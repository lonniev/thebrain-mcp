"""Tests for LedgerCache: LRU eviction, background flush, concurrency."""

import asyncio

import pytest
from unittest.mock import AsyncMock

from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_vault(ledger_json: str | None = None, fail_store: bool = False):
    """Create a mock vault with fetch_ledger/store_ledger."""
    vault = AsyncMock()
    vault.fetch_ledger = AsyncMock(return_value=ledger_json)
    if fail_store:
        vault.store_ledger = AsyncMock(side_effect=Exception("vault write failed"))
    else:
        vault.store_ledger = AsyncMock(return_value="ledger-thought-id")
    return vault


# ---------------------------------------------------------------------------
# Cache miss / hit
# ---------------------------------------------------------------------------


class TestLedgerCacheGetMiss:
    @pytest.mark.asyncio
    async def test_cache_miss_returns_fresh_ledger(self) -> None:
        vault = _mock_vault(ledger_json=None)
        cache = LedgerCache(vault, maxsize=5)
        ledger = await cache.get("user1")
        assert ledger.balance_api_sats == 0
        vault.fetch_ledger.assert_called_once_with("user1")

    @pytest.mark.asyncio
    async def test_cache_miss_loads_from_vault(self) -> None:
        stored = UserLedger(balance_api_sats=500)
        vault = _mock_vault(ledger_json=stored.to_json())
        cache = LedgerCache(vault, maxsize=5)
        ledger = await cache.get("user1")
        assert ledger.balance_api_sats == 500

    @pytest.mark.asyncio
    async def test_cache_miss_vault_error_returns_fresh(self) -> None:
        vault = AsyncMock()
        vault.fetch_ledger = AsyncMock(side_effect=Exception("network error"))
        cache = LedgerCache(vault, maxsize=5)
        ledger = await cache.get("user1")
        assert ledger.balance_api_sats == 0


class TestLedgerCacheGetHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_same_object(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        ledger1 = await cache.get("user1")
        ledger2 = await cache.get("user1")
        assert ledger1 is ledger2
        # Vault should only be called once
        vault.fetch_ledger.assert_called_once()

    @pytest.mark.asyncio
    async def test_mutations_visible_on_cache_hit(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        ledger = await cache.get("user1")
        ledger.balance_api_sats = 999
        cache.mark_dirty("user1")
        ledger2 = await cache.get("user1")
        assert ledger2.balance_api_sats == 999


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


class TestLedgerCacheEviction:
    @pytest.mark.asyncio
    async def test_eviction_at_capacity(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=2)
        await cache.get("user1")
        await cache.get("user2")
        await cache.get("user3")  # should evict user1
        assert cache.size == 2
        # user1 was evicted, next access should reload from vault
        vault.fetch_ledger.reset_mock()
        await cache.get("user1")
        vault.fetch_ledger.assert_called_with("user1")

    @pytest.mark.asyncio
    async def test_eviction_flushes_dirty_entry(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=2)
        ledger1 = await cache.get("user1")
        ledger1.balance_api_sats = 42
        cache.mark_dirty("user1")
        await cache.get("user2")
        await cache.get("user3")  # evicts user1
        vault.store_ledger.assert_called_once()
        args = vault.store_ledger.call_args[0]
        assert args[0] == "user1"

    @pytest.mark.asyncio
    async def test_eviction_does_not_flush_clean_entry(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=2)
        await cache.get("user1")  # clean
        await cache.get("user2")
        await cache.get("user3")  # evicts user1 (clean)
        vault.store_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_lru_order_access_refreshes(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=2)
        await cache.get("user1")
        await cache.get("user2")
        await cache.get("user1")   # refresh user1 — user2 is now LRU
        await cache.get("user3")   # evicts user2
        assert cache.size == 2
        # user1 should still be cached (no vault call)
        vault.fetch_ledger.reset_mock()
        ledger = await cache.get("user1")
        vault.fetch_ledger.assert_not_called()


# ---------------------------------------------------------------------------
# Dirty tracking and flush
# ---------------------------------------------------------------------------


class TestLedgerCacheFlush:
    @pytest.mark.asyncio
    async def test_mark_dirty_and_flush(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        ledger = await cache.get("user1")
        ledger.balance_api_sats = 100
        cache.mark_dirty("user1")
        count = await cache.flush_dirty()
        assert count == 1
        vault.store_ledger.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_skips_clean_entries(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        await cache.get("user1")  # clean
        count = await cache.flush_dirty()
        assert count == 0
        vault.store_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_clears_dirty_flag(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        ledger = await cache.get("user1")
        cache.mark_dirty("user1")
        await cache.flush_dirty()
        # Second flush should be a no-op
        vault.store_ledger.reset_mock()
        count = await cache.flush_dirty()
        assert count == 0
        vault.store_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_failure_keeps_dirty(self) -> None:
        vault = _mock_vault(fail_store=True)
        cache = LedgerCache(vault, maxsize=5)
        await cache.get("user1")
        cache.mark_dirty("user1")
        count = await cache.flush_dirty()
        assert count == 0  # failed, entry still dirty
        # Retry should attempt again
        vault.store_ledger.reset_mock()
        vault.store_ledger = AsyncMock(return_value="ok")
        count = await cache.flush_dirty()
        assert count == 1

    @pytest.mark.asyncio
    async def test_flush_all(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        await cache.get("user1")
        await cache.get("user2")
        cache.mark_dirty("user1")
        cache.mark_dirty("user2")
        count = await cache.flush_all()
        assert count == 2

    @pytest.mark.asyncio
    async def test_mark_dirty_nonexistent_noop(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        cache.mark_dirty("ghost")  # should not raise


# ---------------------------------------------------------------------------
# Snapshot all
# ---------------------------------------------------------------------------


class TestLedgerCacheSnapshotAll:
    @pytest.mark.asyncio
    async def test_snapshot_all_iterates_entries(self) -> None:
        vault = _mock_vault()
        vault.snapshot_ledger = AsyncMock(return_value="snap-id")
        cache = LedgerCache(vault, maxsize=5)
        await cache.get("user1")
        await cache.get("user2")
        count = await cache.snapshot_all("2026-02-16T12:00:00Z")
        assert count == 2
        assert vault.snapshot_ledger.call_count == 2

    @pytest.mark.asyncio
    async def test_snapshot_all_empty_cache(self) -> None:
        vault = _mock_vault()
        vault.snapshot_ledger = AsyncMock(return_value="snap-id")
        cache = LedgerCache(vault, maxsize=5)
        count = await cache.snapshot_all("2026-02-16T12:00:00Z")
        assert count == 0
        vault.snapshot_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_snapshot_all_skips_failures(self) -> None:
        vault = _mock_vault()
        call_count = 0

        async def snapshot_side_effect(user_id, ledger_json, ts):
            nonlocal call_count
            call_count += 1
            if user_id == "user1":
                raise Exception("vault error")
            return "snap-id"

        vault.snapshot_ledger = AsyncMock(side_effect=snapshot_side_effect)
        cache = LedgerCache(vault, maxsize=5)
        await cache.get("user1")
        await cache.get("user2")
        count = await cache.snapshot_all("2026-02-16T12:00:00Z")
        assert count == 1  # user1 failed, user2 succeeded
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_snapshot_all_counts_none_as_skipped(self) -> None:
        vault = _mock_vault()
        vault.snapshot_ledger = AsyncMock(return_value=None)
        cache = LedgerCache(vault, maxsize=5)
        await cache.get("user1")
        count = await cache.snapshot_all("2026-02-16T12:00:00Z")
        assert count == 0  # None means no ledger thought existed


# ---------------------------------------------------------------------------
# Background flush
# ---------------------------------------------------------------------------


class TestLedgerCacheBackgroundFlush:
    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5, flush_interval_secs=1)
        await cache.start_background_flush()
        assert cache._flush_task is not None
        await cache.stop()
        assert cache._flush_task is None

    @pytest.mark.asyncio
    async def test_background_flush_writes_dirty(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5, flush_interval_secs=0.1)
        ledger = await cache.get("user1")
        ledger.balance_api_sats = 77
        cache.mark_dirty("user1")
        await cache.start_background_flush()
        await asyncio.sleep(0.3)  # wait for at least one flush cycle
        await cache.stop()
        vault.store_ledger.assert_called()

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5, flush_interval_secs=999)
        await cache.start_background_flush()
        ledger = await cache.get("user1")
        cache.mark_dirty("user1")
        await cache.stop()  # should flush before returning
        vault.store_ledger.assert_called_once()

    @pytest.mark.asyncio
    async def test_double_start_idempotent(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5, flush_interval_secs=1)
        await cache.start_background_flush()
        task1 = cache._flush_task
        await cache.start_background_flush()
        assert cache._flush_task is task1  # same task, not duplicated
        await cache.stop()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestLedgerCacheConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_get_same_user(self) -> None:
        """Two concurrent gets for the same user should both see the same ledger."""
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)

        results = await asyncio.gather(
            cache.get("user1"),
            cache.get("user1"),
        )
        assert results[0] is results[1]

    @pytest.mark.asyncio
    async def test_concurrent_get_different_users(self) -> None:
        """Concurrent gets for different users should not interfere."""
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)

        results = await asyncio.gather(
            cache.get("user1"),
            cache.get("user2"),
        )
        assert results[0] is not results[1]
        assert cache.size == 2


# ---------------------------------------------------------------------------
# Size property
# ---------------------------------------------------------------------------


class TestLedgerCacheSize:
    @pytest.mark.asyncio
    async def test_size_empty(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        assert cache.size == 0

    @pytest.mark.asyncio
    async def test_size_after_gets(self) -> None:
        vault = _mock_vault()
        cache = LedgerCache(vault, maxsize=5)
        await cache.get("user1")
        await cache.get("user2")
        assert cache.size == 2
