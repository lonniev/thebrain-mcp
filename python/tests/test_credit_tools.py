"""Tests for credit management tools: purchase_credits, check_payment, check_balance, btcpay_status."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thebrain_mcp.btcpay_client import (
    BTCPayAuthError,
    BTCPayClient,
    BTCPayConnectionError,
    BTCPayError,
    BTCPayServerError,
    BTCPayValidationError,
)
from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache
from thebrain_mcp.tools.credits import (
    ROYALTY_PAYOUT_MAX_SATS,
    _attempt_royalty_payout,
    _get_multiplier,
    _get_tier_info,
    btcpay_status_tool,
    check_balance_tool,
    check_payment_tool,
    compute_low_balance_warning,
    purchase_tax_credits_tool,
)
from thebrain_mcp.utils.constants import MAX_INVOICE_SATS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_btcpay(invoice_response: dict | None = None, error: Exception | None = None):
    """Create a mock BTCPayClient."""
    client = AsyncMock(spec=BTCPayClient)
    if error:
        client.create_invoice = AsyncMock(side_effect=error)
        client.get_invoice = AsyncMock(side_effect=error)
    else:
        resp = invoice_response or {"id": "inv-1", "checkoutLink": "https://pay.example.com/inv-1"}
        client.create_invoice = AsyncMock(return_value=resp)
        client.get_invoice = AsyncMock(return_value=resp)
    return client


def _mock_cache(ledger: UserLedger | None = None):
    """Create a mock LedgerCache."""
    cache = AsyncMock(spec=LedgerCache)
    cache.get = AsyncMock(return_value=ledger or UserLedger())
    cache.mark_dirty = MagicMock()  # sync method, not async
    return cache


TIER_CONFIG = json.dumps({
    "default": {"credit_multiplier": 1},
    "vip": {"credit_multiplier": 100},
})

USER_TIERS = json.dumps({
    "user-vip": "vip",
    "user-standard": "default",
})


# ---------------------------------------------------------------------------
# _get_multiplier
# ---------------------------------------------------------------------------


class TestGetMultiplier:
    def test_default_when_no_config(self) -> None:
        assert _get_multiplier("user1", None, None) == 1

    def test_default_tier(self) -> None:
        assert _get_multiplier("user-standard", TIER_CONFIG, USER_TIERS) == 1

    def test_vip_tier(self) -> None:
        assert _get_multiplier("user-vip", TIER_CONFIG, USER_TIERS) == 100

    def test_unknown_user_gets_default(self) -> None:
        assert _get_multiplier("user-unknown", TIER_CONFIG, USER_TIERS) == 1

    def test_corrupt_json_returns_default(self) -> None:
        assert _get_multiplier("user1", "not json", "also not json") == 1


class TestGetTierInfo:
    def test_default_when_no_config(self) -> None:
        name, mult = _get_tier_info("user1", None, None)
        assert name == "default"
        assert mult == 1

    def test_vip_tier(self) -> None:
        name, mult = _get_tier_info("user-vip", TIER_CONFIG, USER_TIERS)
        assert name == "vip"
        assert mult == 100

    def test_standard_tier(self) -> None:
        name, mult = _get_tier_info("user-standard", TIER_CONFIG, USER_TIERS)
        assert name == "default"
        assert mult == 1

    def test_unknown_user(self) -> None:
        name, mult = _get_tier_info("user-unknown", TIER_CONFIG, USER_TIERS)
        assert name == "default"
        assert mult == 1

    def test_corrupt_json(self) -> None:
        name, mult = _get_tier_info("user1", "bad", "bad")
        assert name == "default"
        assert mult == 1


# ---------------------------------------------------------------------------
# purchase_credits
# ---------------------------------------------------------------------------


class TestPurchaseCredits:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-42",
            "checkoutLink": "https://pay.example.com/inv-42",
            "expirationTime": "2026-02-16T01:00:00Z",
        })
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(btcpay, cache, "user1", 1000)
        assert result["success"] is True
        assert result["invoice_id"] == "inv-42"
        assert result["amount_sats"] == 1000
        assert "checkout_link" in result
        btcpay.create_invoice.assert_called_once()
        cache.mark_dirty.assert_called_once_with("user1")

    @pytest.mark.asyncio
    async def test_zero_amount_rejected(self) -> None:
        btcpay = _mock_btcpay()
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(btcpay, cache, "user1", 0)
        assert result["success"] is False
        assert "positive" in result["error"]

    @pytest.mark.asyncio
    async def test_negative_amount_rejected(self) -> None:
        btcpay = _mock_btcpay()
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(btcpay, cache, "user1", -100)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_btcpay_error(self) -> None:
        btcpay = _mock_btcpay(error=BTCPayConnectionError("DNS failed"))
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(btcpay, cache, "user1", 1000)
        assert result["success"] is False
        assert "BTCPay error" in result["error"]

    @pytest.mark.asyncio
    async def test_invoice_added_to_pending(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-99", "checkoutLink": "https://x.com"})
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        await purchase_tax_credits_tool(btcpay, cache, "user1", 500)
        assert "inv-99" in ledger.pending_invoices

    @pytest.mark.asyncio
    async def test_default_tier_shown(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "checkoutLink": "https://x.com"})
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(
            btcpay, cache, "user1", 1000,
            tier_config_json=TIER_CONFIG, user_tiers_json=USER_TIERS,
        )
        assert result["tier"] == "default"
        assert result["multiplier"] == 1
        assert result["expected_credits"] == 1000

    @pytest.mark.asyncio
    async def test_vip_tier_shown(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "checkoutLink": "https://x.com"})
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(
            btcpay, cache, "user-vip", 500,
            tier_config_json=TIER_CONFIG, user_tiers_json=USER_TIERS,
        )
        assert result["tier"] == "vip"
        assert result["multiplier"] == 100
        assert result["expected_credits"] == 50000


# ---------------------------------------------------------------------------
# check_payment
# ---------------------------------------------------------------------------


class TestCheckPayment:
    @pytest.mark.asyncio
    async def test_new_status(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "status": "New"})
        cache = _mock_cache()
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["success"] is True
        assert result["status"] == "New"
        assert "awaiting" in result["message"]

    @pytest.mark.asyncio
    async def test_processing_status(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Processing"})
        cache = _mock_cache()
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["status"] == "Processing"
        assert "confirmation" in result["message"]

    @pytest.mark.asyncio
    async def test_settled_credits_granted(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "1000",
        })
        ledger = UserLedger(pending_invoices=["inv-1"])
        cache = _mock_cache(ledger)
        result = await check_payment_tool(
            btcpay, cache, "user1", "inv-1",
            tier_config_json=TIER_CONFIG, user_tiers_json=USER_TIERS,
        )
        assert result["success"] is True
        assert result["credits_granted"] == 1000  # default multiplier = 1
        assert result["balance_api_sats"] == 1000
        assert "inv-1" not in ledger.pending_invoices
        cache.mark_dirty.assert_called()

    @pytest.mark.asyncio
    async def test_settled_vip_multiplier(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "500",
        })
        ledger = UserLedger(pending_invoices=["inv-1"])
        cache = _mock_cache(ledger)
        result = await check_payment_tool(
            btcpay, cache, "user-vip", "inv-1",
            tier_config_json=TIER_CONFIG, user_tiers_json=USER_TIERS,
        )
        assert result["credits_granted"] == 50000  # 500 * 100
        assert result["multiplier"] == 100

    @pytest.mark.asyncio
    async def test_settled_idempotent(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "1000",
        })
        ledger = UserLedger(balance_api_sats=1000, credited_invoices=["inv-1"])
        cache = _mock_cache(ledger)
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["credits_granted"] == 0
        assert result["balance_api_sats"] == 1000
        assert "already credited" in result["message"]

    @pytest.mark.asyncio
    async def test_expired_removes_pending(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Expired"})
        ledger = UserLedger(pending_invoices=["inv-1"])
        cache = _mock_cache(ledger)
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["status"] == "Expired"
        assert "inv-1" not in ledger.pending_invoices
        assert "expired" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_removes_pending(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Invalid"})
        ledger = UserLedger(pending_invoices=["inv-1"])
        cache = _mock_cache(ledger)
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["status"] == "Invalid"
        assert "inv-1" not in ledger.pending_invoices

    @pytest.mark.asyncio
    async def test_btcpay_error(self) -> None:
        btcpay = _mock_btcpay(error=BTCPayServerError("500", status_code=500))
        cache = _mock_cache()
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["success"] is False
        assert "BTCPay error" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_status(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "status": "SomethingNew"})
        cache = _mock_cache()
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert "Unknown" in result["message"]

    @pytest.mark.asyncio
    async def test_additional_status_included(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Processing", "additionalStatus": "PaidPartial",
        })
        cache = _mock_cache()
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["additional_status"] == "PaidPartial"


# ---------------------------------------------------------------------------
# check_balance
# ---------------------------------------------------------------------------


class TestCheckBalance:
    @pytest.mark.asyncio
    async def test_fresh_user(self) -> None:
        cache = _mock_cache()
        result = await check_balance_tool(cache, "user1")
        assert result["success"] is True
        assert result["balance_api_sats"] == 0
        assert result["pending_invoices"] == 0

    @pytest.mark.asyncio
    async def test_with_balance(self) -> None:
        ledger = UserLedger(
            balance_api_sats=5000,
            total_deposited_api_sats=10000,
            total_consumed_api_sats=5000,
            pending_invoices=["inv-a"],
            last_deposit_at="2026-02-15",
        )
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert result["balance_api_sats"] == 5000
        assert result["total_deposited_api_sats"] == 10000
        assert result["total_consumed_api_sats"] == 5000
        assert result["pending_invoices"] == 1
        assert result["last_deposit_at"] == "2026-02-15"

    @pytest.mark.asyncio
    async def test_today_usage_included(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        ledger.debit("search", 10)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "today_usage" in result
        today = date.today().isoformat()
        assert result["today_usage"]["search"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_no_today_usage(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "today_usage" not in result

    @pytest.mark.asyncio
    async def test_does_not_modify_state(self) -> None:
        ledger = UserLedger(balance_api_sats=500)
        cache = _mock_cache(ledger)
        await check_balance_tool(cache, "user1")
        cache.mark_dirty.assert_not_called()
        assert ledger.balance_api_sats == 500

    @pytest.mark.asyncio
    async def test_default_tier_shown(self) -> None:
        cache = _mock_cache()
        result = await check_balance_tool(
            cache, "user1",
            tier_config_json=TIER_CONFIG, user_tiers_json=USER_TIERS,
        )
        assert result["tier"] == "default"
        assert result["multiplier"] == 1

    @pytest.mark.asyncio
    async def test_vip_tier_shown(self) -> None:
        cache = _mock_cache()
        result = await check_balance_tool(
            cache, "user-vip",
            tier_config_json=TIER_CONFIG, user_tiers_json=USER_TIERS,
        )
        assert result["tier"] == "vip"
        assert result["multiplier"] == 100

    @pytest.mark.asyncio
    async def test_seed_balance_granted_shown(self) -> None:
        """check_balance shows seed_balance_granted when seed sentinel is present."""
        ledger = UserLedger(balance_api_sats=1000, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert result["seed_balance_granted"] is True

    @pytest.mark.asyncio
    async def test_seed_balance_granted_absent(self) -> None:
        """check_balance omits seed_balance_granted when no seed was applied."""
        ledger = UserLedger(balance_api_sats=500)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "seed_balance_granted" not in result


# ---------------------------------------------------------------------------
# Seed Balance on Registration
# ---------------------------------------------------------------------------


SAMPLE_NPUB = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"


class TestSeedBalance:
    """Tests for seed balance logic in register_credentials."""

    def setup_method(self) -> None:
        import thebrain_mcp.server as srv
        srv._dpyc_sessions.clear()

    def teardown_method(self) -> None:
        import thebrain_mcp.server as srv
        srv._dpyc_sessions.clear()

    @pytest.mark.asyncio
    async def test_new_user_gets_seed(self) -> None:
        """New user receives seed balance on first registration."""
        import thebrain_mcp.server as srv

        mock_api = AsyncMock()
        mock_api.get_brain = AsyncMock(return_value={"id": "brain-1"})
        mock_api.close = AsyncMock()

        ledger = UserLedger()
        mock_cache = _mock_cache(ledger)

        mock_vault = AsyncMock()
        mock_vault.store = AsyncMock(return_value="thought-123")

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        with patch.object(srv, "_require_user_id", return_value="user-new"), \
             patch.object(srv, "_get_vault", return_value=mock_vault), \
             patch.object(srv, "_get_ledger_cache", return_value=mock_cache), \
             patch.object(srv, "get_settings", return_value=mock_settings), \
             patch("thebrain_mcp.server.TheBrainAPI", return_value=mock_api), \
             patch("thebrain_mcp.server.encrypt_credentials", return_value="encrypted"), \
             patch("thebrain_mcp.server.set_session"):
            result = await srv.register_credentials(
                thebrain_api_key="key-1", brain_id="brain-1",
                passphrase="pass", npub=SAMPLE_NPUB,
            )

        assert result["success"] is True
        assert result["seed_applied"] is True
        assert result["seed_balance_api_sats"] == 1000
        assert ledger.balance_api_sats == 1000
        assert "seed_balance_v1" in ledger.credited_invoices
        # Seed keyed by npub, not Horizon ID
        mock_cache.mark_dirty.assert_called_with(SAMPLE_NPUB)

    @pytest.mark.asyncio
    async def test_re_registration_no_double_seed(self) -> None:
        """Re-registering user does NOT get a second seed."""
        import thebrain_mcp.server as srv

        mock_api = AsyncMock()
        mock_api.get_brain = AsyncMock(return_value={"id": "brain-1"})
        mock_api.close = AsyncMock()

        # User already has the seed sentinel
        ledger = UserLedger(
            balance_api_sats=500,
            credited_invoices=["seed_balance_v1"],
        )
        mock_cache = _mock_cache(ledger)

        mock_vault = AsyncMock()
        mock_vault.store = AsyncMock(return_value="thought-123")

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        with patch.object(srv, "_require_user_id", return_value="user-existing"), \
             patch.object(srv, "_get_vault", return_value=mock_vault), \
             patch.object(srv, "_get_ledger_cache", return_value=mock_cache), \
             patch.object(srv, "get_settings", return_value=mock_settings), \
             patch("thebrain_mcp.server.TheBrainAPI", return_value=mock_api), \
             patch("thebrain_mcp.server.encrypt_credentials", return_value="encrypted"), \
             patch("thebrain_mcp.server.set_session"):
            result = await srv.register_credentials(
                thebrain_api_key="key-1", brain_id="brain-1",
                passphrase="pass", npub=SAMPLE_NPUB,
            )

        assert result["success"] is True
        assert "seed_applied" not in result
        assert ledger.balance_api_sats == 500  # unchanged

    @pytest.mark.asyncio
    async def test_seed_disabled_when_zero(self) -> None:
        """SEED_BALANCE_SATS=0 disables seeding."""
        import thebrain_mcp.server as srv

        mock_api = AsyncMock()
        mock_api.get_brain = AsyncMock(return_value={"id": "brain-1"})
        mock_api.close = AsyncMock()

        ledger = UserLedger()
        mock_cache = _mock_cache(ledger)

        mock_vault = AsyncMock()
        mock_vault.store = AsyncMock(return_value="thought-123")

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 0

        with patch.object(srv, "_require_user_id", return_value="user-new"), \
             patch.object(srv, "_get_vault", return_value=mock_vault), \
             patch.object(srv, "_get_ledger_cache", return_value=mock_cache), \
             patch.object(srv, "get_settings", return_value=mock_settings), \
             patch("thebrain_mcp.server.TheBrainAPI", return_value=mock_api), \
             patch("thebrain_mcp.server.encrypt_credentials", return_value="encrypted"), \
             patch("thebrain_mcp.server.set_session"):
            result = await srv.register_credentials(
                thebrain_api_key="key-1", brain_id="brain-1",
                passphrase="pass", npub=SAMPLE_NPUB,
            )

        assert result["success"] is True
        assert "seed_applied" not in result
        assert ledger.balance_api_sats == 0


# ---------------------------------------------------------------------------
# refresh_config
# ---------------------------------------------------------------------------


class TestRefreshConfig:
    """Tests for the refresh_config tool's reset logic."""

    @pytest.mark.asyncio
    async def test_resets_all_globals(self) -> None:
        """Globals are cleared and settings reloaded after refresh."""
        import thebrain_mcp.server as srv

        # Set up non-None singletons
        mock_btcpay = AsyncMock(spec=BTCPayClient)
        mock_ledger_cache = AsyncMock(spec=LedgerCache)
        mock_ledger_cache.snapshot_all = AsyncMock(return_value=0)
        mock_ledger_cache.flush_all = AsyncMock(return_value=0)
        mock_ledger_cache.stop = AsyncMock()
        mock_operator_api = AsyncMock()
        mock_operator_api.close = AsyncMock()

        srv._btcpay_client = mock_btcpay
        srv._ledger_cache = mock_ledger_cache
        srv._operator_api_client = mock_operator_api
        srv._settings_loaded = True
        srv.active_brain_id = "old-brain-id"

        with patch.object(srv, "_ensure_settings_loaded"), \
             patch.object(srv, "get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.btcpay_host = "https://btcpay.example.com"
            mock_settings.btcpay_store_id = "store-123"
            mock_settings.btcpay_api_key = "key-abc"
            mock_settings.btcpay_tier_config = '{"default":{"credit_multiplier":1}}'
            mock_settings.thebrain_vault_brain_id = "vault-brain-id"
            mock_get_settings.return_value = mock_settings

            result = await srv._refresh_config_impl()

        assert result["success"] is True
        assert len(result["refreshed"]) == 5
        assert result["config_summary"]["btcpay_configured"] is True
        assert result["config_summary"]["tier_config_present"] is True
        assert result["config_summary"]["vault_brain_id"] == "vault-brain-id"

        # Verify cleanup was called
        mock_ledger_cache.snapshot_all.assert_called_once()
        mock_ledger_cache.flush_all.assert_called_once()
        mock_ledger_cache.stop.assert_called_once()
        mock_btcpay.close.assert_called_once()
        mock_operator_api.close.assert_called_once()

        # Verify globals were reset
        assert srv._btcpay_client is None
        assert srv._ledger_cache is None
        assert srv._operator_api_client is None

    @pytest.mark.asyncio
    async def test_handles_none_singletons(self) -> None:
        """refresh_config works even when singletons are already None."""
        import thebrain_mcp.server as srv

        srv._btcpay_client = None
        srv._ledger_cache = None
        srv._operator_api_client = None
        srv._settings_loaded = False
        srv.active_brain_id = None

        with patch.object(srv, "_ensure_settings_loaded"), \
             patch.object(srv, "get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.btcpay_host = ""
            mock_settings.btcpay_store_id = ""
            mock_settings.btcpay_api_key = ""
            mock_settings.btcpay_tier_config = None
            mock_settings.thebrain_vault_brain_id = None
            mock_get_settings.return_value = mock_settings

            result = await srv._refresh_config_impl()

        assert result["success"] is True
        # Only settings_loaded reset when singletons were None
        assert result["refreshed"] == ["settings_loaded reset"]
        assert result["config_summary"]["btcpay_configured"] is False
        assert result["config_summary"]["tier_config_present"] is False

    @pytest.mark.asyncio
    async def test_flushes_dirty_entries_before_teardown(self) -> None:
        """Dirty ledger entries are flushed before cache is discarded."""
        import thebrain_mcp.server as srv

        mock_ledger_cache = AsyncMock(spec=LedgerCache)
        mock_ledger_cache.snapshot_all = AsyncMock(return_value=2)
        mock_ledger_cache.flush_all = AsyncMock(return_value=3)
        mock_ledger_cache.stop = AsyncMock()
        srv._ledger_cache = mock_ledger_cache
        srv._btcpay_client = None
        srv._operator_api_client = None

        with patch.object(srv, "_ensure_settings_loaded"), \
             patch.object(srv, "get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.btcpay_host = ""
            mock_settings.btcpay_store_id = ""
            mock_settings.btcpay_api_key = ""
            mock_settings.btcpay_tier_config = None
            mock_settings.thebrain_vault_brain_id = None
            mock_get_settings.return_value = mock_settings

            result = await srv._refresh_config_impl()

        assert "ledger snapshots created (2)" in result["refreshed"]
        assert "ledger_cache flushed (3 dirty entries)" in result["refreshed"]
        mock_ledger_cache.snapshot_all.assert_called_once()
        mock_ledger_cache.flush_all.assert_called_once()
        mock_ledger_cache.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_snapshot_called_before_flush(self) -> None:
        """Snapshot must happen before flush to capture pre-overwrite state."""
        import thebrain_mcp.server as srv

        call_order: list[str] = []

        mock_ledger_cache = AsyncMock(spec=LedgerCache)

        async def mock_snapshot_all(ts):
            call_order.append("snapshot_all")
            return 1

        async def mock_flush_all():
            call_order.append("flush_all")
            return 1

        mock_ledger_cache.snapshot_all = AsyncMock(side_effect=mock_snapshot_all)
        mock_ledger_cache.flush_all = AsyncMock(side_effect=mock_flush_all)
        mock_ledger_cache.stop = AsyncMock()
        srv._ledger_cache = mock_ledger_cache
        srv._btcpay_client = None
        srv._operator_api_client = None

        with patch.object(srv, "_ensure_settings_loaded"), \
             patch.object(srv, "get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.btcpay_host = ""
            mock_settings.btcpay_store_id = ""
            mock_settings.btcpay_api_key = ""
            mock_settings.btcpay_tier_config = None
            mock_settings.thebrain_vault_brain_id = None
            mock_get_settings.return_value = mock_settings

            await srv._refresh_config_impl()

        assert call_order == ["snapshot_all", "flush_all"]


# ---------------------------------------------------------------------------
# compute_low_balance_warning
# ---------------------------------------------------------------------------


class TestComputeLowBalanceWarning:
    def test_above_threshold_returns_none(self) -> None:
        """Balance well above threshold → no warning."""
        ledger = UserLedger(balance_api_sats=5000)
        assert compute_low_balance_warning(ledger, seed_balance_sats=1000) is None

    def test_at_threshold_returns_none(self) -> None:
        """Balance exactly at threshold → no warning (>= means safe)."""
        # seed_balance_sats=500, threshold = max(500//5, 100) = 100
        ledger = UserLedger(
            balance_api_sats=100,
            credited_invoices=["seed_balance_v1"],
        )
        assert compute_low_balance_warning(ledger, seed_balance_sats=500) is None

    def test_below_threshold_returns_warning(self) -> None:
        """Balance below threshold → warning dict."""
        ledger = UserLedger(
            balance_api_sats=50,
            credited_invoices=["seed_balance_v1"],
        )
        warning = compute_low_balance_warning(ledger, seed_balance_sats=500)
        assert warning is not None
        assert warning["balance_api_sats"] == 50
        assert warning["threshold_api_sats"] == 100
        assert "purchase_credits" in warning["purchase_command"]
        assert "message" in warning

    def test_settled_invoice_reference(self) -> None:
        """Threshold is 20% of last settled invoice's api_sats_credited."""
        ledger = UserLedger(balance_api_sats=50)
        ledger.record_invoice_created("inv-1", amount_sats=1000, multiplier=1, created_at="")
        ledger.record_invoice_settled("inv-1", api_sats_credited=1000, settled_at="")
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        # threshold = max(1000 // 5, 100) = 200
        assert warning["threshold_api_sats"] == 200

    def test_seed_only_user(self) -> None:
        """Seed-only user: reference is seed_balance_sats."""
        ledger = UserLedger(
            balance_api_sats=10,
            credited_invoices=["seed_balance_v1"],
        )
        warning = compute_low_balance_warning(ledger, seed_balance_sats=1000)
        assert warning is not None
        # threshold = max(1000 // 5, 100) = 200
        assert warning["threshold_api_sats"] == 200

    def test_no_history_uses_floor(self) -> None:
        """No invoices, no seed: reference is the floor."""
        ledger = UserLedger(balance_api_sats=50)
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        # reference = floor (100), threshold = max(100//5, 100) = 100
        assert warning["threshold_api_sats"] == 100

    def test_retroactive_invoice_suggested_defaults(self) -> None:
        """Retroactive invoice (amount_sats=0) → suggested defaults to 1000."""
        ledger = UserLedger(balance_api_sats=5)
        ledger.record_invoice_settled("inv-retro", api_sats_credited=500, settled_at="")
        # retroactive: amount_sats=0 in the record
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        assert warning["suggested_top_up_sats"] == 1000

    def test_suggested_capped_at_max(self) -> None:
        """Suggested top-up capped at MAX_INVOICE_SATS."""
        ledger = UserLedger(balance_api_sats=5)
        ledger.record_invoice_created(
            "inv-big", amount_sats=5_000_000, multiplier=1, created_at="",
        )
        ledger.record_invoice_settled("inv-big", api_sats_credited=5_000_000, settled_at="")
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        assert warning["suggested_top_up_sats"] == MAX_INVOICE_SATS

    def test_zero_seed_no_invoices(self) -> None:
        """Zero seed + no invoices → floor path."""
        ledger = UserLedger(balance_api_sats=50)
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        assert warning["threshold_api_sats"] == 100
        assert warning["suggested_top_up_sats"] == 1000


# ---------------------------------------------------------------------------
# purchase cap
# ---------------------------------------------------------------------------


class TestPurchaseCap:
    @pytest.mark.asyncio
    async def test_max_accepted(self) -> None:
        """Exactly MAX_INVOICE_SATS is accepted."""
        btcpay = _mock_btcpay({
            "id": "inv-max", "checkoutLink": "https://pay.example.com/inv-max",
        })
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(
            btcpay, cache, "user1", MAX_INVOICE_SATS,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_over_max_rejected(self) -> None:
        """MAX_INVOICE_SATS + 1 is rejected."""
        btcpay = _mock_btcpay()
        cache = _mock_cache()
        result = await purchase_tax_credits_tool(
            btcpay, cache, "user1", MAX_INVOICE_SATS + 1,
        )
        assert result["success"] is False
        assert "maximum" in result["error"]
        assert "1,000,000" in result["error"]


# ---------------------------------------------------------------------------
# _attempt_royalty_payout
# ---------------------------------------------------------------------------


class TestAttemptRoyaltyPayout:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.create_payout = AsyncMock(
            return_value={"id": "payout-1", "state": "AwaitingApproval"}
        )
        result = await _attempt_royalty_payout(btcpay, 1000, "addr@ln", 0.02, 10)
        assert result is not None
        assert result["royalty_sats"] == 20
        assert result["royalty_address"] == "addr@ln"
        assert result["payout_id"] == "payout-1"
        assert result["payout_state"] == "AwaitingApproval"
        btcpay.create_payout.assert_called_once_with("addr@ln", 20)

    @pytest.mark.asyncio
    async def test_below_minimum_returns_none(self) -> None:
        btcpay = AsyncMock(spec=BTCPayClient)
        result = await _attempt_royalty_payout(btcpay, 100, "addr@ln", 0.02, 10)
        # 100 * 0.02 = 2, below min of 10
        assert result is None
        btcpay.create_payout.assert_not_called()

    @pytest.mark.asyncio
    async def test_at_minimum(self) -> None:
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.create_payout = AsyncMock(return_value={"id": "p-2", "state": "OK"})
        result = await _attempt_royalty_payout(btcpay, 500, "addr@ln", 0.02, 10)
        # 500 * 0.02 = 10, exactly at min
        assert result is not None
        assert result["royalty_sats"] == 10

    @pytest.mark.asyncio
    async def test_btcpay_error_returns_dict_never_raises(self) -> None:
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.create_payout = AsyncMock(
            side_effect=BTCPayServerError("500 oops", status_code=500)
        )
        result = await _attempt_royalty_payout(btcpay, 1000, "addr@ln", 0.02, 10)
        assert result is not None
        assert result["royalty_sats"] == 20
        assert "royalty_error" in result
        assert "500 oops" in result["royalty_error"]

    @pytest.mark.asyncio
    async def test_percentage_math(self) -> None:
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.create_payout = AsyncMock(return_value={"id": "p", "state": "OK"})
        result = await _attempt_royalty_payout(btcpay, 5000, "a@b", 0.05, 10)
        assert result is not None
        assert result["royalty_sats"] == 250  # 5000 * 0.05

    @pytest.mark.asyncio
    async def test_int_truncation_rounding(self) -> None:
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.create_payout = AsyncMock(return_value={"id": "p", "state": "OK"})
        # 999 * 0.02 = 19.98, int() truncates to 19
        result = await _attempt_royalty_payout(btcpay, 999, "a@b", 0.02, 10)
        assert result is not None
        assert result["royalty_sats"] == 19


# ---------------------------------------------------------------------------
# Royalty payout ceiling
# ---------------------------------------------------------------------------


class TestRoyaltyPayoutCeiling:
    @pytest.mark.asyncio
    async def test_above_ceiling_refused(self) -> None:
        """Royalty exceeding ROYALTY_PAYOUT_MAX_SATS is refused without calling BTCPay."""
        btcpay = AsyncMock(spec=BTCPayClient)
        # 10M * 0.02 = 200,000 sats — above 100K ceiling
        result = await _attempt_royalty_payout(btcpay, 10_000_000, "addr@ln", 0.02, 10)
        assert result is not None
        assert "royalty_error" in result
        assert "safety ceiling" in result["royalty_error"]
        assert result["royalty_sats"] == 200_000
        btcpay.create_payout.assert_not_called()

    @pytest.mark.asyncio
    async def test_at_ceiling_allowed(self) -> None:
        """Royalty exactly at ROYALTY_PAYOUT_MAX_SATS is allowed."""
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.create_payout = AsyncMock(return_value={"id": "p-1", "state": "OK"})
        # 5M * 0.02 = 100,000 sats — exactly at ceiling
        result = await _attempt_royalty_payout(btcpay, 5_000_000, "addr@ln", 0.02, 10)
        assert result is not None
        assert "royalty_error" not in result
        assert result["royalty_sats"] == ROYALTY_PAYOUT_MAX_SATS
        btcpay.create_payout.assert_called_once()

    @pytest.mark.asyncio
    async def test_just_below_ceiling_allowed(self) -> None:
        """Royalty just below ceiling is allowed."""
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.create_payout = AsyncMock(return_value={"id": "p-2", "state": "OK"})
        # 4,999,999 * 0.02 = 99,999.98 → int() = 99,999
        result = await _attempt_royalty_payout(btcpay, 4_999_999, "addr@ln", 0.02, 10)
        assert result is not None
        assert "royalty_error" not in result
        assert result["royalty_sats"] == 99_999

    @pytest.mark.asyncio
    async def test_ceiling_catches_bad_percentage(self) -> None:
        """A mis-configured 100% royalty rate is caught by the ceiling."""
        btcpay = AsyncMock(spec=BTCPayClient)
        # 500,000 * 1.0 = 500,000 sats — way above ceiling
        result = await _attempt_royalty_payout(btcpay, 500_000, "addr@ln", 1.0, 10)
        assert result is not None
        assert "royalty_error" in result
        assert "safety ceiling" in result["royalty_error"]
        btcpay.create_payout.assert_not_called()


# ---------------------------------------------------------------------------
# check_payment with royalty
# ---------------------------------------------------------------------------


class TestCheckPaymentWithRoyalty:
    @pytest.mark.asyncio
    async def test_settled_triggers_payout(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "1000",
        })
        btcpay.create_payout = AsyncMock(
            return_value={"id": "payout-1", "state": "AwaitingApproval"}
        )
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        result = await check_payment_tool(
            btcpay, cache, "user1", "inv-1",
            royalty_address="addr@ln", royalty_percent=0.02, royalty_min_sats=10,
        )
        assert result["credits_granted"] == 1000
        assert "royalty_payout" in result
        assert result["royalty_payout"]["royalty_sats"] == 20
        assert result["royalty_payout"]["payout_id"] == "payout-1"

    @pytest.mark.asyncio
    async def test_no_payout_when_address_none(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "1000",
        })
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        result = await check_payment_tool(
            btcpay, cache, "user1", "inv-1",
            royalty_address=None,
        )
        assert result["credits_granted"] == 1000
        assert "royalty_payout" not in result

    @pytest.mark.asyncio
    async def test_payout_failure_doesnt_block_credits(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "1000",
        })
        btcpay.create_payout = AsyncMock(
            side_effect=BTCPayServerError("fail", status_code=500)
        )
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        result = await check_payment_tool(
            btcpay, cache, "user1", "inv-1",
            royalty_address="addr@ln", royalty_percent=0.02, royalty_min_sats=10,
        )
        assert result["success"] is True
        assert result["credits_granted"] == 1000
        assert result["royalty_payout"]["royalty_error"] is not None

    @pytest.mark.asyncio
    async def test_idempotent_path_skips_payout(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "1000",
        })
        btcpay.create_payout = AsyncMock()
        ledger = UserLedger(balance_api_sats=1000, credited_invoices=["inv-1"])
        cache = _mock_cache(ledger)
        result = await check_payment_tool(
            btcpay, cache, "user1", "inv-1",
            royalty_address="addr@ln", royalty_percent=0.02, royalty_min_sats=10,
        )
        assert result["credits_granted"] == 0
        assert "royalty_payout" not in result
        btcpay.create_payout.assert_not_called()

    @pytest.mark.asyncio
    async def test_below_minimum_skips_payout(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "100",
        })
        btcpay.create_payout = AsyncMock()
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        result = await check_payment_tool(
            btcpay, cache, "user1", "inv-1",
            royalty_address="addr@ln", royalty_percent=0.02, royalty_min_sats=10,
        )
        # 100 * 0.02 = 2, below min 10 → no royalty_payout key
        assert result["credits_granted"] == 100
        assert "royalty_payout" not in result
        btcpay.create_payout.assert_not_called()


