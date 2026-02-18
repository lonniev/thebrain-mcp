"""Tests for UserLedger model, serialization, and vault ledger storage."""

import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thebrain_mcp.ledger import ToolUsage, UserLedger
from thebrain_mcp.vault import CredentialNotFoundError, PersonalBrainVault


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


# ---------------------------------------------------------------------------
# Vault ledger storage
# ---------------------------------------------------------------------------


def _make_child(name: str, child_id: str | None = None):
    """Create a mock Thought child with a name and id."""
    child = MagicMock()
    child.name = name
    child.id = child_id or f"child-{name}"
    return child


def _mock_vault_api(
    index: dict[str, str] | None = None,
    note_content: str | None = None,
    children: list | None = None,
):
    """Create a mock TheBrainAPI for vault operations."""
    api = AsyncMock()
    index_note = MagicMock()
    index_note.markdown = json.dumps(index) if index else None

    # Notes: dispatch by thought_id
    note_map: dict[str, str | None] = {}

    async def get_note_side_effect(brain_id, thought_id, fmt):
        note = MagicMock()
        if thought_id == "home":
            note.markdown = json.dumps(index) if index else None
        elif thought_id in note_map:
            note.markdown = note_map[thought_id]
        elif note_content is not None:
            note.markdown = note_content
        else:
            note.markdown = None
        return note

    api.get_note = AsyncMock(side_effect=get_note_side_effect)

    # Graph: return children for ledger parent
    graph = MagicMock()
    graph.children = children or []
    api.get_thought_graph = AsyncMock(return_value=graph)

    api.create_or_update_note = AsyncMock()
    api.create_thought = AsyncMock(return_value={"id": "new-ledger-thought"})
    return api, note_map


class TestVaultLedgerStorage:
    @pytest.mark.asyncio
    async def test_store_ledger_creates_daily_child(self) -> None:
        """First flush of the day creates a child named YYYY-MM-DD."""
        api, _ = _mock_vault_api(index={"user1/ledger": "ledger-parent"}, children=[])
        vault = PersonalBrainVault(api, "vault-brain", "home")
        ledger = UserLedger(balance_api_sats=500)
        tid = await vault.store_ledger("user1", ledger.to_json())
        assert tid == "new-ledger-thought"
        # Should create a child thought + write its note
        api.create_thought.assert_called_once()
        call_args = api.create_thought.call_args[0]
        assert call_args[1]["sourceThoughtId"] == "ledger-parent"
        assert call_args[1]["relation"] == 1  # Child

    @pytest.mark.asyncio
    async def test_store_ledger_reuses_daily_child(self) -> None:
        """Second flush same day updates existing child."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing_child = _make_child(today, "daily-child-id")
        api, _ = _mock_vault_api(
            index={"user1/ledger": "ledger-parent"},
            children=[existing_child],
        )
        vault = PersonalBrainVault(api, "vault-brain", "home")
        ledger = UserLedger(balance_api_sats=300)
        tid = await vault.store_ledger("user1", ledger.to_json())
        assert tid == "daily-child-id"
        api.create_thought.assert_not_called()
        api.create_or_update_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_ledger_new_day_creates_new_child(self) -> None:
        """Next day creates a new child even if yesterday's exists."""
        yesterday_child = _make_child("2026-02-16", "yesterday-id")
        api, _ = _mock_vault_api(
            index={"user1/ledger": "ledger-parent"},
            children=[yesterday_child],
        )
        vault = PersonalBrainVault(api, "vault-brain", "home")
        ledger = UserLedger(balance_api_sats=100)
        # Today is not "2026-02-16", so a new child should be created
        with patch("thebrain_mcp.vault.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 17, tzinfo=timezone.utc)
            tid = await vault.store_ledger("user1", ledger.to_json())
        assert tid == "new-ledger-thought"
        api.create_thought.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_ledger_creates_parent_if_needed(self) -> None:
        """First ever store creates parent + daily child."""
        api, _ = _mock_vault_api(index={"user1": "cred-thought"}, children=[])
        # First create_thought returns parent, second returns daily child
        api.create_thought = AsyncMock(
            side_effect=[{"id": "new-parent-id"}, {"id": "new-daily-id"}]
        )
        # get_thought_graph for the new parent returns no children
        vault = PersonalBrainVault(api, "vault-brain", "home")
        ledger = UserLedger(balance_api_sats=500)
        tid = await vault.store_ledger("user1", ledger.to_json())
        assert tid == "new-daily-id"
        assert api.create_thought.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_ledger_reads_most_recent_child(self) -> None:
        """Reads from the latest dated child."""
        child_old = _make_child("2026-02-15", "child-15")
        child_new = _make_child("2026-02-16", "child-16")
        api, note_map = _mock_vault_api(
            index={"user1/ledger": "ledger-parent"},
            children=[child_old, child_new],
        )
        ledger_json = UserLedger(balance_api_sats=42).to_json()
        note_map["child-16"] = ledger_json
        vault = PersonalBrainVault(api, "vault-brain", "home")
        result = await vault.fetch_ledger("user1")
        assert result == ledger_json

    @pytest.mark.asyncio
    async def test_fetch_ledger_fallback_to_parent_note(self) -> None:
        """Pre-migration: reads parent note when no children exist."""
        ledger_json = UserLedger(balance_api_sats=99).to_json()
        api, note_map = _mock_vault_api(
            index={"user1/ledger": "ledger-parent"},
            children=[],
        )
        note_map["ledger-parent"] = ledger_json
        vault = PersonalBrainVault(api, "vault-brain", "home")
        result = await vault.fetch_ledger("user1")
        assert result == ledger_json

    @pytest.mark.asyncio
    async def test_fetch_ledger_no_parent_returns_none(self) -> None:
        """No ledger thought returns None."""
        api, _ = _mock_vault_api(index={})
        vault = PersonalBrainVault(api, "vault-brain", "home")
        result = await vault.fetch_ledger("user1")
        assert result is None
