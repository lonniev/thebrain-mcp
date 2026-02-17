"""Tests for invoice persistence: InvoiceRecord, ledger methods, credit tool integration."""

import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.btcpay_client import BTCPayClient, BTCPayError
from thebrain_mcp.ledger import InvoiceRecord, UserLedger
from thebrain_mcp.ledger_cache import LedgerCache
from thebrain_mcp.tools.credits import (
    check_balance_tool,
    check_payment_tool,
    purchase_credits_tool,
    restore_credits_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_btcpay(invoice_response: dict | None = None, error: Exception | None = None):
    client = AsyncMock(spec=BTCPayClient)
    if error:
        client.create_invoice = AsyncMock(side_effect=error)
        client.get_invoice = AsyncMock(side_effect=error)
    else:
        resp = invoice_response or {"id": "inv-1", "checkoutLink": "https://pay.example.com"}
        client.create_invoice = AsyncMock(return_value=resp)
        client.get_invoice = AsyncMock(return_value=resp)
    return client


def _mock_cache(ledger: UserLedger | None = None):
    cache = AsyncMock(spec=LedgerCache)
    cache.get = AsyncMock(return_value=ledger or UserLedger())
    cache.mark_dirty = MagicMock()
    return cache


TIER_CONFIG = json.dumps({"default": {"credit_multiplier": 1}, "vip": {"credit_multiplier": 100}})
USER_TIERS = json.dumps({"user-vip": "vip"})


# ---------------------------------------------------------------------------
# InvoiceRecord dataclass
# ---------------------------------------------------------------------------


class TestInvoiceRecord:
    def test_defaults(self) -> None:
        rec = InvoiceRecord(invoice_id="inv-1", amount_sats=1000)
        assert rec.status == "Pending"
        assert rec.api_sats_credited == 0
        assert rec.multiplier == 1
        assert rec.settled_at is None
        assert rec.btcpay_status is None

    def test_to_dict(self) -> None:
        rec = InvoiceRecord(
            invoice_id="inv-1", amount_sats=1000, api_sats_credited=100000,
            multiplier=100, status="Settled", created_at="2026-02-17T00:00:00",
            settled_at="2026-02-17T01:00:00", btcpay_status="Settled",
        )
        d = rec.to_dict()
        assert d["invoice_id"] == "inv-1"
        assert d["amount_sats"] == 1000
        assert d["api_sats_credited"] == 100000
        assert d["multiplier"] == 100
        assert d["status"] == "Settled"
        assert d["settled_at"] == "2026-02-17T01:00:00"

    def test_from_dict(self) -> None:
        d = {
            "invoice_id": "inv-2", "amount_sats": 500, "api_sats_credited": 50000,
            "multiplier": 100, "status": "Settled", "created_at": "2026-02-17T00:00:00",
            "settled_at": "2026-02-17T01:00:00", "btcpay_status": "Settled",
        }
        rec = InvoiceRecord.from_dict(d)
        assert rec.invoice_id == "inv-2"
        assert rec.amount_sats == 500
        assert rec.api_sats_credited == 50000

    def test_from_dict_missing_fields(self) -> None:
        rec = InvoiceRecord.from_dict({"invoice_id": "inv-3"})
        assert rec.invoice_id == "inv-3"
        assert rec.amount_sats == 0
        assert rec.status == "Pending"
        assert rec.multiplier == 1

    def test_roundtrip(self) -> None:
        original = InvoiceRecord(
            invoice_id="inv-rt", amount_sats=2000, api_sats_credited=200000,
            multiplier=100, status="Settled", created_at="2026-02-17T00:00:00",
            settled_at="2026-02-17T01:00:00", btcpay_status="Settled",
        )
        restored = InvoiceRecord.from_dict(original.to_dict())
        assert restored.invoice_id == original.invoice_id
        assert restored.amount_sats == original.amount_sats
        assert restored.api_sats_credited == original.api_sats_credited
        assert restored.status == original.status
        assert restored.settled_at == original.settled_at


# ---------------------------------------------------------------------------
# Invoice record methods on UserLedger
# ---------------------------------------------------------------------------


class TestInvoiceRecordOnLedger:
    def test_record_invoice_created(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 100, "2026-02-17T00:00:00")
        assert "inv-1" in ledger.invoices
        rec = ledger.invoices["inv-1"]
        assert rec.status == "Pending"
        assert rec.amount_sats == 1000
        assert rec.multiplier == 100
        assert rec.btcpay_status == "New"

    def test_record_invoice_settled_existing(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 100, "2026-02-17T00:00:00")
        ledger.record_invoice_settled("inv-1", 100000, "2026-02-17T01:00:00", "Settled")
        rec = ledger.invoices["inv-1"]
        assert rec.status == "Settled"
        assert rec.api_sats_credited == 100000
        assert rec.settled_at == "2026-02-17T01:00:00"
        # Original fields preserved
        assert rec.amount_sats == 1000
        assert rec.multiplier == 100

    def test_record_invoice_settled_missing_creates_retroactive(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_settled("inv-old", 50000, "2026-02-17T01:00:00", "Settled")
        rec = ledger.invoices["inv-old"]
        assert rec.status == "Settled"
        assert rec.api_sats_credited == 50000
        assert rec.amount_sats == 0  # Unknown
        assert rec.multiplier == 0  # Unknown

    def test_record_invoice_terminal_expired(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 1, "2026-02-17T00:00:00")
        ledger.record_invoice_terminal("inv-1", "Expired", "Expired")
        assert ledger.invoices["inv-1"].status == "Expired"

    def test_record_invoice_terminal_invalid(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 1, "2026-02-17T00:00:00")
        ledger.record_invoice_terminal("inv-1", "Invalid", "Invalid")
        assert ledger.invoices["inv-1"].status == "Invalid"

    def test_record_invoice_terminal_missing_is_noop(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_terminal("inv-missing", "Expired", "Expired")
        assert "inv-missing" not in ledger.invoices


# ---------------------------------------------------------------------------
# Invoice serialization
# ---------------------------------------------------------------------------


class TestInvoiceSerialization:
    def test_schema_version_3(self) -> None:
        ledger = UserLedger()
        obj = json.loads(ledger.to_json())
        assert obj["v"] == 3

    def test_invoices_survive_roundtrip(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 100, "2026-02-17T00:00:00")
        ledger.record_invoice_settled("inv-1", 100000, "2026-02-17T01:00:00", "Settled")

        restored = UserLedger.from_json(ledger.to_json())
        assert "inv-1" in restored.invoices
        rec = restored.invoices["inv-1"]
        assert rec.status == "Settled"
        assert rec.api_sats_credited == 100000
        assert rec.amount_sats == 1000

    def test_v2_ledger_migration(self) -> None:
        """v2 JSON (no invoices key) deserializes with empty invoices dict."""
        v2_json = json.dumps({
            "v": 2, "balance_api_sats": 500, "total_deposited_api_sats": 1000,
            "total_consumed_api_sats": 500, "pending_invoices": ["inv-p"],
            "credited_invoices": ["inv-c"], "last_deposit_at": "2026-02-17",
            "daily_log": {}, "history": {},
        })
        ledger = UserLedger.from_json(v2_json)
        assert ledger.invoices == {}
        assert ledger.balance_api_sats == 500
        assert ledger.credited_invoices == ["inv-c"]

    def test_v1_ledger_migration(self) -> None:
        """v1 JSON (old field names, no invoices) still works."""
        v1_json = json.dumps({
            "v": 1, "balance_sats": 300, "total_deposited_sats": 600,
            "total_consumed_sats": 300, "pending_invoices": [],
            "credited_invoices": [], "daily_log": {}, "history": {},
        })
        ledger = UserLedger.from_json(v1_json)
        assert ledger.invoices == {}
        assert ledger.balance_api_sats == 300

    def test_empty_invoices_dict(self) -> None:
        ledger = UserLedger()
        obj = json.loads(ledger.to_json())
        assert obj["invoices"] == {}
        restored = UserLedger.from_json(ledger.to_json())
        assert restored.invoices == {}

    def test_multiple_invoices_roundtrip(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 100, "2026-02-17T00:00:00")
        ledger.record_invoice_created("inv-2", 2000, 1, "2026-02-17T00:01:00")
        ledger.record_invoice_settled("inv-1", 100000, "2026-02-17T01:00:00", "Settled")
        ledger.record_invoice_terminal("inv-2", "Expired", "Expired")

        restored = UserLedger.from_json(ledger.to_json())
        assert len(restored.invoices) == 2
        assert restored.invoices["inv-1"].status == "Settled"
        assert restored.invoices["inv-2"].status == "Expired"


# ---------------------------------------------------------------------------
# purchase_credits records invoice
# ---------------------------------------------------------------------------


class TestPurchaseCreditsInvoiceRecord:
    @pytest.mark.asyncio
    async def test_invoice_record_created_on_purchase(self) -> None:
        ledger = UserLedger()
        btcpay = _mock_btcpay({"id": "inv-new", "checkoutLink": "https://pay"})
        cache = _mock_cache(ledger)

        result = await purchase_credits_tool(btcpay, cache, "user-1", 1000)
        assert result["success"] is True
        assert "inv-new" in ledger.invoices
        assert ledger.invoices["inv-new"].status == "Pending"

    @pytest.mark.asyncio
    async def test_invoice_record_has_correct_metadata(self) -> None:
        ledger = UserLedger()
        btcpay = _mock_btcpay({"id": "inv-meta", "checkoutLink": "https://pay"})
        cache = _mock_cache(ledger)

        result = await purchase_credits_tool(
            btcpay, cache, "user-vip", 2000,
            tier_config_json=TIER_CONFIG, user_tiers_json=USER_TIERS,
        )
        rec = ledger.invoices["inv-meta"]
        assert rec.amount_sats == 2000
        assert rec.multiplier == 100
        assert rec.created_at != ""  # ISO timestamp populated
        assert rec.btcpay_status == "New"

    @pytest.mark.asyncio
    async def test_invoice_record_flushed_to_vault(self) -> None:
        ledger = UserLedger()
        btcpay = _mock_btcpay({"id": "inv-flush", "checkoutLink": "https://pay"})
        cache = _mock_cache(ledger)

        await purchase_credits_tool(btcpay, cache, "user-1", 1000)
        cache.mark_dirty.assert_called_with("user-1")
        cache.flush_user.assert_called_with("user-1")


# ---------------------------------------------------------------------------
# check_payment updates invoice records
# ---------------------------------------------------------------------------


class TestCheckPaymentInvoiceRecord:
    @pytest.mark.asyncio
    async def test_settled_updates_invoice_record(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-settle", 1000, 1, "2026-02-17T00:00:00")
        ledger.pending_invoices.append("inv-settle")
        btcpay = _mock_btcpay({"id": "inv-settle", "status": "Settled", "amount": "1000"})
        cache = _mock_cache(ledger)

        result = await check_payment_tool(btcpay, cache, "user-1", "inv-settle")
        assert result["credits_granted"] == 1000
        rec = ledger.invoices["inv-settle"]
        assert rec.status == "Settled"
        assert rec.api_sats_credited == 1000
        assert rec.settled_at is not None

    @pytest.mark.asyncio
    async def test_expired_updates_invoice_record(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-exp", 1000, 1, "2026-02-17T00:00:00")
        ledger.pending_invoices.append("inv-exp")
        btcpay = _mock_btcpay({"id": "inv-exp", "status": "Expired"})
        cache = _mock_cache(ledger)

        await check_payment_tool(btcpay, cache, "user-1", "inv-exp")
        assert ledger.invoices["inv-exp"].status == "Expired"

    @pytest.mark.asyncio
    async def test_invalid_updates_invoice_record(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-inv", 1000, 1, "2026-02-17T00:00:00")
        ledger.pending_invoices.append("inv-inv")
        btcpay = _mock_btcpay({"id": "inv-inv", "status": "Invalid"})
        cache = _mock_cache(ledger)

        await check_payment_tool(btcpay, cache, "user-1", "inv-inv")
        assert ledger.invoices["inv-inv"].status == "Invalid"

    @pytest.mark.asyncio
    async def test_settled_idempotent_does_not_overwrite_record(self) -> None:
        """Already-credited invoice keeps its existing record untouched."""
        ledger = UserLedger()
        ledger.record_invoice_created("inv-idem", 1000, 100, "2026-02-17T00:00:00")
        ledger.record_invoice_settled("inv-idem", 100000, "2026-02-17T01:00:00", "Settled")
        ledger.credited_invoices.append("inv-idem")
        btcpay = _mock_btcpay({"id": "inv-idem", "status": "Settled", "amount": "1000"})
        cache = _mock_cache(ledger)

        result = await check_payment_tool(btcpay, cache, "user-1", "inv-idem")
        assert result["credits_granted"] == 0
        # Record unchanged
        assert ledger.invoices["inv-idem"].api_sats_credited == 100000


# ---------------------------------------------------------------------------
# restore_credits vault-first logic
# ---------------------------------------------------------------------------


class TestRestoreCreditsVaultFirst:
    @pytest.mark.asyncio
    async def test_restore_from_vault_record(self) -> None:
        """Restore uses vault record when credited_invoices lost but invoice record exists."""
        ledger = UserLedger()
        # Simulate: invoice was settled and recorded, but credited_invoices was lost
        ledger.record_invoice_created("inv-vault", 1000, 100, "2026-02-17T00:00:00")
        ledger.record_invoice_settled("inv-vault", 100000, "2026-02-17T01:00:00", "Settled")
        # NOTE: invoice_id NOT in credited_invoices (simulating partial data loss)

        btcpay = _mock_btcpay()  # Should not be called
        cache = _mock_cache(ledger)

        result = await restore_credits_tool(btcpay, cache, "user-1", "inv-vault")
        assert result["success"] is True
        assert result["source"] == "vault_record"
        assert result["credits_granted"] == 100000
        assert ledger.balance_api_sats == 100000
        btcpay.get_invoice.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_falls_back_to_btcpay(self) -> None:
        """No vault record → falls back to BTCPay verification."""
        ledger = UserLedger()
        btcpay = _mock_btcpay({"id": "inv-btc", "status": "Settled", "amount": "500"})
        cache = _mock_cache(ledger)

        result = await restore_credits_tool(btcpay, cache, "user-1", "inv-btc")
        assert result["success"] is True
        assert result["source"] == "btcpay"
        assert result["credits_granted"] == 500
        btcpay.get_invoice.assert_called_once_with("inv-btc")

    @pytest.mark.asyncio
    async def test_restore_btcpay_fallback_creates_record(self) -> None:
        """BTCPay fallback restoration creates an invoice record."""
        ledger = UserLedger()
        btcpay = _mock_btcpay({"id": "inv-rec", "status": "Settled", "amount": "1000"})
        cache = _mock_cache(ledger)

        await restore_credits_tool(btcpay, cache, "user-1", "inv-rec")
        assert "inv-rec" in ledger.invoices
        rec = ledger.invoices["inv-rec"]
        assert rec.status == "Settled"
        assert rec.api_sats_credited == 1000

    @pytest.mark.asyncio
    async def test_restore_idempotent_via_credited_invoices(self) -> None:
        """If invoice is in credited_invoices, return 0 even with vault record."""
        ledger = UserLedger()
        ledger.record_invoice_settled("inv-dup", 100000, "2026-02-17T01:00:00", "Settled")
        ledger.credited_invoices.append("inv-dup")

        btcpay = _mock_btcpay()
        cache = _mock_cache(ledger)

        result = await restore_credits_tool(btcpay, cache, "user-1", "inv-dup")
        assert result["credits_granted"] == 0
        assert ledger.balance_api_sats == 0  # No double credit


# ---------------------------------------------------------------------------
# check_balance invoice summary
# ---------------------------------------------------------------------------


class TestCheckBalanceInvoiceSummary:
    @pytest.mark.asyncio
    async def test_no_invoices_no_summary(self) -> None:
        ledger = UserLedger()
        cache = _mock_cache(ledger)
        result = await check_balance_tool(cache, "user-1")
        assert "invoice_summary" not in result

    @pytest.mark.asyncio
    async def test_invoice_summary_counts(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 1, "2026-02-17T00:00:00")
        ledger.record_invoice_created("inv-2", 2000, 1, "2026-02-17T00:01:00")
        ledger.record_invoice_settled("inv-1", 1000, "2026-02-17T01:00:00", "Settled")
        cache = _mock_cache(ledger)

        result = await check_balance_tool(cache, "user-1")
        summary = result["invoice_summary"]
        assert summary["total_invoices"] == 2
        assert summary["settled_count"] == 1
        assert summary["pending_count"] == 1

    @pytest.mark.asyncio
    async def test_invoice_summary_sats_totals(self) -> None:
        ledger = UserLedger()
        ledger.record_invoice_created("inv-1", 1000, 100, "2026-02-17T00:00:00")
        ledger.record_invoice_created("inv-2", 2000, 100, "2026-02-17T00:01:00")
        ledger.record_invoice_settled("inv-1", 100000, "2026-02-17T01:00:00", "Settled")
        ledger.record_invoice_settled("inv-2", 200000, "2026-02-17T01:01:00", "Settled")
        cache = _mock_cache(ledger)

        result = await check_balance_tool(cache, "user-1")
        summary = result["invoice_summary"]
        assert summary["total_real_sats"] == 3000
        assert summary["total_api_sats_credited"] == 300000


# ---------------------------------------------------------------------------
# Invoice durability
# ---------------------------------------------------------------------------


class TestInvoiceDurability:
    @pytest.mark.asyncio
    async def test_invoice_record_survives_cache_rebuild(self) -> None:
        """purchase → settle → serialize → deserialize → record intact."""
        ledger = UserLedger()
        ledger.record_invoice_created("inv-dur", 1000, 100, "2026-02-17T00:00:00")
        ledger.credit_deposit(100000, "inv-dur")
        ledger.record_invoice_settled("inv-dur", 100000, "2026-02-17T01:00:00", "Settled")

        # Simulate vault roundtrip
        restored = UserLedger.from_json(ledger.to_json())
        assert "inv-dur" in restored.invoices
        assert restored.invoices["inv-dur"].status == "Settled"
        assert restored.invoices["inv-dur"].api_sats_credited == 100000
        assert restored.balance_api_sats == 100000
        assert "inv-dur" in restored.credited_invoices

    @pytest.mark.asyncio
    async def test_restore_after_cache_rebuild_uses_vault_record(self) -> None:
        """After cache loss, restore_credits finds vault record and restores."""
        # Build ledger with settled invoice
        ledger = UserLedger()
        ledger.record_invoice_created("inv-lost", 500, 100, "2026-02-17T00:00:00")
        ledger.record_invoice_settled("inv-lost", 50000, "2026-02-17T01:00:00", "Settled")
        # Simulate partial loss: credited_invoices cleared but invoices dict intact
        json_data = ledger.to_json()
        obj = json.loads(json_data)
        obj["credited_invoices"] = []  # Simulate partial data loss
        obj["balance_api_sats"] = 0
        damaged_json = json.dumps(obj)

        rebuilt = UserLedger.from_json(damaged_json)
        assert "inv-lost" not in rebuilt.credited_invoices
        assert "inv-lost" in rebuilt.invoices

        btcpay = _mock_btcpay()
        cache = _mock_cache(rebuilt)

        result = await restore_credits_tool(btcpay, cache, "user-1", "inv-lost")
        assert result["success"] is True
        assert result["source"] == "vault_record"
        assert result["credits_granted"] == 50000
        btcpay.get_invoice.assert_not_called()