# ---------------------------------------------------------------------------
# btcpay_status with royalty
# ---------------------------------------------------------------------------


class TestBTCPayStatusRoyalty:
    @pytest.mark.asyncio
    async def test_royalty_config_shown(self) -> None:
        settings = MagicMock()
        settings.btcpay_host = "https://btcpay.example.com"
        settings.btcpay_store_id = "store-123"
        settings.btcpay_api_key = "key-abc"
        settings.btcpay_tier_config = TIER_CONFIG
        settings.btcpay_user_tiers = USER_TIERS
        settings.tollbooth_royalty_address = "toll@ln"
        settings.tollbooth_royalty_percent = 0.02
        settings.tollbooth_royalty_min_sats = 10

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(return_value={"name": "Store"})
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": [
                "btcpay.store.cancreateinvoice",
                "btcpay.store.canviewinvoices",
                "btcpay.store.cancreatenonapprovedpullpayments",
            ]
        })

        result = await btcpay_status_tool(settings, btcpay)
        assert result["royalty_config"]["enabled"] is True
        assert result["royalty_config"]["address"] == "toll@ln"
        assert result["royalty_config"]["percent"] == 0.02
        assert result["royalty_config"]["min_sats"] == 10

    @pytest.mark.asyncio
    async def test_royalty_disabled_shown(self) -> None:
        settings = MagicMock()
        settings.btcpay_host = None
        settings.btcpay_store_id = None
        settings.btcpay_api_key = None
        settings.btcpay_tier_config = None
        settings.btcpay_user_tiers = None
        settings.tollbooth_royalty_address = None
        settings.tollbooth_royalty_percent = 0.02
        settings.tollbooth_royalty_min_sats = 10

        result = await btcpay_status_tool(settings, None)
        assert result["royalty_config"]["enabled"] is False
        assert result["royalty_config"]["address"] is None

    @pytest.mark.asyncio
    async def test_permissions_success(self) -> None:
        settings = MagicMock()
        settings.btcpay_host = "https://btcpay.example.com"
        settings.btcpay_store_id = "store-123"
        settings.btcpay_api_key = "key-abc"
        settings.btcpay_tier_config = TIER_CONFIG
        settings.btcpay_user_tiers = USER_TIERS
        settings.tollbooth_royalty_address = "toll@ln"
        settings.tollbooth_royalty_percent = 0.02
        settings.tollbooth_royalty_min_sats = 10

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(return_value={"name": "Store"})
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": [
                "btcpay.store.cancreateinvoice",
                "btcpay.store.canviewinvoices",
                "btcpay.store.cancreatenonapprovedpullpayments",
            ]
        })

        result = await btcpay_status_tool(settings, btcpay)
        perms = result["api_key_permissions"]
        assert perms["missing"] == []
        assert len(perms["present"]) == 3

    @pytest.mark.asyncio
    async def test_missing_payout_perm(self) -> None:
        settings = MagicMock()
        settings.btcpay_host = "https://btcpay.example.com"
        settings.btcpay_store_id = "store-123"
        settings.btcpay_api_key = "key-abc"
        settings.btcpay_tier_config = TIER_CONFIG
        settings.btcpay_user_tiers = USER_TIERS
        settings.tollbooth_royalty_address = "toll@ln"
        settings.tollbooth_royalty_percent = 0.02
        settings.tollbooth_royalty_min_sats = 10

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(return_value={"name": "Store"})
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": [
                "btcpay.store.cancreateinvoice",
                "btcpay.store.canviewinvoices",
            ]
        })

        result = await btcpay_status_tool(settings, btcpay)
        perms = result["api_key_permissions"]
        assert "btcpay.store.cancreatenonapprovedpullpayments" in perms["missing"]

    @pytest.mark.asyncio
    async def test_api_key_info_error(self) -> None:
        settings = MagicMock()
        settings.btcpay_host = "https://btcpay.example.com"
        settings.btcpay_store_id = "store-123"
        settings.btcpay_api_key = "key-abc"
        settings.btcpay_tier_config = TIER_CONFIG
        settings.btcpay_user_tiers = USER_TIERS
        settings.tollbooth_royalty_address = None
        settings.tollbooth_royalty_percent = 0.02
        settings.tollbooth_royalty_min_sats = 10

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(return_value={"name": "Store"})
        btcpay.get_api_key_info = AsyncMock(
            side_effect=BTCPayAuthError("unauthorized", status_code=401)
        )

        result = await btcpay_status_tool(settings, btcpay)
        assert "error" in result["api_key_permissions"]


