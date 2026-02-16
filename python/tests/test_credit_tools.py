"""Tests for credit management tools: purchase_credits, check_payment, check_balance."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.btcpay_client import BTCPayClient, BTCPayConnectionError, BTCPayServerError
from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache
from thebrain_mcp.tools.credits import (
    _get_multiplier,
    _get_tier_info,
    check_balance_tool,
    check_payment_tool,
    purchase_credits_tool,
)


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
        result = await purchase_credits_tool(btcpay, cache, "user1", 1000)
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
        result = await purchase_credits_tool(btcpay, cache, "user1", 0)
        assert result["success"] is False
        assert "positive" in result["error"]

    @pytest.mark.asyncio
    async def test_negative_amount_rejected(self) -> None:
        btcpay = _mock_btcpay()
        cache = _mock_cache()
        result = await purchase_credits_tool(btcpay, cache, "user1", -100)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_btcpay_error(self) -> None:
        btcpay = _mock_btcpay(error=BTCPayConnectionError("DNS failed"))
        cache = _mock_cache()
        result = await purchase_credits_tool(btcpay, cache, "user1", 1000)
        assert result["success"] is False
        assert "BTCPay error" in result["error"]

    @pytest.mark.asyncio
    async def test_invoice_added_to_pending(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-99", "checkoutLink": "https://x.com"})
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        await purchase_credits_tool(btcpay, cache, "user1", 500)
        assert "inv-99" in ledger.pending_invoices

    @pytest.mark.asyncio
    async def test_default_tier_shown(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-1", "checkoutLink": "https://x.com"})
        cache = _mock_cache()
        result = await purchase_credits_tool(
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
        result = await purchase_credits_tool(
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
        assert result["balance_sats"] == 1000
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
        ledger = UserLedger(balance_sats=1000)  # already credited, not in pending
        cache = _mock_cache(ledger)
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["credits_granted"] == 0
        assert result["balance_sats"] == 1000
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
        assert result["balance_sats"] == 0
        assert result["pending_invoices"] == 0

    @pytest.mark.asyncio
    async def test_with_balance(self) -> None:
        ledger = UserLedger(
            balance_sats=5000,
            total_deposited_sats=10000,
            total_consumed_sats=5000,
            pending_invoices=["inv-a"],
            last_deposit_at="2026-02-15",
        )
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert result["balance_sats"] == 5000
        assert result["total_deposited_sats"] == 10000
        assert result["total_consumed_sats"] == 5000
        assert result["pending_invoices"] == 1
        assert result["last_deposit_at"] == "2026-02-15"

    @pytest.mark.asyncio
    async def test_today_usage_included(self) -> None:
        ledger = UserLedger(balance_sats=100)
        ledger.debit("search", 10)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "today_usage" in result
        today = date.today().isoformat()
        assert result["today_usage"]["search"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_no_today_usage(self) -> None:
        ledger = UserLedger(balance_sats=100)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "today_usage" not in result

    @pytest.mark.asyncio
    async def test_does_not_modify_state(self) -> None:
        ledger = UserLedger(balance_sats=500)
        cache = _mock_cache(ledger)
        await check_balance_tool(cache, "user1")
        cache.mark_dirty.assert_not_called()
        assert ledger.balance_sats == 500

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
