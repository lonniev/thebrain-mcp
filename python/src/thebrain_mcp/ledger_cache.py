"""In-memory LRU cache for UserLedger with write-behind flush to vault.

The cache is the hot path for all credit operations. The vault is the
durable backing store, updated asynchronously every ``flush_interval_secs``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from thebrain_mcp.ledger import UserLedger

if TYPE_CHECKING:
    from thebrain_mcp.vault import CredentialVault

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
        vault: CredentialVault,
        maxsize: int = 20,
        flush_interval_secs: int = 60,
    ) -> None:
        self._vault = vault
        self._maxsize = maxsize
        self._flush_interval = flush_interval_secs
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._flush_task: asyncio.Task[None] | None = None

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        """Get or create a per-user lock."""
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def get(self, user_id: str) -> UserLedger:
        """Return the cached ledger, loading from vault on miss."""
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
        try:
            await self._vault.store_ledger(user_id, entry.ledger.to_json())
            entry.dirty = False
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
        try:
            while True:
                await asyncio.sleep(self._flush_interval)
                count = await self.flush_dirty()
                if count > 0:
                    logger.debug("Background flush: wrote %d ledger(s).", count)
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