# ---------------------------------------------------------------------------
# btcpay_status
# ---------------------------------------------------------------------------


def _mock_settings(**overrides):
    """Create a mock Settings object with sensible defaults."""
    defaults = {
        "btcpay_host": "https://btcpay.example.com",
        "btcpay_store_id": "store-123",
        "btcpay_api_key": "key-abc",
        "btcpay_tier_config": TIER_CONFIG,
        "btcpay_user_tiers": USER_TIERS,
        "tollbooth_royalty_address": None,
        "tollbooth_royalty_percent": 0.02,
        "tollbooth_royalty_min_sats": 10,
    }
    defaults.update(overrides)
    settings = MagicMock()
    for k, v in defaults.items():
        setattr(settings, k, v)
    return settings


class TestBTCPayStatus:
    @pytest.mark.asyncio
    async def test_all_configured_and_reachable(self) -> None:
        """Full config, server reachable, store accessible."""
        settings = _mock_settings()
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(return_value={"name": "My Store"})
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": ["btcpay.store.cancreateinvoice", "btcpay.store.canviewinvoices"]
        })

        result = await btcpay_status_tool(settings, btcpay)

        assert result["btcpay_host"] == "https://btcpay.example.com"
        assert result["btcpay_store_id"] == "store-123"
        assert result["btcpay_api_key_status"] == "present"
        assert result["tier_config"] == "2 tier(s)"
        assert result["user_tiers"] == "2 user(s)"
        assert result["server_reachable"] is True
        assert result["store_name"] == "My Store"

    @pytest.mark.asyncio
    async def test_api_key_missing(self) -> None:
        """Missing API key — network checks skipped."""
        settings = _mock_settings(btcpay_api_key=None)

        result = await btcpay_status_tool(settings, None)

        assert result["btcpay_api_key_status"] == "missing"
        assert result["server_reachable"] is None
        assert result["store_name"] is None

    @pytest.mark.asyncio
    async def test_host_missing(self) -> None:
        """Missing host — network checks skipped."""
        settings = _mock_settings(btcpay_host=None)

        result = await btcpay_status_tool(settings, None)

        assert result["btcpay_host"] is None
        assert result["server_reachable"] is None
        assert result["store_name"] is None

    @pytest.mark.asyncio
    async def test_invalid_tier_config_json(self) -> None:
        """Invalid tier config JSON reported."""
        settings = _mock_settings(btcpay_tier_config="not valid json{")

        result = await btcpay_status_tool(settings, None)

        assert result["tier_config"] == "invalid JSON"

    @pytest.mark.asyncio
    async def test_server_unreachable(self) -> None:
        """Server unreachable — health check fails."""
        settings = _mock_settings()
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(
            side_effect=BTCPayConnectionError("DNS failed")
        )
        btcpay.get_store = AsyncMock(return_value={"name": "My Store"})
        btcpay.get_api_key_info = AsyncMock(return_value={"permissions": []})

        result = await btcpay_status_tool(settings, btcpay)

        assert result["server_reachable"] is False
        assert result["store_name"] == "My Store"

    @pytest.mark.asyncio
    async def test_store_auth_failure(self) -> None:
        """Store returns 401 — reported as unauthorized."""
        settings = _mock_settings()
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(
            side_effect=BTCPayAuthError("Unauthorized", status_code=401)
        )
        btcpay.get_api_key_info = AsyncMock(return_value={"permissions": []})

        result = await btcpay_status_tool(settings, btcpay)

        assert result["server_reachable"] is True
        assert result["store_name"] == "unauthorized"


