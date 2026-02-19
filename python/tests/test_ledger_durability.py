"""Tests for ledger durability fixes: flush_user, credit-path flushing, background flush startup, vault caching."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache, _CacheEntry
from thebrain_mcp.vault import PersonalBrainVault


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
        ledger.balance_api_sats = 500
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
        assert stored_ledger.balance_api_sats == 1000
        assert "inv-1" not in stored_ledger.pending_invoices


# ---------------------------------------------------------------------------
# credits.py flush integration
# ---------------------------------------------------------------------------


class TestCreditPathFlushing:
    @pytest.mark.asyncio
    async def test_purchase_credits_flushes_pending_invoice(self) -> None:
        """purchase_credits must flush to vault after adding pending invoice."""
        from thebrain_mcp.tools.credits import purchase_tax_credits_tool

        cache = _make_cache()
        btcpay = _mock_btcpay({"id": "inv-42", "checkoutLink": "https://pay.example.com"})

        result = await purchase_tax_credits_tool(btcpay, cache, "user-1", 1000)

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
        assert stored_ledger.balance_api_sats == 1000
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
        assert ledger2.balance_api_sats == 500
        assert "inv-1" not in ledger2.pending_invoices
        assert ledger2.total_deposited_api_sats == 500

    @pytest.mark.asyncio
    async def test_idempotency_correct_after_cache_rebuild(self) -> None:
        """After cache loss + vault reload, check_payment should correctly say 'already credited'."""
        from thebrain_mcp.tools.credits import check_payment_tool

        # Build a ledger where inv-1 was already credited
        ledger = UserLedger(
            balance_api_sats=500,
            total_deposited_api_sats=500,
            credited_invoices=["inv-1"],
        )
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
        assert result["balance_api_sats"] == 500


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

        with patch.object(srv, "_get_commerce_vault", return_value=mock_vault), \
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

        with patch.object(srv, "_get_commerce_vault", return_value=mock_vault), \
             patch("thebrain_mcp.server.LedgerCache", return_value=mock_cache), \
             patch("asyncio.ensure_future", side_effect=RuntimeError("no loop")):
            cache = srv._get_ledger_cache()

        # Should succeed despite RuntimeError
        assert cache is mock_cache

        srv._ledger_cache = None


# ---------------------------------------------------------------------------
# credited_invoices tracking
# ---------------------------------------------------------------------------


class TestCreditedInvoices:
    def test_credit_deposit_tracks_invoice(self) -> None:
        """credit_deposit adds invoice_id to credited_invoices."""
        ledger = UserLedger()
        ledger.credit_deposit(1000, "inv-1")
        assert "inv-1" in ledger.credited_invoices

    def test_credit_deposit_removes_from_pending(self) -> None:
        """credit_deposit removes invoice from pending_invoices."""
        ledger = UserLedger(pending_invoices=["inv-1"])
        ledger.credit_deposit(1000, "inv-1")
        assert "inv-1" not in ledger.pending_invoices
        assert "inv-1" in ledger.credited_invoices

    def test_credit_deposit_idempotent(self) -> None:
        """credit_deposit doesn't duplicate invoice in credited_invoices."""
        ledger = UserLedger()
        ledger.credit_deposit(1000, "inv-1")
        ledger.credit_deposit(500, "inv-1")  # duplicate call
        assert ledger.credited_invoices.count("inv-1") == 1

    def test_credited_invoices_serialization_roundtrip(self) -> None:
        """credited_invoices survive to_json → from_json."""
        ledger = UserLedger(credited_invoices=["inv-a", "inv-b"])
        ledger.credit_deposit(100, "inv-c")
        restored = UserLedger.from_json(ledger.to_json())
        assert set(restored.credited_invoices) == {"inv-a", "inv-b", "inv-c"}

    def test_from_json_missing_credited_invoices(self) -> None:
        """Backwards compat: missing credited_invoices defaults to empty list."""
        data = json.dumps({"v": 1, "balance_sats": 100})
        ledger = UserLedger.from_json(data)
        assert ledger.credited_invoices == []
        assert ledger.balance_api_sats == 100


