"""Tests for the tool gating middleware (_debit_or_error / _rollback_debit)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache
from thebrain_mcp.utils.constants import TOOL_COSTS, ToolTier

SAMPLE_NPUB = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_dpyc_sessions():
    """Ensure DPYC sessions are clean before and after each test."""
    import thebrain_mcp.server as srv
    srv._dpyc_sessions.clear()
    yield
    srv._dpyc_sessions.clear()


def _mock_cache(ledger: UserLedger | None = None) -> AsyncMock:
    cache = AsyncMock(spec=LedgerCache)
    cache.get = AsyncMock(return_value=ledger or UserLedger())
    cache.mark_dirty = MagicMock()
    return cache


def _patch_cloud_user(user_id: str | None):
    """Patch _get_current_user_id to return the given user_id."""
    return patch("thebrain_mcp.server._get_current_user_id", return_value=user_id)


def _patch_ledger_cache(cache: AsyncMock):
    """Patch _get_ledger_cache to return a mock cache."""
    return patch("thebrain_mcp.server._get_ledger_cache", return_value=cache)


def _activate_dpyc(horizon_id: str, npub: str = SAMPLE_NPUB):
    """Activate a DPYC session for the given Horizon user."""
    import thebrain_mcp.server as srv
    srv._dpyc_sessions[horizon_id] = npub


# ---------------------------------------------------------------------------
# _debit_or_error
# ---------------------------------------------------------------------------


class TestDebitOrError:
    @pytest.mark.asyncio
    async def test_free_tool_no_debit(self) -> None:
        """Free tools (cost 0) should return None without touching the ledger."""
        from thebrain_mcp.server import _debit_or_error

        # No mocks needed — free tools short-circuit before checking user_id
        result = await _debit_or_error("whoami")
        assert result is None

    @pytest.mark.asyncio
    async def test_read_tool_debits_1_sat(self) -> None:
        """Read-tier tool debits 1 sat and marks dirty."""
        from thebrain_mcp.server import _debit_or_error

        ledger = UserLedger(balance_api_sats=100)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            result = await _debit_or_error("search_thoughts")

        assert result is None
        assert ledger.balance_api_sats == 99
        cache.mark_dirty.assert_called_once_with(SAMPLE_NPUB)

    @pytest.mark.asyncio
    async def test_write_tool_debits_5_sats(self) -> None:
        """Write-tier tool debits 5 sats."""
        from thebrain_mcp.server import _debit_or_error

        ledger = UserLedger(balance_api_sats=100)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            result = await _debit_or_error("create_thought")

        assert result is None
        assert ledger.balance_api_sats == 95

    @pytest.mark.asyncio
    async def test_heavy_tool_debits_10_sats(self) -> None:
        """Heavy-tier tool debits 10 sats."""
        from thebrain_mcp.server import _debit_or_error

        ledger = UserLedger(balance_api_sats=100)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            result = await _debit_or_error("brain_query")

        assert result is None
        assert ledger.balance_api_sats == 90

    @pytest.mark.asyncio
    async def test_insufficient_balance_returns_error(self) -> None:
        """Insufficient balance returns an error dict with a hint."""
        from thebrain_mcp.server import _debit_or_error

        ledger = UserLedger(balance_api_sats=0)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            result = await _debit_or_error("search_thoughts")

        assert result is not None
        assert result["success"] is False
        assert "Insufficient balance" in result["error"]
        assert "purchase_credits" in result["error"]
        # Balance unchanged
        assert ledger.balance_api_sats == 0
        cache.mark_dirty.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_dpyc_session_returns_error(self) -> None:
        """Paid tool without DPYC session returns helpful error."""
        from thebrain_mcp.server import _debit_or_error

        with _patch_cloud_user("user-1"):
            result = await _debit_or_error("search_thoughts")

        assert result is not None
        assert result["success"] is False
        assert "No DPYC identity active" in result["error"]
        assert "register_credentials" in result["error"]

    @pytest.mark.asyncio
    async def test_stdio_mode_skips_gating(self) -> None:
        """STDIO mode (no user_id) should skip gating even for paid tools."""
        from thebrain_mcp.server import _debit_or_error

        with _patch_cloud_user(None):
            result = await _debit_or_error("brain_query")

        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_tool_treated_as_free(self) -> None:
        """Unlisted tools default to cost 0 (free)."""
        from thebrain_mcp.server import _debit_or_error

        result = await _debit_or_error("some_unknown_tool")
        assert result is None


# ---------------------------------------------------------------------------
# _rollback_debit
# ---------------------------------------------------------------------------


class TestRollbackDebit:
    @pytest.mark.asyncio
    async def test_rollback_restores_balance(self) -> None:
        """Rollback after a failed API call restores balance."""
        from thebrain_mcp.server import _debit_or_error, _rollback_debit

        ledger = UserLedger(balance_api_sats=100)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            # Debit first
            await _debit_or_error("search_thoughts")
            assert ledger.balance_api_sats == 99

            # Rollback
            await _rollback_debit("search_thoughts")
            assert ledger.balance_api_sats == 100

        # mark_dirty called twice (once for debit, once for rollback)
        assert cache.mark_dirty.call_count == 2

    @pytest.mark.asyncio
    async def test_rollback_free_tool_is_noop(self) -> None:
        """Rollback on a free tool does nothing."""
        from thebrain_mcp.server import _rollback_debit

        # Should not raise or touch any state
        await _rollback_debit("whoami")

    @pytest.mark.asyncio
    async def test_rollback_stdio_mode_is_noop(self) -> None:
        """Rollback in STDIO mode does nothing (ValueError caught)."""
        from thebrain_mcp.server import _rollback_debit

        with _patch_cloud_user(None):
            await _rollback_debit("brain_query")


# ---------------------------------------------------------------------------
# TOOL_COSTS completeness
# ---------------------------------------------------------------------------


class TestToolCostsCompleteness:
    def test_all_tiers_have_correct_values(self) -> None:
        """Verify tier values match expectations."""
        assert ToolTier.FREE == 0
        assert ToolTier.READ == 1
        assert ToolTier.WRITE == 5
        assert ToolTier.HEAVY == 10

    def test_free_tools_cost_zero(self) -> None:
        """All free tools should be cost 0."""
        free_tools = [
            "whoami", "session_status", "register_credentials",
            "upgrade_credentials", "activate_session", "list_brains",
            "purchase_credits", "check_payment", "check_balance",
            "btcpay_status", "test_low_balance_warning",
        ]
        for tool in free_tools:
            assert TOOL_COSTS[tool] == 0, f"{tool} should be free"

    def test_read_tools_cost_one(self) -> None:
        """All read tools should cost 1 sat."""
        read_tools = [
            "get_brain", "get_brain_stats", "set_active_brain",
            "get_thought", "get_thought_by_name", "search_thoughts",
            "get_thought_graph", "get_types", "get_tags", "get_note",
            "get_link", "get_attachment", "get_attachment_content",
            "list_attachments",
        ]
        for tool in read_tools:
            assert TOOL_COSTS[tool] == 1, f"{tool} should cost 1 sat"

    def test_write_tools_cost_five(self) -> None:
        """All write tools should cost 5 sats."""
        write_tools = [
            "create_thought", "update_thought", "delete_thought",
            "create_link", "update_link", "delete_link",
            "create_or_update_note", "append_to_note",
            "add_file_attachment", "add_url_attachment", "delete_attachment",
        ]
        for tool in write_tools:
            assert TOOL_COSTS[tool] == 5, f"{tool} should cost 5 sats"

    def test_heavy_tools_cost_ten(self) -> None:
        """All heavy tools should cost 10 sats."""
        heavy_tools = ["brain_query", "get_modifications", "get_thought_graph_paginated"]
        for tool in heavy_tools:
            assert TOOL_COSTS[tool] == 10, f"{tool} should cost 10 sats"


# ---------------------------------------------------------------------------
# _with_warning integration tests
# ---------------------------------------------------------------------------


class TestWithWarning:
    @pytest.mark.asyncio
    async def test_stdio_mode_unchanged(self) -> None:
        """STDIO mode (no user_id): result returned unchanged."""
        from thebrain_mcp.server import _with_warning

        original = {"success": True, "data": "hello"}
        with _patch_cloud_user(None):
            result = await _with_warning(original)
        assert result is original
        assert "low_balance_warning" not in result

    @pytest.mark.asyncio
    async def test_healthy_balance_no_warning(self) -> None:
        """Healthy balance: no warning key added."""
        from thebrain_mcp.server import _with_warning

        ledger = UserLedger(balance_api_sats=5000, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        with _patch_cloud_user("user-1"), \
             _patch_ledger_cache(cache), \
             patch("thebrain_mcp.server.get_settings", return_value=mock_settings):
            result = await _with_warning({"success": True})

        assert "low_balance_warning" not in result

    @pytest.mark.asyncio
    async def test_low_balance_warning_present(self) -> None:
        """Low balance: warning key injected."""
        from thebrain_mcp.server import _with_warning

        ledger = UserLedger(balance_api_sats=10, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        with _patch_cloud_user("user-1"), \
             _patch_ledger_cache(cache), \
             patch("thebrain_mcp.server.get_settings", return_value=mock_settings):
            result = await _with_warning({"success": True})

        assert "low_balance_warning" in result
        assert result["low_balance_warning"]["balance_api_sats"] == 10
        assert "purchase_credits" in result["low_balance_warning"]["purchase_command"]

    @pytest.mark.asyncio
    async def test_no_dpyc_session_returns_original(self) -> None:
        """No DPYC session: ValueError caught, original returned unchanged."""
        from thebrain_mcp.server import _with_warning

        original = {"success": True, "data": "hello"}
        with _patch_cloud_user("user-1"):
            result = await _with_warning(original)
        assert result is original
        assert "low_balance_warning" not in result

    @pytest.mark.asyncio
    async def test_exception_returns_original(self) -> None:
        """Exception in warning path: original result returned unmodified."""
        from thebrain_mcp.server import _with_warning

        _activate_dpyc("user-1")
        original = {"success": True, "data": "important"}
        with _patch_cloud_user("user-1"), \
             patch("thebrain_mcp.server._get_ledger_cache", side_effect=RuntimeError("boom")):
            result = await _with_warning(original)

        assert result is original
        assert "low_balance_warning" not in result

    @pytest.mark.asyncio
    async def test_result_not_mutated_in_place(self) -> None:
        """Original dict should not be mutated when warning is added."""
        from thebrain_mcp.server import _with_warning

        ledger = UserLedger(balance_api_sats=10, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        original = {"success": True}
        with _patch_cloud_user("user-1"), \
             _patch_ledger_cache(cache), \
             patch("thebrain_mcp.server.get_settings", return_value=mock_settings):
            result = await _with_warning(original)

        # result should have the warning, but original should not
        assert "low_balance_warning" in result
        assert "low_balance_warning" not in original


# ---------------------------------------------------------------------------
# test_low_balance_warning tool
# ---------------------------------------------------------------------------


class TestTestLowBalanceWarning:
    @pytest.mark.asyncio
    async def test_simulated_low_balance_shows_warning(self) -> None:
        """Simulated balance below threshold should produce a warning."""
        from thebrain_mcp.server import _test_low_balance_warning_impl

        ledger = UserLedger(balance_api_sats=999_999, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        _activate_dpyc("user-1")
        with _patch_cloud_user("user-1"), \
             _patch_ledger_cache(cache), \
             patch("thebrain_mcp.server.get_settings", return_value=mock_settings):
            result = await _test_low_balance_warning_impl(simulated_balance_api_sats=10)

        assert result["success"] is True
        assert result["simulated_balance_api_sats"] == 10
        assert result["real_balance_api_sats"] == 999_999
        assert "low_balance_warning" in result
        assert result["low_balance_warning"]["balance_api_sats"] == 10

    @pytest.mark.asyncio
    async def test_simulated_healthy_balance_no_warning(self) -> None:
        """Simulated balance above threshold should not produce a warning."""
        from thebrain_mcp.server import _test_low_balance_warning_impl

        ledger = UserLedger(balance_api_sats=999_999, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        _activate_dpyc("user-1")
        with _patch_cloud_user("user-1"), \
             _patch_ledger_cache(cache), \
             patch("thebrain_mcp.server.get_settings", return_value=mock_settings):
            result = await _test_low_balance_warning_impl(simulated_balance_api_sats=5000)

        assert result["success"] is True
        assert result["simulated_balance_api_sats"] == 5000
        assert "low_balance_warning" not in result

    def test_tool_is_free_in_tool_costs(self) -> None:
        """test_low_balance_warning must be FREE tier."""
        assert TOOL_COSTS["test_low_balance_warning"] == ToolTier.FREE

    @pytest.mark.asyncio
    async def test_real_ledger_not_mutated(self) -> None:
        """The real ledger balance must not change after simulation."""
        from thebrain_mcp.server import _test_low_balance_warning_impl

        ledger = UserLedger(balance_api_sats=500, credited_invoices=["seed_balance_v1"])
        cache = _mock_cache(ledger)

        mock_settings = MagicMock()
        mock_settings.seed_balance_sats = 1000

        with _patch_cloud_user("user-1"), \
             _patch_ledger_cache(cache), \
             patch("thebrain_mcp.server.get_settings", return_value=mock_settings):
            await _test_low_balance_warning_impl(simulated_balance_api_sats=5)

        assert ledger.balance_api_sats == 500
