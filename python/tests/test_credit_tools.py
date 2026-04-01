"""Tests for credit management tools: purchase_credits, check_payment, check_balance, btcpay_status."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pynostr.event import Event  # type: ignore[import-untyped]
from pynostr.key import PrivateKey  # type: ignore[import-untyped]
from tollbooth.btcpay_client import (
    BTCPayAuthError,
    BTCPayClient,
    BTCPayConnectionError,
    BTCPayServerError,
)
from tollbooth.certificate import reset_jti_store
from tollbooth.config import TollboothConfig
from tollbooth.constants import MAX_INVOICE_SATS
from tollbooth.ledger import ToolUsage, Tranche, UserLedger
from tollbooth.ledger_cache import LedgerCache
from tollbooth.nostr_certificate import NOSTR_CERT_KIND, NOSTR_CERT_LABEL, NOSTR_CERT_TAG
from tollbooth.tools.credits import (
    account_statement_tool,
    btcpay_status_tool,
    check_balance_tool,
    check_payment_tool,
    compute_low_balance_warning,
    purchase_credits_tool,
    reconcile_pending_invoices,
)

# ---------------------------------------------------------------------------
# Module-level Nostr test keypair for certificate signing
# ---------------------------------------------------------------------------

_TEST_NOSTR_PRIVKEY = PrivateKey()
_TEST_AUTHORITY_NPUB = _TEST_NOSTR_PRIVKEY.public_key.bech32()

_MOCK_BOLT11 = "lnbc200n1pjmockinvoice"

_RESOLVE_PATCH = "tollbooth.tools.credits.resolve_lightning_address"

_jti_counter = 0


def _test_certificate(net_sats: int = 980, amount_sats: int = 1000) -> str:
    """Sign a test Nostr certificate event with a unique JTI for each call."""
    global _jti_counter
    _jti_counter += 1
    jti = f"test-jti-{_jti_counter}-{time.time_ns()}"
    claims = {
        "sub": "test-op",
        "amount_sats": amount_sats,
        "fee_sats": amount_sats - net_sats,
        "net_sats": net_sats,
        "dpyc_protocol": "dpyp-01-base-certificate",
    }
    expiration = int(time.time()) + 600
    tags: list[list[str]] = [
        ["d", jti],
        ["p", "deadbeef" * 8],
        ["t", NOSTR_CERT_TAG],
        ["L", NOSTR_CERT_LABEL],
        ["expiration", str(expiration)],
    ]
    event = Event(
        kind=NOSTR_CERT_KIND,
        content=json.dumps(claims),
        tags=tags,
        pubkey=_TEST_NOSTR_PRIVKEY.public_key.hex(),
        created_at=int(time.time()),
    )
    event.sign(_TEST_NOSTR_PRIVKEY.hex())
    return json.dumps(event.to_dict())


@pytest.fixture(autouse=True)
def _clean_jti_store():
    """Reset the JTI store before each test to prevent cross-test replay."""
    reset_jti_store()
    yield
    reset_jti_store()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAST = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _tranche(
    sats: int,
    remaining: int | None = None,
    expires_at: str | None = None,
    invoice_id: str = "test-init",
) -> Tranche:
    return Tranche(
        granted_at=_PAST,
        original_sats=sats,
        remaining_sats=remaining if remaining is not None else sats,
        invoice_id=invoice_id,
        expires_at=expires_at,
    )


def _ledger_with_balance(balance: int, **kwargs) -> UserLedger:
    """Create a UserLedger with initial balance as a single non-expiring tranche."""
    ledger = UserLedger(**kwargs)
    if balance > 0:
        ledger.tranches.append(_tranche(balance))
    return ledger


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


def _make_config(**overrides) -> TollboothConfig:
    """Create a TollboothConfig with sensible defaults."""
    defaults = {
        "btcpay_host": "https://btcpay.example.com",
        "btcpay_store_id": "store-123",
        "btcpay_api_key": "key-abc",
    }
    defaults.update(overrides)
    return TollboothConfig(**defaults)


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
        result = await purchase_credits_tool(
            btcpay, cache, "user1", 1000,
            certificate=_test_certificate(net_sats=1000),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert result["success"] is True
        assert result["invoice_id"] == "inv-42"
        assert result["amount_sats"] == 1000
        assert "checkout_link" in result
        assert "certificate_jti" in result
        btcpay.create_invoice.assert_called_once()
        cache.mark_dirty.assert_called_once_with("user1")

    @pytest.mark.asyncio
    async def test_zero_amount_rejected(self) -> None:
        btcpay = _mock_btcpay()
        cache = _mock_cache()
        result = await purchase_credits_tool(
            btcpay, cache, "user1", 0,
            certificate=_test_certificate(amount_sats=0, net_sats=0),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert result["success"] is False
        assert "positive" in result["error"]

    @pytest.mark.asyncio
    async def test_negative_amount_rejected(self) -> None:
        btcpay = _mock_btcpay()
        cache = _mock_cache()
        result = await purchase_credits_tool(
            btcpay, cache, "user1", -100,
            certificate=_test_certificate(amount_sats=-100, net_sats=-100),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_btcpay_error(self) -> None:
        btcpay = _mock_btcpay(error=BTCPayConnectionError("DNS failed"))
        cache = _mock_cache()
        result = await purchase_credits_tool(
            btcpay, cache, "user1", 1000,
            certificate=_test_certificate(net_sats=1000),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert result["success"] is False
        assert "BTCPay error" in result["error"]

    @pytest.mark.asyncio
    async def test_invoice_added_to_pending(self) -> None:
        btcpay = _mock_btcpay({"id": "inv-99", "checkoutLink": "https://x.com"})
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        await purchase_credits_tool(
            btcpay, cache, "user1", 500,
            certificate=_test_certificate(net_sats=500),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert "inv-99" in ledger.pending_invoices

class TestInvoiceDmCallback:
    """Tests for the invoice_dm_callback parameter on purchase_credits_tool."""

    @pytest.mark.asyncio
    async def test_dm_callback_fires_on_success(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-dm-1",
            "checkoutLink": "https://pay.example.com/inv-dm-1",
            "expirationTime": "2026-03-08T00:00:00Z",
        })
        cache = _mock_cache()
        dm_cb = AsyncMock()

        result = await purchase_credits_tool(
            btcpay, cache, "user1", 1000,
            certificate=_test_certificate(net_sats=1000),
            authority_npub=_TEST_AUTHORITY_NPUB,
            invoice_dm_callback=dm_cb,
        )
        assert result["success"] is True
        assert result["invoice_dm_sent"] is True
        dm_cb.assert_awaited_once()
        dm_text = dm_cb.call_args[0][0]
        assert "1,000 sats" in dm_text
        assert "https://pay.example.com/inv-dm-1" in dm_text

    @pytest.mark.asyncio
    async def test_dm_callback_failure_does_not_block_purchase(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-dm-2",
            "checkoutLink": "https://pay.example.com/inv-dm-2",
            "expirationTime": "2026-03-08T00:00:00Z",
        })
        cache = _mock_cache()
        dm_cb = AsyncMock(side_effect=Exception("relay down"))

        result = await purchase_credits_tool(
            btcpay, cache, "user1", 1000,
            certificate=_test_certificate(net_sats=1000),
            authority_npub=_TEST_AUTHORITY_NPUB,
            invoice_dm_callback=dm_cb,
        )
        assert result["success"] is True
        assert result["invoice_dm_sent"] is False
        assert result["invoice_id"] == "inv-dm-2"

    @pytest.mark.asyncio
    async def test_no_callback_means_no_dm_key(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-dm-3",
            "checkoutLink": "https://pay.example.com/inv-dm-3",
        })
        cache = _mock_cache()

        result = await purchase_credits_tool(
            btcpay, cache, "user1", 1000,
            certificate=_test_certificate(net_sats=1000),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert result["success"] is True
        assert "invoice_dm_sent" not in result


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
        result = await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert result["success"] is True
        assert result["credits_granted"] == 1000
        assert result["balance_api_sats"] == 1000
        assert "inv-1" not in ledger.pending_invoices
        cache.mark_dirty.assert_called()

    @pytest.mark.asyncio
    async def test_settled_creates_tranche(self) -> None:
        """Settlement creates a new tranche in the ledger."""
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "500",
        })
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert len(ledger.tranches) == 1
        assert ledger.tranches[0].original_sats == 500

    @pytest.mark.asyncio
    async def test_settled_with_ttl(self) -> None:
        """Settlement with default TTL creates expiring tranche."""
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "500",
        })
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        await check_payment_tool(
            btcpay, cache, "user1", "inv-1",
            default_credit_ttl_seconds=3600,
        )
        assert ledger.tranches[0].expires_at is not None

    @pytest.mark.asyncio
    async def test_settled_without_ttl(self) -> None:
        """Settlement without explicit TTL creates perpetual tranche."""
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "500",
        })
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        await check_payment_tool(btcpay, cache, "user1", "inv-1")
        assert ledger.tranches[0].expires_at is None

    @pytest.mark.asyncio
    async def test_settled_idempotent(self) -> None:
        btcpay = _mock_btcpay({
            "id": "inv-1", "status": "Settled", "amount": "1000",
        })
        ledger = _ledger_with_balance(1000, credited_invoices=["inv-1"])
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
        assert result["pending_invoice_ids"] == []
        assert result["active_tranches"] == 0

    @pytest.mark.asyncio
    async def test_with_balance(self) -> None:
        ledger = _ledger_with_balance(
            5000,
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
        assert result["pending_invoice_ids"] == ["inv-a"]
        assert result["last_deposit_at"] == "2026-02-15"
        assert result["active_tranches"] == 1

    @pytest.mark.asyncio
    async def test_today_usage_included(self) -> None:
        ledger = _ledger_with_balance(100)
        ledger.debit("search", 10)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "today_usage" in result
        assert result["today_usage"]["search"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_no_today_usage(self) -> None:
        ledger = _ledger_with_balance(100)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "today_usage" not in result

    @pytest.mark.asyncio
    async def test_does_not_modify_state(self) -> None:
        ledger = _ledger_with_balance(500)
        cache = _mock_cache(ledger)
        await check_balance_tool(cache, "user1")
        cache.mark_dirty.assert_not_called()
        assert ledger.balance_api_sats == 500

    @pytest.mark.asyncio
    async def test_seed_balance_granted_shown(self) -> None:
        """check_balance shows seed_balance_granted when seed sentinel is present."""
        ledger = _ledger_with_balance(1000, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert result["seed_balance_granted"] is True

    @pytest.mark.asyncio
    async def test_seed_balance_granted_absent(self) -> None:
        """check_balance omits seed_balance_granted when no seed was applied."""
        ledger = _ledger_with_balance(500)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert "seed_balance_granted" not in result

    @pytest.mark.asyncio
    async def test_expiration_fields_present(self) -> None:
        """check_balance includes tranche expiration analytics."""
        soon = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        ledger = UserLedger(tranches=[
            _tranche(100, expires_at=soon),
            _tranche(200, expires_at=None),
        ])
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert result["total_expired_api_sats"] == 0
        assert result["expiring_within_24h_sats"] == 100
        assert result["next_expiration_iso"] == soon
        assert result["active_tranches"] == 2

    @pytest.mark.asyncio
    async def test_no_expiration_fields_when_no_ttl(self) -> None:
        """No expiration fields when all tranches are non-expiring."""
        ledger = _ledger_with_balance(500)
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user1")
        assert result["total_expired_api_sats"] == 0
        assert "expiring_within_24h_sats" not in result
        assert "next_expiration_iso" not in result


# ---------------------------------------------------------------------------
# compute_low_balance_warning
# ---------------------------------------------------------------------------


class TestComputeLowBalanceWarning:
    def test_above_threshold_returns_none(self) -> None:
        """Balance well above threshold -> no warning."""
        ledger = _ledger_with_balance(5000)
        assert compute_low_balance_warning(ledger, seed_balance_sats=1000) is None

    def test_at_threshold_returns_none(self) -> None:
        """Balance exactly at threshold -> no warning (>= means safe)."""
        # seed_balance_sats=500, threshold = max(500//5, 100) = 100
        ledger = _ledger_with_balance(100, credited_invoices=["seed_balance_v1"])
        assert compute_low_balance_warning(ledger, seed_balance_sats=500) is None

    def test_below_threshold_returns_warning(self) -> None:
        """Balance below threshold -> warning dict."""
        ledger = _ledger_with_balance(50, credited_invoices=["seed_balance_v1"])
        warning = compute_low_balance_warning(ledger, seed_balance_sats=500)
        assert warning is not None
        assert warning["balance_api_sats"] == 50
        assert warning["threshold_api_sats"] == 100
        assert "purchase_credits" in warning["purchase_command"]
        assert "message" in warning

    def test_settled_invoice_reference(self) -> None:
        """Threshold is 20% of last settled invoice's api_sats_credited."""
        ledger = _ledger_with_balance(50)
        ledger.record_invoice_created("inv-1", amount_sats=1000, multiplier=1, created_at="")
        ledger.record_invoice_settled("inv-1", api_sats_credited=1000, settled_at="")
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        # threshold = max(1000 // 5, 100) = 200
        assert warning["threshold_api_sats"] == 200

    def test_seed_only_user(self) -> None:
        """Seed-only user: reference is seed_balance_sats."""
        ledger = _ledger_with_balance(10, credited_invoices=["seed_balance_v1"])
        warning = compute_low_balance_warning(ledger, seed_balance_sats=1000)
        assert warning is not None
        # threshold = max(1000 // 5, 100) = 200
        assert warning["threshold_api_sats"] == 200

    def test_no_history_uses_floor(self) -> None:
        """No invoices, no seed: reference is the floor."""
        ledger = _ledger_with_balance(50)
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        # reference = floor (100), threshold = max(100//5, 100) = 100
        assert warning["threshold_api_sats"] == 100

    def test_retroactive_invoice_suggested_defaults(self) -> None:
        """Retroactive invoice (amount_sats=0) -> suggested defaults to 1000."""
        ledger = _ledger_with_balance(5)
        ledger.record_invoice_settled("inv-retro", api_sats_credited=500, settled_at="")
        # retroactive: amount_sats=0 in the record
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        assert warning["suggested_top_up_sats"] == 1000

    def test_suggested_capped_at_max(self) -> None:
        """Suggested top-up capped at MAX_INVOICE_SATS."""
        ledger = _ledger_with_balance(5)
        ledger.record_invoice_created(
            "inv-big", amount_sats=5_000_000, multiplier=1, created_at="",
        )
        ledger.record_invoice_settled("inv-big", api_sats_credited=5_000_000, settled_at="")
        warning = compute_low_balance_warning(ledger, seed_balance_sats=0)
        assert warning is not None
        assert warning["suggested_top_up_sats"] == MAX_INVOICE_SATS

    def test_zero_seed_no_invoices(self) -> None:
        """Zero seed + no invoices -> floor path."""
        ledger = _ledger_with_balance(50)
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
        result = await purchase_credits_tool(
            btcpay, cache, "user1", MAX_INVOICE_SATS,
            certificate=_test_certificate(amount_sats=MAX_INVOICE_SATS, net_sats=MAX_INVOICE_SATS - 20),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_over_max_rejected(self) -> None:
        """MAX_INVOICE_SATS + 1 is rejected."""
        btcpay = _mock_btcpay()
        cache = _mock_cache()
        result = await purchase_credits_tool(
            btcpay, cache, "user1", MAX_INVOICE_SATS + 1,
            certificate=_test_certificate(amount_sats=MAX_INVOICE_SATS + 1, net_sats=MAX_INVOICE_SATS),
            authority_npub=_TEST_AUTHORITY_NPUB,
        )
        assert result["success"] is False
        assert "maximum" in result["error"]
        assert "1,000,000" in result["error"]


# ---------------------------------------------------------------------------
# btcpay_status (uses TollboothConfig)
# ---------------------------------------------------------------------------


class TestBTCPayStatus:
    @pytest.mark.asyncio
    async def test_all_configured_and_reachable(self) -> None:
        """Full config, server reachable, store accessible."""
        config = _make_config()
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(return_value={"name": "My Store"})
        btcpay.get_api_key_info = AsyncMock(return_value={
            "permissions": ["btcpay.store.cancreateinvoice", "btcpay.store.canviewinvoices"]
        })

        result = await btcpay_status_tool(config, btcpay)

        assert result["btcpay_host"] == "https://btcpay.example.com"
        assert result["btcpay_store_id"] == "store-123"
        assert result["btcpay_api_key_status"] == "present"
        assert result["server_reachable"] is True
        assert result["store_name"] == "My Store"

    @pytest.mark.asyncio
    async def test_api_key_missing(self) -> None:
        """Missing API key — network checks skipped."""
        config = _make_config(btcpay_api_key=None)

        result = await btcpay_status_tool(config, None)

        assert result["btcpay_api_key_status"] == "missing"
        assert result["server_reachable"] is None
        assert result["store_name"] is None

    @pytest.mark.asyncio
    async def test_host_missing(self) -> None:
        """Missing host — network checks skipped."""
        config = _make_config(btcpay_host=None)

        result = await btcpay_status_tool(config, None)

        assert result["btcpay_host"] is None
        assert result["server_reachable"] is None
        assert result["store_name"] is None

    @pytest.mark.asyncio
    async def test_server_unreachable(self) -> None:
        """Server unreachable — health check fails."""
        config = _make_config()
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(
            side_effect=BTCPayConnectionError("DNS failed")
        )
        btcpay.get_store = AsyncMock(return_value={"name": "My Store"})
        btcpay.get_api_key_info = AsyncMock(return_value={"permissions": []})

        result = await btcpay_status_tool(config, btcpay)

        assert result["server_reachable"] is False
        assert result["store_name"] == "My Store"

    @pytest.mark.asyncio
    async def test_store_auth_failure(self) -> None:
        """Store returns 401 — reported as unauthorized."""
        config = _make_config()
        btcpay = AsyncMock(spec=BTCPayClient)
        btcpay.health_check = AsyncMock(return_value={"synchronized": True})
        btcpay.get_store = AsyncMock(
            side_effect=BTCPayAuthError("Unauthorized", status_code=401)
        )
        btcpay.get_api_key_info = AsyncMock(return_value={"permissions": []})

        result = await btcpay_status_tool(config, btcpay)

        assert result["server_reachable"] is True
        assert result["store_name"] == "unauthorized"


# ---------------------------------------------------------------------------
# btcpay_status — authority_config diagnostic
# ---------------------------------------------------------------------------


class TestBTCPayStatusAuthorityConfig:
    @pytest.mark.asyncio
    async def test_authority_npub_configured(self) -> None:
        """Valid npub shows configured, verification enabled."""
        config = _make_config(authority_npub=_TEST_AUTHORITY_NPUB)
        result = await btcpay_status_tool(config, None)

        auth = result["authority_config"]
        assert auth["npub_configured"] is True
        assert auth["certificate_verification_enabled"] is True
        assert auth["authority_npub"] == _TEST_AUTHORITY_NPUB

    @pytest.mark.asyncio
    async def test_authority_npub_not_configured(self) -> None:
        """No npub set — configured false, verification disabled."""
        config = _make_config(authority_npub=None)
        result = await btcpay_status_tool(config, None)

        auth = result["authority_config"]
        assert auth["npub_configured"] is False
        assert auth["certificate_verification_enabled"] is False
        assert "authority_npub" not in auth


# ---------------------------------------------------------------------------
# reconcile_pending_invoices
# ---------------------------------------------------------------------------


class TestReconcilePendingInvoices:
    @pytest.mark.asyncio
    async def test_credits_settled_invoice(self) -> None:
        """Settled pending invoice gets credited and flushed."""
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "500"})
        ledger = UserLedger(pending_invoices=["inv-1"])
        cache = _mock_cache(ledger)

        result = await reconcile_pending_invoices(btcpay, cache, "user1")

        assert result["reconciled"] == 1
        assert result["actions"][0]["action"] == "credited"
        assert result["actions"][0]["api_sats"] == 500
        assert ledger.balance_api_sats == 500
        assert "inv-1" in ledger.credited_invoices
        cache.flush_user.assert_called_once_with("user1")

    @pytest.mark.asyncio
    async def test_removes_expired_invoice(self) -> None:
        """Expired pending invoice is removed from pending list."""
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Expired"})
        ledger = UserLedger(pending_invoices=["inv-1"])
        cache = _mock_cache(ledger)

        result = await reconcile_pending_invoices(btcpay, cache, "user1")

        assert result["reconciled"] == 1
        assert result["actions"][0]["action"] == "removed"
        assert result["actions"][0]["reason"] == "Expired"
        assert "inv-1" not in ledger.pending_invoices
        cache.flush_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_on_empty_pending(self) -> None:
        """No pending invoices -> no actions, no flush."""
        btcpay = _mock_btcpay()
        ledger = UserLedger()
        cache = _mock_cache(ledger)

        result = await reconcile_pending_invoices(btcpay, cache, "user1")

        assert result["reconciled"] == 0
        assert result["actions"] == []
        cache.flush_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_btcpay_errors(self) -> None:
        """BTCPay errors for individual invoices are skipped, not fatal."""
        from tollbooth.btcpay_client import BTCPayConnectionError

        btcpay = _mock_btcpay(error=BTCPayConnectionError("timeout"))
        ledger = UserLedger(pending_invoices=["inv-1"])
        cache = _mock_cache(ledger)

        result = await reconcile_pending_invoices(btcpay, cache, "user1")

        assert result["reconciled"] == 0
        # Invoice stays pending since we couldn't check it
        assert "inv-1" in ledger.pending_invoices
        cache.flush_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_already_credited(self) -> None:
        """Already-credited settled invoice is not double-credited."""
        btcpay = _mock_btcpay({"id": "inv-1", "status": "Settled", "amount": "500"})
        ledger = _ledger_with_balance(
            500,
            pending_invoices=["inv-1"],
            credited_invoices=["inv-1"],
        )
        cache = _mock_cache(ledger)

        result = await reconcile_pending_invoices(btcpay, cache, "user1")

        assert result["reconciled"] == 0
        # Balance should not increase
        assert ledger.balance_api_sats == 500
        cache.flush_user.assert_not_called()