# ---------------------------------------------------------------------------
# restore_credits_tool
# ---------------------------------------------------------------------------


class TestRestoreCredits:
    @pytest.mark.asyncio
    async def test_restore_settled_invoice(self) -> None:
        """restore_credits credits balance from a Settled invoice."""
        from thebrain_mcp.tools.credits import restore_credits_tool

        cache = _make_cache()
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "1000"})

        result = await restore_credits_tool(btcpay, cache, "user-1", "inv-1")

        assert result["success"] is True
        assert result["credits_granted"] == 1000
        assert result["balance_api_sats"] == 1000
        # Verify flushed to vault
        assert cache._vault.store_ledger.call_count >= 1

    @pytest.mark.asyncio
    async def test_restore_idempotent(self) -> None:
        """restore_credits won't double-credit an already-credited invoice."""
        from thebrain_mcp.tools.credits import restore_credits_tool

        cache = _make_cache()
        # Pre-credit the invoice
        ledger = await cache.get("user-1")
        ledger.credit_deposit(1000, "inv-1")
        cache.mark_dirty("user-1")
        cache._vault.store_ledger.reset_mock()

        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "1000"})
        result = await restore_credits_tool(btcpay, cache, "user-1", "inv-1")

        assert result["success"] is True
        assert result["credits_granted"] == 0
        assert result["balance_api_sats"] == 1000
        assert "already credited" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_restore_non_settled_invoice_fails(self) -> None:
        """restore_credits rejects invoices that aren't Settled."""
        from thebrain_mcp.tools.credits import restore_credits_tool

        cache = _make_cache()
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Processing", "amount": "1000"})

        result = await restore_credits_tool(btcpay, cache, "user-1", "inv-1")

        assert result["success"] is False
        assert "Processing" in result["error"]

    @pytest.mark.asyncio
    async def test_restore_with_tier_multiplier(self) -> None:
        """restore_credits applies tier multiplier."""
        from thebrain_mcp.tools.credits import restore_credits_tool

        cache = _make_cache()
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "100"})

        tier_config = json.dumps({"premium": {"credit_multiplier": 3}})
        user_tiers = json.dumps({"user-1": "premium"})

        result = await restore_credits_tool(
            btcpay, cache, "user-1", "inv-1",
            tier_config_json=tier_config, user_tiers_json=user_tiers,
        )

        assert result["success"] is True
        assert result["credits_granted"] == 300
        assert result["multiplier"] == 3

    @pytest.mark.asyncio
    async def test_restore_survives_cache_rebuild(self) -> None:
        """Restored credits survive cache loss via vault flush."""
        from thebrain_mcp.tools.credits import restore_credits_tool

        vault = AsyncMock()
        vault.fetch_ledger = AsyncMock(return_value=None)
        vault.store_ledger = AsyncMock()
        cache = LedgerCache(vault)

        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "750"})
        await restore_credits_tool(btcpay, cache, "user-1", "inv-1")

        # Capture flushed data
        flushed_json = vault.store_ledger.call_args[0][1]

        # Simulate cache loss
        vault2 = AsyncMock()
        vault2.fetch_ledger = AsyncMock(return_value=flushed_json)
        vault2.store_ledger = AsyncMock()
        cache2 = LedgerCache(vault2)

        ledger2 = await cache2.get("user-1")
        assert ledger2.balance_api_sats == 750
        assert "inv-1" in ledger2.credited_invoices


# ---------------------------------------------------------------------------
# PersonalBrainVault caching
# ---------------------------------------------------------------------------


