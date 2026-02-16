"""Tests for UserLedger model, serialization, and vault ledger storage."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.ledger import ToolUsage, UserLedger
from thebrain_mcp.vault import CredentialNotFoundError, CredentialVault


# ---------------------------------------------------------------------------
# ToolUsage
# ---------------------------------------------------------------------------


class TestToolUsage:
    def test_defaults(self) -> None:
        u = ToolUsage()
        assert u.calls == 0
        assert u.sats == 0

    def test_to_dict(self) -> None:
        u = ToolUsage(calls=5, sats=100)
        assert u.to_dict() == {"calls": 5, "sats": 100}

    def test_from_dict(self) -> None:
        u = ToolUsage.from_dict({"calls": 3, "sats": 42})
        assert u.calls == 3
        assert u.sats == 42

    def test_from_dict_missing_fields(self) -> None:
        u = ToolUsage.from_dict({})
        assert u.calls == 0
        assert u.sats == 0

    def test_roundtrip(self) -> None:
        original = ToolUsage(calls=10, sats=200)
        restored = ToolUsage.from_dict(original.to_dict())
        assert restored.calls == original.calls
        assert restored.sats == original.sats


# ---------------------------------------------------------------------------
# UserLedger — debit / credit / rollback
# ---------------------------------------------------------------------------


class TestUserLedger:
    def test_debit_success(self) -> None:
        ledger = UserLedger(balance_sats=100)
        assert ledger.debit("search", 30) is True
        assert ledger.balance_sats == 70
        assert ledger.total_consumed_sats == 30

    def test_debit_insufficient_balance(self) -> None:
        ledger = UserLedger(balance_sats=10)
        assert ledger.debit("search", 20) is False
        assert ledger.balance_sats == 10
        assert ledger.total_consumed_sats == 0

    def test_debit_exact_balance(self) -> None:
        ledger = UserLedger(balance_sats=50)
        assert ledger.debit("search", 50) is True
        assert ledger.balance_sats == 0

    def test_debit_negative_amount_rejected(self) -> None:
        ledger = UserLedger(balance_sats=100)
        assert ledger.debit("search", -5) is False
        assert ledger.balance_sats == 100

    def test_debit_zero(self) -> None:
        ledger = UserLedger(balance_sats=100)
        assert ledger.debit("search", 0) is True
        assert ledger.balance_sats == 100

    def test_debit_updates_daily_log(self) -> None:
        ledger = UserLedger(balance_sats=100)
        ledger.debit("search", 10)
        today = date.today().isoformat()
        assert today in ledger.daily_log
        assert ledger.daily_log[today]["search"].calls == 1
        assert ledger.daily_log[today]["search"].sats == 10

    def test_debit_updates_history(self) -> None:
        ledger = UserLedger(balance_sats=100)
        ledger.debit("search", 10)
        ledger.debit("search", 20)
        assert ledger.history["search"].calls == 2
        assert ledger.history["search"].sats == 30

    def test_credit_deposit(self) -> None:
        ledger = UserLedger(balance_sats=50, pending_invoices=["inv-1"])
        ledger.credit_deposit(100, "inv-1")
        assert ledger.balance_sats == 150
        assert ledger.total_deposited_sats == 100
        assert ledger.last_deposit_at == date.today().isoformat()
        assert "inv-1" not in ledger.pending_invoices

    def test_credit_deposit_unknown_invoice(self) -> None:
        ledger = UserLedger(pending_invoices=["inv-1"])
        ledger.credit_deposit(50, "inv-other")
        assert ledger.balance_sats == 50
        assert "inv-1" in ledger.pending_invoices

    def test_rollback_debit(self) -> None:
        ledger = UserLedger(balance_sats=100)
        ledger.debit("search", 30)
        assert ledger.balance_sats == 70
        ledger.rollback_debit("search", 30)
        assert ledger.balance_sats == 100
        assert ledger.total_consumed_sats == 0

    def test_rollback_clamps_to_zero(self) -> None:
        ledger = UserLedger(balance_sats=100)
        ledger.debit("search", 10)
        # Rollback more than was debited
        ledger.rollback_debit("search", 20)
        assert ledger.history["search"].calls == 0
        assert ledger.history["search"].sats == 0

    def test_rotate_daily_log(self) -> None:
        ledger = UserLedger(balance_sats=100)
        # Add an old entry
        ledger.daily_log["2020-01-01"] = {"search": ToolUsage(calls=5, sats=50)}
        # Add today's entry
        today = date.today().isoformat()
        ledger.daily_log[today] = {"search": ToolUsage(calls=1, sats=10)}
        ledger.rotate_daily_log(retention_days=30)
        assert "2020-01-01" not in ledger.daily_log
        assert today in ledger.daily_log


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestLedgerSerialization:
    def test_roundtrip(self) -> None:
        ledger = UserLedger(balance_sats=500, total_deposited_sats=1000)
        ledger.debit("search", 100)
        restored = UserLedger.from_json(ledger.to_json())
        assert restored.balance_sats == 400
        assert restored.total_deposited_sats == 1000
        assert restored.total_consumed_sats == 100
        assert "search" in restored.history
        assert restored.history["search"].calls == 1

    def test_schema_version(self) -> None:
        ledger = UserLedger()
        obj = json.loads(ledger.to_json())
        assert obj["v"] == 1

    def test_from_json_missing_fields(self) -> None:
        restored = UserLedger.from_json('{"v": 1}')
        assert restored.balance_sats == 0
        assert restored.pending_invoices == []

    def test_from_json_corrupt_data(self) -> None:
        restored = UserLedger.from_json("not json at all")
        assert restored.balance_sats == 0

    def test_from_json_none(self) -> None:
        restored = UserLedger.from_json(None)  # type: ignore[arg-type]
        assert restored.balance_sats == 0

    def test_from_json_non_dict(self) -> None:
        restored = UserLedger.from_json('"just a string"')
        assert restored.balance_sats == 0

    def test_daily_log_survives_roundtrip(self) -> None:
        ledger = UserLedger(balance_sats=100)
        ledger.debit("search", 10)
        ledger.debit("create", 20)
        restored = UserLedger.from_json(ledger.to_json())
        today = date.today().isoformat()
        assert restored.daily_log[today]["search"].sats == 10
        assert restored.daily_log[today]["create"].sats == 20

    def test_pending_invoices_survive_roundtrip(self) -> None:
        ledger = UserLedger(pending_invoices=["inv-a", "inv-b"])
        restored = UserLedger.from_json(ledger.to_json())
        assert restored.pending_invoices == ["inv-a", "inv-b"]


# ---------------------------------------------------------------------------
# Vault ledger storage
# ---------------------------------------------------------------------------


def _mock_vault_api(
    index: dict[str, str] | None = None,
    note_content: str | None = None,
):
    """Create a mock TheBrainAPI for vault operations."""
    api = AsyncMock()
    index_note = MagicMock()
    index_note.markdown = json.dumps(index) if index else None
    api.get_note = AsyncMock(return_value=index_note)

    if note_content is not None:
        ledger_note = MagicMock()
        ledger_note.markdown = note_content

        async def get_note_side_effect(brain_id, thought_id, fmt):
            if thought_id == "home":
                return index_note
            return ledger_note

        api.get_note = AsyncMock(side_effect=get_note_side_effect)

    api.create_or_update_note = AsyncMock()
    api.create_thought = AsyncMock(return_value={"id": "new-ledger-thought"})
    return api


class TestVaultLedgerStorage:
    @pytest.mark.asyncio
    async def test_store_ledger_new(self) -> None:
        api = _mock_vault_api(index={"user1": "cred-thought"})
        vault = CredentialVault(api, "vault-brain", "home")
        ledger = UserLedger(balance_sats=500)
        tid = await vault.store_ledger("user1", ledger.to_json())
        assert tid == "new-ledger-thought"
        api.create_thought.assert_called_once()
        # Should write ledger note + update index
        assert api.create_or_update_note.call_count == 2

    @pytest.mark.asyncio
    async def test_store_ledger_existing(self) -> None:
        api = _mock_vault_api(index={"user1/ledger": "existing-ledger-thought"})
        vault = CredentialVault(api, "vault-brain", "home")
        ledger = UserLedger(balance_sats=300)
        tid = await vault.store_ledger("user1", ledger.to_json())
        assert tid == "existing-ledger-thought"
        api.create_thought.assert_not_called()
        api.create_or_update_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_ledger_success(self) -> None:
        ledger = UserLedger(balance_sats=42)
        ledger_json = ledger.to_json()
        api = _mock_vault_api(
            index={"user1/ledger": "ledger-thought"},
            note_content=ledger_json,
        )
        vault = CredentialVault(api, "vault-brain", "home")
        result = await vault.fetch_ledger("user1")
        assert result == ledger_json

    @pytest.mark.asyncio
    async def test_fetch_ledger_not_found(self) -> None:
        api = _mock_vault_api(index={})
        vault = CredentialVault(api, "vault-brain", "home")
        result = await vault.fetch_ledger("user1")
        assert result is None
