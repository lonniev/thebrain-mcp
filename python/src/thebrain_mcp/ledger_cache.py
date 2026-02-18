"""In-memory LRU cache for UserLedger with write-behind flush to vault.

The cache is the hot path for all credit operations. The vault is the
durable backing store, updated asynchronously every ``flush_interval_secs``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from thebrain_mcp.ledger import UserLedger

if TYPE_CHECKING:
    from thebrain_mcp.vault_backend import VaultBackend

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    """Internal cache entry wrapping a UserLedger with dirty tracking."""

    ledger: UserLedger
    dirty: bool = False


class LedgerCache:
    """LRU cache for UserLedger objects with write-behind flush.

    - ``get()`` returns a cached ledger or loads from vault on miss.
    - Mutations should be followed by ``mark_dirty(user_id)``.
    - A background task flushes dirty entries to the vault periodically.
    - On LRU eviction, dirty entries are flushed synchronously.
    - Per-user asyncio locks prevent concurrent access races.
    """

    def __init__(
        self,
        vault: VaultBackend,
        maxsize: int = 20,
        flush_interval_secs: int = 60,
    ) -> None:
        self._vault = vault
        self._maxsize = maxsize
        self._flush_interval = flush_interval_secs
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._flush_task: asyncio.Task[None] | None = None
        self._last_flush_at: str | None = None
        self._total_flushes: int = 0
        self._last_flush_check: float = time.monotonic()

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        """Get or create a per-user lock."""
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def _maybe_flush(self) -> None:
        """Flush dirty entries if enough time has passed since the last flush.

        Called from get() to piggyback on request-driven event loop activity.
        In serverless environments where asyncio.sleep() doesn't advance
        between requests, this ensures dirty entries are eventually persisted.
        """
        now = time.monotonic()
        if now - self._last_flush_check < self._flush_interval:
            return
        self._last_flush_check = now
        if self.dirty_count > 0:
            count = await self.flush_dirty()
            if count > 0:
                logger.info("Opportunistic flush: wrote %d ledger(s).", count)

    async def get(self, user_id: str) -> UserLedger:
        """Return the cached ledger, loading from vault on miss."""
        await self._maybe_flush()
        lock = self._get_lock(user_id)
        async with lock:
            if user_id in self._entries:
                self._entries.move_to_end(user_id)
                return self._entries[user_id].ledger

            # Cache miss — load from vault
            ledger = await self._load_from_vault(user_id)

            # Evict LRU if at capacity
            while len(self._entries) >= self._maxsize:
                await self._evict_lru()

            self._entries[user_id] = _CacheEntry(ledger=ledger)
            self._entries.move_to_end(user_id)
            return ledger

    def mark_dirty(self, user_id: str) -> None:
        """Mark a cached entry as dirty (needs flush to vault)."""
        entry = self._entries.get(user_id)
        if entry:
            entry.dirty = True

    async def flush_user(self, user_id: str) -> bool:
        """Immediately flush a single user's entry to vault.

        Use for credit-critical paths (check_payment, purchase_credits)
        where data MUST be durable before returning success.
        Returns True on success, False on failure (logged, not raised).
        """
        entry = self._entries.get(user_id)
        if not entry or not entry.dirty:
            return True  # Nothing to flush
        return await self._flush_entry(user_id, entry)

    async def _load_from_vault(self, user_id: str) -> UserLedger:
        """Load ledger JSON from vault, returning fresh ledger on miss/error."""
        try:
            ledger_json = await self._vault.fetch_ledger(user_id)
        except Exception:
            logger.warning("Failed to load ledger from vault for %s.", user_id)
            return UserLedger()

        if ledger_json is None:
            return UserLedger()
        return UserLedger.from_json(ledger_json)

    async def _evict_lru(self) -> None:
        """Evict the least-recently-used entry, flushing if dirty."""
        if not self._entries:
            return
        user_id, entry = next(iter(self._entries.items()))
        if entry.dirty:
            await self._flush_entry(user_id, entry)
        del self._entries[user_id]
        self._locks.pop(user_id, None)

    async def _flush_entry(self, user_id: str, entry: _CacheEntry) -> bool:
        """Flush a single entry to vault. Returns True on success."""
        from datetime import datetime, timezone

        try:
            await self._vault.store_ledger(user_id, entry.ledger.to_json())
            entry.dirty = False
            self._last_flush_at = datetime.now(timezone.utc).isoformat()
            self._total_flushes += 1
            return True
        except Exception:
            logger.warning("Failed to flush ledger to vault for %s.", user_id)
            return False

    async def flush_dirty(self) -> int:
        """Flush all dirty entries to vault. Returns count of flushed entries."""
        flushed = 0
        for user_id, entry in list(self._entries.items()):
            if entry.dirty:
                if await self._flush_entry(user_id, entry):
                    flushed += 1
        return flushed

    async def snapshot_all(self, timestamp: str) -> int:
        """Snapshot all cached ledgers to vault. Returns count of snapshots created."""
        snapped = 0
        for user_id, entry in list(self._entries.items()):
            try:
                result = await self._vault.snapshot_ledger(
                    user_id, entry.ledger.to_json(), timestamp
                )
                if result is not None:
                    snapped += 1
            except Exception:
                logger.warning("Failed to snapshot ledger for %s.", user_id)
        return snapped

    async def flush_all(self) -> int:
        """Flush every dirty entry (used during shutdown). Returns flush count."""
        return await self.flush_dirty()

    async def start_background_flush(self) -> None:
        """Start the periodic background flush task."""
        if self._flush_task is not None:
            return
        self._flush_task = asyncio.create_task(self._background_flush_loop())

    async def _background_flush_loop(self) -> None:
        """Periodically flush dirty entries until cancelled."""
        logger.warning(
            "Background flush loop started (interval=%ds). "
            "In serverless envs, opportunistic flush handles persistence instead.",
            self._flush_interval,
        )
        cycles = 0
        try:
            while True:
                await asyncio.sleep(self._flush_interval)
                count = await self.flush_dirty()
                cycles += 1
                if count > 0:
                    logger.info(
                        "Background flush: wrote %d ledger(s) "
                        "(cycle %d, total flushes: %d).",
                        count, cycles, self._total_flushes,
                    )
                elif cycles % 10 == 0:
                    # Heartbeat every 10 cycles even when idle
                    logger.info(
                        "Background flush heartbeat: cycle %d, "
                        "cache size %d, dirty %d, total flushes %d.",
                        cycles, self.size, self.dirty_count, self._total_flushes,
                    )
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Cancel background flush and flush all remaining dirty entries."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush_all()

    @property
    def size(self) -> int:
        """Number of entries currently in cache."""
        return len(self._entries)

    @property
    def dirty_count(self) -> int:
        """Number of dirty (unflushed) entries in cache."""
        return sum(1 for e in self._entries.values() if e.dirty)

    def health(self) -> dict[str, object]:
        """Return cache health metrics for monitoring."""
        return {
            "cache_size": self.size,
            "dirty_entries": self.dirty_count,
            "last_flush_at": self._last_flush_at,
            "total_flushes": self._total_flushes,
            "background_flush_running": self._flush_task is not None
                                        and not self._flush_task.done(),
            "last_flush_check_age_secs": round(
                time.monotonic() - self._last_flush_check, 1
            ),
        }