def _mock_api():
    """Create a mock TheBrainAPI with common vault methods."""
    api = AsyncMock()

    # Stubs for note operations
    class FakeNote:
        def __init__(self, md):
            self.markdown = md

    api.get_note = AsyncMock(return_value=FakeNote(None))
    api.create_or_update_note = AsyncMock()
    api.create_thought = AsyncMock(return_value={"id": "new-thought-id"})

    class FakeGraph:
        def __init__(self, children=None):
            self.children = children or []

    api._FakeNote = FakeNote
    api._FakeGraph = FakeGraph
    return api


class TestPersonalBrainVaultCaching:
    @pytest.mark.asyncio
    async def test_second_flush_skips_graph_call(self) -> None:
        """After first store_ledger, second call on same day uses cached child ID."""
        api = _mock_api()

        # Set up: index returns a ledger parent
        index_data = json.dumps({"user-1/ledger": "ledger-parent-id"})
        api.get_note = AsyncMock(return_value=api._FakeNote(index_data))

        # First call: graph returns no children → creates new child
        api.get_thought_graph = AsyncMock(return_value=api._FakeGraph([]))
        api.create_thought = AsyncMock(return_value={"id": "daily-child-id"})

        vault = PersonalBrainVault(api, "brain-1", "home-id")
        result1 = await vault.store_ledger("user-1", '{"balance": 100}')
        assert result1 == "daily-child-id"
        assert api.get_thought_graph.call_count == 1

        # Second call: should use cached ID, skip graph call
        api.get_thought_graph.reset_mock()
        api.create_or_update_note.reset_mock()
        result2 = await vault.store_ledger("user-1", '{"balance": 200}')
        assert result2 == "daily-child-id"
        api.get_thought_graph.assert_not_called()
        api.create_or_update_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_cache_falls_through(self) -> None:
        """If cached daily child set_note fails, evicts and does full lookup."""
        from thebrain_mcp.api.client import TheBrainAPIError

        api = _mock_api()

        # Set up: index returns a ledger parent
        index_data = json.dumps({"user-1/ledger": "ledger-parent-id"})

        # Manually populate the cache
        vault = PersonalBrainVault(api, "brain-1", "home-id")
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        vault._daily_child_cache[f"user-1/{today}"] = "stale-child-id"

        # First call to create_or_update_note fails (stale cache)
        call_count = 0

        async def note_side_effect(brain_id, thought_id, content):
            nonlocal call_count
            call_count += 1
            if thought_id == "stale-child-id":
                raise TheBrainAPIError("404 not found")
            # Second call succeeds (after fallthrough)

        api.create_or_update_note = AsyncMock(side_effect=note_side_effect)
        api.get_note = AsyncMock(return_value=api._FakeNote(index_data))

        # Graph returns existing child with today's date
        class FakeChild:
            def __init__(self, name, id):
                self.name = name
                self.id = id

        api.get_thought_graph = AsyncMock(
            return_value=api._FakeGraph([FakeChild(today, "real-child-id")])
        )

        result = await vault.store_ledger("user-1", '{"balance": 300}')
        assert result == "real-child-id"
        # Stale entry should be evicted, new one cached
        assert vault._daily_child_cache[f"user-1/{today}"] == "real-child-id"

    @pytest.mark.asyncio
    async def test_index_cache_avoids_repeat_reads(self) -> None:
        """After first _read_index, subsequent calls use the in-memory cache."""
        api = _mock_api()

        index_data = json.dumps({"user-1/ledger": "ledger-parent-id"})
        api.get_note = AsyncMock(return_value=api._FakeNote(index_data))

        vault = PersonalBrainVault(api, "brain-1", "home-id")

        # First read
        index1 = await vault._read_index()
        assert index1 == {"user-1/ledger": "ledger-parent-id"}
        assert api.get_note.call_count == 1

        # Second read — should use cache, no API call
        api.get_note.reset_mock()
        index2 = await vault._read_index()
        assert index2 == {"user-1/ledger": "ledger-parent-id"}
        api.get_note.assert_not_called()