# ---------------------------------------------------------------------------
# AccountStatement
# ---------------------------------------------------------------------------


class TestAccountStatement:
    @pytest.mark.asyncio
    async def test_empty_ledger(self) -> None:
        """Fresh user gets a valid statement with zero values."""
        cache = _mock_cache()
        result = await account_statement_tool(cache, "user1")

        assert result["success"] is True
        assert "generated_at" in result
        assert result["statement_period_days"] == 30
        assert result["account_summary"]["balance_api_sats"] == 0
        assert result["account_summary"]["total_deposited_api_sats"] == 0
        assert result["purchase_history"] == []
        assert result["active_tranches"] == []
        assert result["tool_usage_all_time"] == []
        assert result["daily_usage"] == []

    @pytest.mark.asyncio
    async def test_with_invoices(self) -> None:
        """Statement includes invoice line items sorted by date descending."""
        ledger = UserLedger()
        ledger.record_invoice_created("inv-a", 500, 1, "2026-02-20T10:00:00+00:00")
        ledger.record_invoice_settled("inv-a", 500, "2026-02-20T10:05:00+00:00", "Settled")
        ledger.credit_deposit(500, "inv-a")

        ledger.record_invoice_created("inv-b", 1000, 1, "2026-02-21T12:00:00+00:00")
        ledger.record_invoice_settled("inv-b", 1000, "2026-02-21T12:05:00+00:00", "Settled")
        ledger.credit_deposit(1000, "inv-b")

        cache = _mock_cache(ledger)
        result = await account_statement_tool(cache, "user1")

        assert result["success"] is True
        history = result["purchase_history"]
        assert len(history) == 2
        # Most recent first
        assert history[0]["invoice_id"] == "inv-b"
        assert history[1]["invoice_id"] == "inv-a"
        assert history[0]["amount_sats"] == 1000
        assert history[0]["settled_at"] == "2026-02-21T12:05:00+00:00"

    @pytest.mark.asyncio
    async def test_active_tranches(self) -> None:
        """Statement lists non-expired, non-zero tranches."""
        ledger = UserLedger()
        # First tranche — will be fully consumed by FIFO debit
        ledger.credit_deposit(100, "inv-a")
        # Second tranche — survives
        ledger.credit_deposit(300, "inv-b")
        # FIFO debit consumes oldest (inv-a) fully
        ledger.debit("test_tool", 100)

        cache = _mock_cache(ledger)
        result = await account_statement_tool(cache, "user1")

        tranches = result["active_tranches"]
        assert len(tranches) == 1
        assert tranches[0]["remaining_sats"] == 300
        assert tranches[0]["invoice_id"] == "inv-b"

    @pytest.mark.asyncio
    async def test_tool_usage(self) -> None:
        """All-time usage sorted by api_sats descending."""
        ledger = _ledger_with_balance(5000)
        ledger.debit("search_thoughts", 10)
        ledger.debit("search_thoughts", 10)
        ledger.debit("brain_query", 100)

        cache = _mock_cache(ledger)
        result = await account_statement_tool(cache, "user1")

        usage = result["tool_usage_all_time"]
        assert len(usage) == 2
        # brain_query has more api_sats, so comes first
        assert usage[0]["tool"] == "brain_query"
        assert usage[0]["api_sats"] == 100
        assert usage[0]["calls"] == 1
        assert usage[1]["tool"] == "search_thoughts"
        assert usage[1]["api_sats"] == 20
        assert usage[1]["calls"] == 2

    @pytest.mark.asyncio
    async def test_daily_usage_respects_days_param(self) -> None:
        """Daily log only includes entries within the requested window."""
        ledger = _ledger_with_balance(5000)
        today = date.today()
        # Add entries for 3 days
        for offset in (0, 15, 45):
            day = (today - timedelta(days=offset)).isoformat()
            ledger.daily_log[day] = {
                "get_thought": ToolUsage(calls=5, api_sats=5),
            }

        cache = _mock_cache(ledger)
        result = await account_statement_tool(cache, "user1", days=30)

        daily = result["daily_usage"]
        # Only today (0 days ago) and 15 days ago are within 30 days
        assert len(daily) == 2
        assert daily[0]["date"] == today.isoformat()
        assert daily[1]["date"] == (today - timedelta(days=15)).isoformat()

    @pytest.mark.asyncio
    async def test_summary_totals(self) -> None:
        """Account summary reflects deposited, consumed, expired correctly."""
        ledger = UserLedger()
        ledger.credit_deposit(1000, "inv-1")
        ledger.debit("tool_a", 300)
        # Simulate some previously expired amount
        ledger.total_expired_api_sats = 200

        cache = _mock_cache(ledger)
        result = await account_statement_tool(cache, "user1")

        summary = result["account_summary"]
        assert summary["balance_api_sats"] == 700
        assert summary["total_deposited_api_sats"] == 1000
        assert summary["total_consumed_api_sats"] == 300
        assert summary["total_expired_api_sats"] == 200