# ---------------------------------------------------------------------------
# Preflight permission check
# ---------------------------------------------------------------------------


class TestBTCPayPreflight:
    def setup_method(self) -> None:
        import thebrain_mcp.server as srv
        srv._dpyc_sessions.clear()

    def teardown_method(self) -> None:
        import thebrain_mcp.server as srv
        srv._dpyc_sessions.clear()

    @pytest.mark.asyncio
    async def test_fails_when_royalty_configured_but_perm_missing(self) -> None:
        """Preflight raises TollboothConfigError when royalty configured but payout perm missing."""
        import thebrain_mcp.server as srv
        from thebrain_mcp.server import TollboothConfigError

        srv._btcpay_preflight_done = False

        mock_settings = MagicMock()
        mock_settings.tollbooth_royalty_address = "toll@ln"
        mock_settings.btcpay_store_id = "store-123"

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": [
                "btcpay.store.cancreateinvoice",
                "btcpay.store.canviewinvoices",
                # Missing: cancreatenonapprovedpullpayments
            ]
        })

        with patch.object(srv, "get_settings", return_value=mock_settings):
            with pytest.raises(TollboothConfigError, match="missing required permissions"):
                await srv._ensure_btcpay_preflight(btcpay)

        # Verify preflight was NOT marked done (so it retries)
        assert srv._btcpay_preflight_done is False

    @pytest.mark.asyncio
    async def test_succeeds_when_all_perms_present(self) -> None:
        """Preflight passes when all required permissions are granted."""
        import thebrain_mcp.server as srv

        srv._btcpay_preflight_done = False

        mock_settings = MagicMock()
        mock_settings.tollbooth_royalty_address = "toll@ln"
        mock_settings.btcpay_store_id = "store-123"

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": [
                "btcpay.store.cancreateinvoice",
                "btcpay.store.canviewinvoices",
                "btcpay.store.cancreatenonapprovedpullpayments",
            ]
        })

        with patch.object(srv, "get_settings", return_value=mock_settings):
            await srv._ensure_btcpay_preflight(btcpay)

        assert srv._btcpay_preflight_done is True

    @pytest.mark.asyncio
    async def test_succeeds_when_no_royalty_configured(self) -> None:
        """Preflight passes without payout perm when royalty is not configured."""
        import thebrain_mcp.server as srv

        srv._btcpay_preflight_done = False

        mock_settings = MagicMock()
        mock_settings.tollbooth_royalty_address = None  # No royalty
        mock_settings.btcpay_store_id = "store-123"

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": [
                "btcpay.store.cancreateinvoice",
                "btcpay.store.canviewinvoices",
                # No payout perm — but that's fine, no royalty configured
            ]
        })

        with patch.object(srv, "get_settings", return_value=mock_settings):
            await srv._ensure_btcpay_preflight(btcpay)

        assert srv._btcpay_preflight_done is True

    @pytest.mark.asyncio
    async def test_store_scoped_permissions_accepted(self) -> None:
        """Preflight accepts store-scoped permissions (e.g. 'canX:storeId')."""
        import thebrain_mcp.server as srv

        srv._btcpay_preflight_done = False

        mock_settings = MagicMock()
        mock_settings.tollbooth_royalty_address = "toll@ln"
        mock_settings.btcpay_store_id = "store-123"

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": [
                "btcpay.store.cancreateinvoice:store-123",
                "btcpay.store.canviewinvoices:store-123",
                "btcpay.store.cancreatenonapprovedpullpayments:store-123",
            ]
        })

        with patch.object(srv, "get_settings", return_value=mock_settings):
            await srv._ensure_btcpay_preflight(btcpay)

        assert srv._btcpay_preflight_done is True

    @pytest.mark.asyncio
    async def test_api_error_raises_config_error(self) -> None:
        """Preflight raises TollboothConfigError when API call fails."""
        import thebrain_mcp.server as srv
        from thebrain_mcp.server import TollboothConfigError

        srv._btcpay_preflight_done = False

        mock_settings = MagicMock()
        mock_settings.tollbooth_royalty_address = "toll@ln"
        mock_settings.btcpay_store_id = "store-123"

        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.get_api_key_info = AsyncMock(
            side_effect=BTCPayConnectionError("DNS failed")
        )

        with patch.object(srv, "get_settings", return_value=mock_settings):
            with pytest.raises(TollboothConfigError, match="Cannot verify"):
                await srv._ensure_btcpay_preflight(btcpay)

    @pytest.mark.asyncio
    async def test_skips_when_already_done(self) -> None:
        """Preflight is a no-op after first successful run."""
        import thebrain_mcp.server as srv

        srv._btcpay_preflight_done = True

        btcpay = AsyncMock(spec=BTCPayClient)
        await srv._ensure_btcpay_preflight(btcpay)

        # Should not have called the API at all
        btcpay.get_api_key_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_purchase_credits_blocked_by_preflight(self) -> None:
        """purchase_credits returns error when preflight fails."""
        import thebrain_mcp.server as srv
        from thebrain_mcp.server import TollboothConfigError

        srv._btcpay_preflight_done = False
        srv._dpyc_sessions["user-1"] = SAMPLE_NPUB

        mock_btcpay = AsyncMock(spec=BTCPayClient)
        mock_btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": ["btcpay.store.cancreateinvoice"]
        })

        mock_settings = MagicMock()
        mock_settings.tollbooth_royalty_address = "toll@ln"
        mock_settings.btcpay_store_id = "store-123"
        mock_settings.btcpay_host = "https://btcpay.example.com"
        mock_settings.btcpay_api_key = "key"
        mock_settings.authority_public_key = "-----BEGIN PUBLIC KEY-----\nMCowBQ...\n-----END PUBLIC KEY-----"

        with patch.object(srv, "_require_user_id", return_value="user-1"), \
             patch.object(srv, "_get_btcpay", return_value=mock_btcpay), \
             patch.object(srv, "get_settings", return_value=mock_settings), \
             patch.object(srv, "_get_ledger_cache"):
            result = await srv.purchase_credits(amount_sats=1000, certificate="jwt.token")

        assert result["success"] is False
        assert "missing required permissions" in result["error"]

    @pytest.mark.asyncio
    async def test_purchase_credits_requires_certificate_when_authority_configured(self) -> None:
        """purchase_credits rejects calls without certificate when authority_public_key is set."""
        import thebrain_mcp.server as srv

        srv._dpyc_sessions["user-1"] = SAMPLE_NPUB

        mock_settings = MagicMock()
        mock_settings.authority_public_key = "-----BEGIN PUBLIC KEY-----\nMCowBQ...\n-----END PUBLIC KEY-----"
        mock_settings.btcpay_tier_config = None
        mock_settings.btcpay_user_tiers = None

        mock_btcpay = AsyncMock(spec=BTCPayClient)
        mock_btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": ["btcpay.store.cancreateinvoice", "btcpay.store.canviewinvoices"]
        })
        srv._btcpay_preflight_done = True

        with patch.object(srv, "_require_user_id", return_value="user-1"), \
             patch.object(srv, "_get_btcpay", return_value=mock_btcpay), \
             patch.object(srv, "get_settings", return_value=mock_settings), \
             patch.object(srv, "_get_ledger_cache"):
            result = await srv.purchase_credits(amount_sats=1000, certificate="")

        assert result["success"] is False
        assert "certificate" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_purchase_credits_certified_path(self) -> None:
        """purchase_credits calls purchase_credits_tool when certificate is provided."""
        import thebrain_mcp.server as srv

        srv._dpyc_sessions["user-1"] = SAMPLE_NPUB

        mock_settings = MagicMock()
        mock_settings.authority_public_key = "-----BEGIN PUBLIC KEY-----\nMCowBQ...\n-----END PUBLIC KEY-----"
        mock_settings.btcpay_tier_config = None
        mock_settings.btcpay_user_tiers = None

        mock_btcpay = AsyncMock(spec=BTCPayClient)
        mock_btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": ["btcpay.store.cancreateinvoice", "btcpay.store.canviewinvoices"]
        })
        srv._btcpay_preflight_done = True

        fake_cert_result = {"success": True, "invoice_id": "cert-inv-1", "certificate_jti": "jti-abc"}

        with patch.object(srv, "_require_user_id", return_value="user-1"), \
             patch.object(srv, "_get_btcpay", return_value=mock_btcpay), \
             patch.object(srv, "get_settings", return_value=mock_settings), \
             patch.object(srv, "_get_ledger_cache") as mock_cache, \
             patch.object(srv.credits, "purchase_credits_tool", new_callable=AsyncMock,
                          return_value=fake_cert_result) as mock_certified:
            result = await srv.purchase_credits(amount_sats=1000, certificate="jwt.token.here")

        assert result["success"] is True
        assert result["certificate_jti"] == "jti-abc"
        mock_certified.assert_called_once()
        call_kwargs = mock_certified.call_args
        assert call_kwargs.kwargs["certificate"] == "jwt.token.here"
        assert call_kwargs.kwargs["authority_public_key"] == mock_settings.authority_public_key

    @pytest.mark.asyncio
    async def test_purchase_credits_rejected_without_authority_key(self) -> None:
        """purchase_credits rejects all purchases when AUTHORITY_PUBLIC_KEY is not configured."""
        import thebrain_mcp.server as srv

        srv._dpyc_sessions["user-1"] = SAMPLE_NPUB

        mock_settings = MagicMock()
        mock_settings.authority_public_key = None
        mock_settings.btcpay_tier_config = None
        mock_settings.btcpay_user_tiers = None

        mock_btcpay = AsyncMock(spec=BTCPayClient)
        mock_btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": ["btcpay.store.cancreateinvoice", "btcpay.store.canviewinvoices"]
        })
        srv._btcpay_preflight_done = True

        with patch.object(srv, "_require_user_id", return_value="user-1"), \
             patch.object(srv, "_get_btcpay", return_value=mock_btcpay), \
             patch.object(srv, "get_settings", return_value=mock_settings), \
             patch.object(srv, "_get_ledger_cache"):
            result = await srv.purchase_credits(amount_sats=1000, certificate="jwt.here")

        assert result["success"] is False
        assert "AUTHORITY_PUBLIC_KEY" in result["error"]
