"""Tests for ledger durability fixes: flush_user, credit-path flushing, background flush startup."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache, _CacheEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache(vault: AsyncMock | None = None) -> LedgerCache:
    """Create a LedgerCache with a mock vault."""
    v = vault or AsyncMock()
    v.store_ledger = AsyncMock()
    v.fetch_ledger = AsyncMock(return_value=None)
    return LedgerCache(v, maxsize=20, flush_interval_secs=600)


def _mock_btcpay(invoice_response: dict | None = None):
    """Create a mock BTCPayClient."""
    from thebrain_mcp.btcpay_client import BTCPayClient

    client = AsyncMock(spec=BTCPayClient)
    resp = invoice_response or {"id": "inv-1", "checkoutLink": "https://pay.example.com/inv-1"}
    client.create_invoice = AsyncMock(return_value=resp)
    client.get_invoice = AsyncMock(return_value=resp)
    return client


# ---------------------------------------------------------------------------
# LedgerCache.flush_user
# ---------------------------------------------------------------------------


class TestFlushUser:
    @pytest.mark.asyncio
    async def test_flush_dirty_entry_writes_to_vault(self) -> None:
        """flush_user writes a dirty entry to vault and clears dirty flag."""
        cache = _make_cache()
        ledger = await cache.get("user-1")
        ledger.balance_sats = 500
        cache.mark_dirty("user-1")

        result = await cache.flush_user("user-1")

        assert result is True
        cache._vault.store_ledger.assert_called_once_with("user-1", ledger.to_json())
        # Dirty flag cleared
        assert cache._entries["user-1"].dirty is False

    @pytest.mark.asyncio
    async def test_flush_clean_entry_is_noop(self) -> None:
        """flush_user on a non-dirty entry does nothing."""
        cache = _make_cache()
        await cache.get("user-1")
        # Not marked dirty

        result = await cache.flush_user("user-1")

        assert result is True
        cache._vault.store_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_missing_user_is_noop(self) -> None:
        """flush_user on a user not in cache does nothing."""
        cache = _make_cache()

        result = await cache.flush_user("nonexistent")

        assert result is True
        cache._vault.store_ledger.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_vault_failure_returns_false(self) -> None:
        """flush_user returns False when vault write fails."""
        vault = AsyncMock()
        vault.fetch_ledger = AsyncMock(return_value=None)
        vault.store_ledger = AsyncMock(side_effect=Exception("vault down"))
        cache = LedgerCache(vault)

        await cache.get("user-1")
        cache.mark_dirty("user-1")

        result = await cache.flush_user("user-1")

        assert result is False
        # Entry stays dirty for retry
        assert cache._entries["user-1"].dirty is True

    @pytest.mark.asyncio
    async def test_flush_user_after_credit_deposit(self) -> None:
        """Simulates the critical check_payment path: credit → mark_dirty → flush."""
        cache = _make_cache()
        ledger = await cache.get("user-1")
        ledger.pending_invoices.append("inv-1")
        cache.mark_dirty("user-1")

        # Simulate check_payment crediting
        ledger.credit_deposit(1000, "inv-1")
        cache.mark_dirty("user-1")
        await cache.flush_user("user-1")

        # Verify vault received the credited ledger
        stored_json = cache._vault.store_ledger.call_args[0][1]
        stored_ledger = UserLedger.from_json(stored_json)
        assert stored_ledger.balance_sats == 1000
        assert "inv-1" not in stored_ledger.pending_invoices


# ---------------------------------------------------------------------------
# credits.py flush integration
# ---------------------------------------------------------------------------


class TestCreditPathFlushing:
    @pytest.mark.asyncio
    async def test_purchase_credits_flushes_pending_invoice(self) -> None:
        """purchase_credits must flush to vault after adding pending invoice."""
        from thebrain_mcp.tools.credits import purchase_credits_tool

        cache = _make_cache()
        btcpay = _mock_btcpay({"id": "inv-42", "checkoutLink": "https://pay.example.com"})

        result = await purchase_credits_tool(btcpay, cache, "user-1", 1000)

        assert result["success"] is True
        # Verify flush was called (store_ledger invoked)
        cache._vault.store_ledger.assert_called_once()
        stored_json = cache._vault.store_ledger.call_args[0][1]
        stored_ledger = UserLedger.from_json(stored_json)
        assert "inv-42" in stored_ledger.pending_invoices

    @pytest.mark.asyncio
    async def test_check_payment_settled_flushes_credits(self) -> None:
        """check_payment must flush to vault after crediting balance."""
        from thebrain_mcp.tools.credits import check_payment_tool

        cache = _make_cache()
        ledger = await cache.get("user-1")
        ledger.pending_invoices.append("inv-1")
        cache.mark_dirty("user-1")
        # Reset the mock to only track flushes from check_payment
        cache._vault.store_ledger.reset_mock()

        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "1000"})

        result = await check_payment_tool(btcpay, cache, "user-1", "inv-1")

        assert result["success"] is True
        assert result["credits_granted"] == 1000
        # Verify vault flush happened
        assert cache._vault.store_ledger.call_count >= 1
        stored_json = cache._vault.store_ledger.call_args[0][1]
        stored_ledger = UserLedger.from_json(stored_json)
        assert stored_ledger.balance_sats == 1000
        assert "inv-1" not in stored_ledger.pending_invoices

    @pytest.mark.asyncio
    async def test_check_payment_expired_flushes(self) -> None:
        """check_payment must flush after removing expired invoice from pending."""
        from thebrain_mcp.tools.credits import check_payment_tool

        cache = _make_cache()
        ledger = await cache.get("user-1")
        ledger.pending_invoices.append("inv-1")
        cache.mark_dirty("user-1")
        cache._vault.store_ledger.reset_mock()

        btcpay = _mock_btcpay({"id": "inv-1", "status": "Expired"})

        result = await check_payment_tool(btcpay, cache, "user-1", "inv-1")

        assert result["status"] == "Expired"
        # Verify expired invoice removal was flushed
        assert cache._vault.store_ledger.call_count >= 1
        stored_json = cache._vault.store_ledger.call_args[0][1]
        stored_ledger = UserLedger.from_json(stored_json)
        assert "inv-1" not in stored_ledger.pending_invoices

    @pytest.mark.asyncio
    async def test_credits_survive_cache_rebuild(self) -> None:
        """Critical integration test: credits granted → flushed → cache lost → reloaded from vault."""
        from thebrain_mcp.tools.credits import check_payment_tool

        # Step 1: Set up cache with pending invoice
        vault = AsyncMock()
        vault.fetch_ledger = AsyncMock(return_value=None)
        vault.store_ledger = AsyncMock()
        cache = LedgerCache(vault)

        ledger = await cache.get("user-1")
        ledger.pending_invoices.append("inv-1")
        cache.mark_dirty("user-1")

        # Step 2: check_payment credits and flushes
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "500"})
        await check_payment_tool(btcpay, cache, "user-1", "inv-1")

        # Capture what was written to vault
        assert vault.store_ledger.call_count >= 1
        flushed_json = vault.store_ledger.call_args[0][1]

        # Step 3: Simulate cache loss (server restart)
        vault2 = AsyncMock()
        vault2.fetch_ledger = AsyncMock(return_value=flushed_json)
        vault2.store_ledger = AsyncMock()
        cache2 = LedgerCache(vault2)

        # Step 4: Reload from vault
        ledger2 = await cache2.get("user-1")

        # Step 5: Verify credits survived
        assert ledger2.balance_sats == 500
        assert "inv-1" not in ledger2.pending_invoices
        assert ledger2.total_deposited_sats == 500

    @pytest.mark.asyncio
    async def test_idempotency_correct_after_cache_rebuild(self) -> None:
        """After cache loss + vault reload, check_payment should correctly say 'already credited'."""
        from thebrain_mcp.tools.credits import check_payment_tool

        # Build a ledger where inv-1 was already credited (not in pending)
        ledger = UserLedger(balance_sats=500, total_deposited_sats=500)
        flushed_json = ledger.to_json()

        # New cache loads from vault
        vault = AsyncMock()
        vault.fetch_ledger = AsyncMock(return_value=flushed_json)
        vault.store_ledger = AsyncMock()
        cache = LedgerCache(vault)

        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "500"})
        result = await check_payment_tool(btcpay, cache, "user-1", "inv-1")

        assert result["credits_granted"] == 0
        assert "already credited" in result["message"]
        # Balance should be preserved, not zeroed
        assert result["balance_sats"] == 500


# ---------------------------------------------------------------------------
# Background flush startup
# ---------------------------------------------------------------------------


class TestBackgroundFlushStartup:
    def test_get_ledger_cache_starts_background_flush(self) -> None:
        """_get_ledger_cache() should schedule background flush on creation."""
        import thebrain_mcp.server as srv

        # Reset singleton
        srv._ledger_cache = None

        mock_vault = MagicMock()
        mock_cache = AsyncMock(spec=LedgerCache)

        with patch.object(srv, "_get_vault", return_value=mock_vault), \
             patch("thebrain_mcp.server.LedgerCache", return_value=mock_cache), \
             patch("asyncio.ensure_future") as mock_ensure:
            cache = srv._get_ledger_cache()

        assert cache is mock_cache
        mock_ensure.assert_called_once()
        # The argument should be the coroutine from start_background_flush
        mock_cache.start_background_flush.assert_called_once()

        # Clean up singleton
        srv._ledger_cache = None

    def test_get_ledger_cache_no_error_without_event_loop(self) -> None:
        """_get_ledger_cache() gracefully handles no running event loop."""
        import thebrain_mcp.server as srv

        srv._ledger_cache = None

        mock_vault = MagicMock()
        mock_cache = AsyncMock(spec=LedgerCache)

        with patch.object(srv, "_get_vault", return_value=mock_vault), \
             patch("thebrain_mcp.server.LedgerCache", return_value=mock_cache), \
             patch("asyncio.ensure_future", side_effect=RuntimeError("no loop")):
            cache = srv._get_ledger_cache()

        # Should succeed despite RuntimeError
        assert cache is mock_cache

        srv._ledger_cache = None
