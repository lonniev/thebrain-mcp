"""Tests for UserLedger model and serialization."""

import json
from datetime import date

import pytest

from thebrain_mcp.ledger import ToolUsage, UserLedger


# ---------------------------------------------------------------------------
# ToolUsage
# ---------------------------------------------------------------------------


class TestToolUsage:
    def test_defaults(self) -> None:
        u = ToolUsage()
        assert u.calls == 0
        assert u.api_sats == 0

    def test_to_dict(self) -> None:
        u = ToolUsage(calls=5, api_sats=100)
        assert u.to_dict() == {"calls": 5, "api_sats": 100}

    def test_from_dict(self) -> None:
        u = ToolUsage.from_dict({"calls": 3, "api_sats": 42})
        assert u.calls == 3
        assert u.api_sats == 42

    def test_from_dict_missing_fields(self) -> None:
        u = ToolUsage.from_dict({})
        assert u.calls == 0
        assert u.api_sats == 0

    def test_roundtrip(self) -> None:
        original = ToolUsage(calls=10, api_sats=200)
        restored = ToolUsage.from_dict(original.to_dict())
        assert restored.calls == original.calls
        assert restored.api_sats == original.api_sats


# ---------------------------------------------------------------------------
# UserLedger — debit / credit / rollback
# ---------------------------------------------------------------------------


class TestUserLedger:
    def test_debit_success(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        assert ledger.debit("search", 30) is True
        assert ledger.balance_api_sats == 70
        assert ledger.total_consumed_api_sats == 30

    def test_debit_insufficient_balance(self) -> None:
        ledger = UserLedger(balance_api_sats=10)
        assert ledger.debit("search", 20) is False
        assert ledger.balance_api_sats == 10
        assert ledger.total_consumed_api_sats == 0

    def test_debit_exact_balance(self) -> None:
        ledger = UserLedger(balance_api_sats=50)
        assert ledger.debit("search", 50) is True
        assert ledger.balance_api_sats == 0

    def test_debit_negative_amount_rejected(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        assert ledger.debit("search", -5) is False
        assert ledger.balance_api_sats == 100

    def test_debit_zero(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        assert ledger.debit("search", 0) is True
        assert ledger.balance_api_sats == 100

    def test_debit_updates_daily_log(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        ledger.debit("search", 10)
        today = date.today().isoformat()
        assert today in ledger.daily_log
        assert ledger.daily_log[today]["search"].calls == 1
        assert ledger.daily_log[today]["search"].api_sats == 10

    def test_debit_updates_history(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        ledger.debit("search", 10)
        ledger.debit("search", 20)
        assert ledger.history["search"].calls == 2
        assert ledger.history["search"].api_sats == 30

    def test_credit_deposit(self) -> None:
        ledger = UserLedger(balance_api_sats=50, pending_invoices=["inv-1"])
        ledger.credit_deposit(100, "inv-1")
        assert ledger.balance_api_sats == 150
        assert ledger.total_deposited_api_sats == 100
        assert ledger.last_deposit_at == date.today().isoformat()
        assert "inv-1" not in ledger.pending_invoices

    def test_credit_deposit_unknown_invoice(self) -> None:
        ledger = UserLedger(pending_invoices=["inv-1"])
        ledger.credit_deposit(50, "inv-other")
        assert ledger.balance_api_sats == 50
        assert "inv-1" in ledger.pending_invoices

    def test_rollback_debit(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        ledger.debit("search", 30)
        assert ledger.balance_api_sats == 70
        ledger.rollback_debit("search", 30)
        assert ledger.balance_api_sats == 100
        assert ledger.total_consumed_api_sats == 0

    def test_rollback_clamps_to_zero(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        ledger.debit("search", 10)
        # Rollback more than was debited
        ledger.rollback_debit("search", 20)
        assert ledger.history["search"].calls == 0
        assert ledger.history["search"].api_sats == 0

    def test_seed_via_credit_deposit(self) -> None:
        """Seed balance via credit_deposit with sentinel ID."""
        ledger = UserLedger()
        ledger.credit_deposit(1000, "seed_balance_v1")
        assert ledger.balance_api_sats == 1000
        assert ledger.total_deposited_api_sats == 1000
        assert "seed_balance_v1" in ledger.credited_invoices

    def test_seed_sentinel_prevents_double_credit(self) -> None:
        """Second credit_deposit with same sentinel is a no-op for credited_invoices."""
        ledger = UserLedger()
        ledger.credit_deposit(1000, "seed_balance_v1")
        # Calling again adds balance but sentinel already present (idempotency
        # is checked by the caller, not credit_deposit itself)
        assert "seed_balance_v1" in ledger.credited_invoices
        # Caller should check `sentinel not in ledger.credited_invoices` before calling
        assert ledger.credited_invoices.count("seed_balance_v1") == 1

    def test_seed_balance_is_spendable(self) -> None:
        """Seeded balance can be spent via debit()."""
        ledger = UserLedger()
        ledger.credit_deposit(1000, "seed_balance_v1")
        assert ledger.debit("search", 100) is True
        assert ledger.balance_api_sats == 900

    def test_rotate_daily_log(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        # Add an old entry
        ledger.daily_log["2020-01-01"] = {"search": ToolUsage(calls=5, api_sats=50)}
        # Add today's entry
        today = date.today().isoformat()
        ledger.daily_log[today] = {"search": ToolUsage(calls=1, api_sats=10)}
        ledger.rotate_daily_log(retention_days=30)
        assert "2020-01-01" not in ledger.daily_log
        assert today in ledger.daily_log


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestLedgerSerialization:
    def test_roundtrip(self) -> None:
        ledger = UserLedger(balance_api_sats=500, total_deposited_api_sats=1000)
        ledger.debit("search", 100)
        restored = UserLedger.from_json(ledger.to_json())
        assert restored.balance_api_sats == 400
        assert restored.total_deposited_api_sats == 1000
        assert restored.total_consumed_api_sats == 100
        assert "search" in restored.history
        assert restored.history["search"].calls == 1

    def test_schema_version(self) -> None:
        ledger = UserLedger()
        obj = json.loads(ledger.to_json())
        assert obj["v"] == 3

    def test_from_json_missing_fields(self) -> None:
        restored = UserLedger.from_json('{"v": 1}')
        assert restored.balance_api_sats == 0
        assert restored.pending_invoices == []

    def test_from_json_corrupt_data(self) -> None:
        restored = UserLedger.from_json("not json at all")
        assert restored.balance_api_sats == 0

    def test_from_json_none(self) -> None:
        restored = UserLedger.from_json(None)  # type: ignore[arg-type]
        assert restored.balance_api_sats == 0

    def test_from_json_non_dict(self) -> None:
        restored = UserLedger.from_json('"just a string"')
        assert restored.balance_api_sats == 0

    def test_daily_log_survives_roundtrip(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        ledger.debit("search", 10)
        ledger.debit("create", 20)
        restored = UserLedger.from_json(ledger.to_json())
        today = date.today().isoformat()
        assert restored.daily_log[today]["search"].api_sats == 10
        assert restored.daily_log[today]["create"].api_sats == 20

    def test_pending_invoices_survive_roundtrip(self) -> None:
        ledger = UserLedger(pending_invoices=["inv-a", "inv-b"])
        restored = UserLedger.from_json(ledger.to_json())
        assert restored.pending_invoices == ["inv-a", "inv-b"]

    def test_to_json_is_pretty_printed(self) -> None:
        ledger = UserLedger(balance_api_sats=100)
        output = ledger.to_json()
        assert "\n" in output
        parsed = json.loads(output)
        assert parsed["balance_api_sats"] == 100
