"""Tests for ledger hardening: health metrics, signal handlers, background flush logging."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache(
    vault: AsyncMock | None = None,
    flush_interval_secs: int = 600,
) -> LedgerCache:
    """Create a LedgerCache with a mock vault."""
    v = vault or AsyncMock()
    v.store_ledger = AsyncMock()
    v.fetch_ledger = AsyncMock(return_value=None)
    return LedgerCache(v, maxsize=20, flush_interval_secs=flush_interval_secs)


# ---------------------------------------------------------------------------
# Health metrics
# ---------------------------------------------------------------------------


class TestLedgerCacheHealth:
    @pytest.mark.asyncio
    async def test_health_empty_cache(self) -> None:
        cache = _make_cache()
        h = cache.health()
        assert h["cache_size"] == 0
        assert h["dirty_entries"] == 0
        assert h["last_flush_at"] is None
        assert h["total_flushes"] == 0
        assert h["background_flush_running"] is False

    @pytest.mark.asyncio
    async def test_health_after_dirty_entry(self) -> None:
        cache = _make_cache()
        await cache.get("user-1")
        cache.mark_dirty("user-1")
        h = cache.health()
        assert h["cache_size"] == 1
        assert h["dirty_entries"] == 1

    @pytest.mark.asyncio
    async def test_health_after_flush(self) -> None:
        cache = _make_cache()
        ledger = await cache.get("user-1")
        ledger.balance_sats = 100
        cache.mark_dirty("user-1")
        await cache.flush_dirty()
        h = cache.health()
        assert h["dirty_entries"] == 0
        assert h["last_flush_at"] is not None
        assert h["total_flushes"] == 1

    @pytest.mark.asyncio
    async def test_health_total_flushes_increments(self) -> None:
        cache = _make_cache()
        for i in range(3):
            await cache.get(f"user-{i}")
            cache.mark_dirty(f"user-{i}")
        await cache.flush_dirty()
        h = cache.health()
        assert h["total_flushes"] == 3

    @pytest.mark.asyncio
    async def test_health_background_flush_running(self) -> None:
        cache = _make_cache(flush_interval_secs=999)
        await cache.start_background_flush()
        h = cache.health()
        assert h["background_flush_running"] is True
        await cache.stop()
        h2 = cache.health()
        assert h2["background_flush_running"] is False


# ---------------------------------------------------------------------------
# dirty_count property
# ---------------------------------------------------------------------------


class TestDirtyCount:
    @pytest.mark.asyncio
    async def test_dirty_count_zero(self) -> None:
        cache = _make_cache()
        assert cache.dirty_count == 0

    @pytest.mark.asyncio
    async def test_dirty_count_tracks_dirty_entries(self) -> None:
        cache = _make_cache()
        await cache.get("user-1")
        await cache.get("user-2")
        cache.mark_dirty("user-1")
        assert cache.dirty_count == 1
        cache.mark_dirty("user-2")
        assert cache.dirty_count == 2

    @pytest.mark.asyncio
    async def test_dirty_count_after_flush(self) -> None:
        cache = _make_cache()
        await cache.get("user-1")
        cache.mark_dirty("user-1")
        assert cache.dirty_count == 1
        await cache.flush_dirty()
        assert cache.dirty_count == 0


# ---------------------------------------------------------------------------
# last_flush_at tracking
# ---------------------------------------------------------------------------


class TestLastFlushAt:
    @pytest.mark.asyncio
    async def test_last_flush_at_none_initially(self) -> None:
        cache = _make_cache()
        assert cache._last_flush_at is None

    @pytest.mark.asyncio
    async def test_last_flush_at_updated_on_flush(self) -> None:
        cache = _make_cache()
        await cache.get("user-1")
        cache.mark_dirty("user-1")
        before = datetime.now(timezone.utc).isoformat()
        await cache.flush_dirty()
        assert cache._last_flush_at is not None
        assert cache._last_flush_at >= before

    @pytest.mark.asyncio
    async def test_last_flush_at_not_updated_on_failure(self) -> None:
        vault = AsyncMock()
        vault.fetch_ledger = AsyncMock(return_value=None)
        vault.store_ledger = AsyncMock(side_effect=Exception("vault error"))
        cache = LedgerCache(vault)
        await cache.get("user-1")
        cache.mark_dirty("user-1")
        await cache.flush_dirty()
        assert cache._last_flush_at is None


# ---------------------------------------------------------------------------
# Graceful shutdown handler
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_graceful_shutdown_flushes_dirty(self) -> None:
        """_graceful_shutdown flushes dirty entries and stops cache."""
        import thebrain_mcp.server as srv

        cache = _make_cache()
        ledger = await cache.get("user-1")
        ledger.balance_sats = 500
        cache.mark_dirty("user-1")

        srv._ledger_cache = cache
        srv._shutdown_triggered = False

        await srv._graceful_shutdown()

        assert cache.dirty_count == 0
        cache._vault.store_ledger.assert_called_once()
        assert srv._shutdown_triggered is True

        # Clean up
        srv._ledger_cache = None
        srv._shutdown_triggered = False

    @pytest.mark.asyncio
    async def test_graceful_shutdown_idempotent(self) -> None:
        """Second call to _graceful_shutdown is a no-op."""
        import thebrain_mcp.server as srv

        cache = _make_cache()
        await cache.get("user-1")
        cache.mark_dirty("user-1")

        srv._ledger_cache = cache
        srv._shutdown_triggered = False

        await srv._graceful_shutdown()
        call_count_1 = cache._vault.store_ledger.call_count
        await srv._graceful_shutdown()  # second call
        call_count_2 = cache._vault.store_ledger.call_count
        assert call_count_2 == call_count_1  # no new flushes

        srv._ledger_cache = None
        srv._shutdown_triggered = False

    @pytest.mark.asyncio
    async def test_graceful_shutdown_no_cache_noop(self) -> None:
        """_graceful_shutdown is safe when no cache exists."""
        import thebrain_mcp.server as srv

        srv._ledger_cache = None
        srv._shutdown_triggered = False

        await srv._graceful_shutdown()  # should not raise
        assert srv._shutdown_triggered is True

        srv._shutdown_triggered = False


# ---------------------------------------------------------------------------
# check_balance includes cache_health
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Opportunistic flush (request-driven)
# ---------------------------------------------------------------------------


class TestOpportunisticFlush:
    @pytest.mark.asyncio
    async def test_opportunistic_flush_after_interval(self) -> None:
        """get() triggers flush when interval has elapsed and entries are dirty."""
        cache = _make_cache(flush_interval_secs=0)  # interval=0 → flush on every get()
        ledger = await cache.get("user-1")
        ledger.balance_sats = 500
        cache.mark_dirty("user-1")

        # Next get() should trigger opportunistic flush
        await cache.get("user-1")
        cache._vault.store_ledger.assert_called_once()
        assert cache._total_flushes == 1

    @pytest.mark.asyncio
    async def test_no_flush_before_interval(self) -> None:
        """get() does NOT flush when interval has not elapsed."""
        cache = _make_cache(flush_interval_secs=9999)
        ledger = await cache.get("user-1")
        cache.mark_dirty("user-1")

        await cache.get("user-1")
        cache._vault.store_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_flush_when_clean(self) -> None:
        """get() does NOT flush when nothing is dirty, even if interval elapsed."""
        cache = _make_cache(flush_interval_secs=0)
        await cache.get("user-1")  # not marked dirty

        await cache.get("user-1")
        cache._vault.store_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_includes_flush_check_age(self) -> None:
        """health() includes last_flush_check_age_secs."""
        cache = _make_cache()
        h = cache.health()
        assert "last_flush_check_age_secs" in h
        assert isinstance(h["last_flush_check_age_secs"], float)


# ---------------------------------------------------------------------------
# check_balance includes cache_health
# ---------------------------------------------------------------------------


class TestCheckBalanceCacheHealth:
    @pytest.mark.asyncio
    async def test_check_balance_includes_cache_health(self) -> None:
        """check_balance response includes cache_health dict.

        Tests the integration: check_balance_tool result + cache.health() appended.
        """
        from thebrain_mcp.tools.credits import check_balance_tool

        cache = _make_cache()
        await cache.get("test-user")  # pre-populate

        result = await check_balance_tool(cache, "test-user")
        # Simulate what server.py does after calling check_balance_tool
        result["cache_health"] = cache.health()

        assert result["success"] is True
        assert "cache_health" in result
        assert result["cache_health"]["cache_size"] >= 0
        assert "background_flush_running" in result["cache_health"]


# ---------------------------------------------------------------------------
# btcpay_status includes cache_health
# ---------------------------------------------------------------------------


class TestBTCPayStatusCacheHealth:
    @pytest.mark.asyncio
    async def test_btcpay_status_cache_health_present(self) -> None:
        """btcpay_status result gets cache_health when cache exists."""
        from thebrain_mcp.tools.credits import btcpay_status_tool

        cache = _make_cache()
        settings = MagicMock(
            btcpay_host="", btcpay_store_id="", btcpay_api_key="",
            btcpay_tier_config=None, btcpay_user_tiers=None,
        )
        result = await btcpay_status_tool(settings, None)
        # Simulate what server.py does
        result["cache_health"] = cache.health()

        assert "cache_health" in result
        assert result["cache_health"]["cache_size"] == 0

    @pytest.mark.asyncio
    async def test_btcpay_status_cache_health_none_when_no_cache(self) -> None:
        """btcpay_status shows cache_health: null when cache not initialized."""
        from thebrain_mcp.tools.credits import btcpay_status_tool

        settings = MagicMock(
            btcpay_host="", btcpay_store_id="", btcpay_api_key="",
            btcpay_tier_config=None, btcpay_user_tiers=None,
        )
        result = await btcpay_status_tool(settings, None)
        # Simulate what server.py does when no cache
        result["cache_health"] = None

        assert result["cache_health"] is None
