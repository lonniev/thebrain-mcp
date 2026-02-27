"""Tests verifying that auth/identity tools are zero-cost.

The bootstrap deadlock scenario: a user at 0 balance must be able to
activate_session -> purchase_credits -> check_payment without being
blocked by insufficient-balance errors. This file proves that every
auth/identity/diagnostic tool in the TOOL_COSTS table resolves to
0 api_sats, and that _debit_or_error lets them through even when
the user's ledger is completely empty.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thebrain_mcp.ledger import UserLedger
from thebrain_mcp.ledger_cache import LedgerCache
from thebrain_mcp.utils.constants import TOOL_COSTS, ToolTier


SAMPLE_NPUB = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"


# ---------------------------------------------------------------------------
# Helpers (same patterns as test_tool_gating.py)
# ---------------------------------------------------------------------------


def _ledger_with_balance(sats: int, **kwargs) -> UserLedger:
    """Create a UserLedger with the given balance via a tranche deposit."""
    ledger = UserLedger(**kwargs)
    if sats > 0:
        ledger.credit_deposit(sats, "test-seed")
    return ledger


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
    return patch("thebrain_mcp.server._get_current_user_id", return_value=user_id)


def _patch_ledger_cache(cache: AsyncMock):
    return patch("thebrain_mcp.server._get_ledger_cache", return_value=cache)


def _activate_dpyc(horizon_id: str, npub: str = SAMPLE_NPUB):
    import thebrain_mcp.server as srv
    srv._dpyc_sessions[horizon_id] = npub


# ---------------------------------------------------------------------------
# Auth/identity tools must be FREE in TOOL_COSTS
# ---------------------------------------------------------------------------


AUTH_IDENTITY_TOOLS = [
    "whoami",
    "session_status",
    "register_credentials",
    "upgrade_credentials",
    "activate_session",
    "activate_dpyc",
]


class TestAuthToolsAreFree:
    """Every auth/identity tool must be explicitly listed as ToolTier.FREE."""

    @pytest.mark.parametrize("tool_name", AUTH_IDENTITY_TOOLS)
    def test_auth_tool_is_free(self, tool_name: str) -> None:
        assert tool_name in TOOL_COSTS, f"{tool_name} missing from TOOL_COSTS"
        assert TOOL_COSTS[tool_name] == ToolTier.FREE, (
            f"{tool_name} should be FREE (0 api_sats), got {TOOL_COSTS[tool_name]}"
        )

    @pytest.mark.parametrize("tool_name", AUTH_IDENTITY_TOOLS)
    def test_auth_tool_cost_is_zero(self, tool_name: str) -> None:
        """Redundant but explicit: the integer value must be 0."""
        assert TOOL_COSTS[tool_name] == 0


# ---------------------------------------------------------------------------
# Zero-balance gating: auth tools must pass at 0 balance
# ---------------------------------------------------------------------------


class TestZeroBalanceGating:
    """_debit_or_error must return None (proceed) for every auth tool,
    even when the user has 0 api_sats."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", AUTH_IDENTITY_TOOLS)
    async def test_auth_tool_passes_at_zero_balance(self, tool_name: str) -> None:
        """Auth tools must never be blocked, even at 0 balance."""
        from thebrain_mcp.server import _debit_or_error

        # Set up a user with 0 balance
        ledger = _ledger_with_balance(0)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            result = await _debit_or_error(tool_name)

        # Free tools short-circuit before touching the ledger
        assert result is None
        assert ledger.balance_api_sats == 0
        cache.mark_dirty.assert_not_called()

    @pytest.mark.asyncio
    async def test_paid_tool_blocked_at_zero_balance(self) -> None:
        """Sanity check: a paid tool IS blocked at 0 balance."""
        from thebrain_mcp.server import _debit_or_error

        ledger = _ledger_with_balance(0)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            result = await _debit_or_error("search_thoughts")

        assert result is not None
        assert result["success"] is False
        assert "Insufficient balance" in result["error"]


# ---------------------------------------------------------------------------
# Bootstrap path: activate -> purchase_credits -> check_payment
# ---------------------------------------------------------------------------


BOOTSTRAP_TOOLS = [
    "activate_session",
    "session_status",
    "whoami",
    "purchase_credits",
    "check_payment",
    "check_balance",
]


class TestBootstrapPath:
    """A user at 0 balance must be able to walk the full bootstrap path:
    activate_session -> purchase_credits -> check_payment.
    All of these tools are FREE, so none should be gated."""

    @pytest.mark.asyncio
    async def test_full_bootstrap_sequence_at_zero_balance(self) -> None:
        """Simulate calling every bootstrap tool in sequence at 0 balance.
        None should be blocked by _debit_or_error."""
        from thebrain_mcp.server import _debit_or_error

        ledger = _ledger_with_balance(0)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            for tool_name in BOOTSTRAP_TOOLS:
                result = await _debit_or_error(tool_name)
                assert result is None, (
                    f"{tool_name} should be free but returned: {result}"
                )

        # Balance must remain 0 throughout — nothing was debited
        assert ledger.balance_api_sats == 0
        cache.mark_dirty.assert_not_called()

    @pytest.mark.asyncio
    async def test_bootstrap_tools_are_all_free_in_cost_table(self) -> None:
        """Every tool in the bootstrap path must be listed as FREE."""
        for tool_name in BOOTSTRAP_TOOLS:
            assert TOOL_COSTS.get(tool_name, 0) == 0, (
                f"{tool_name} is not FREE — bootstrap deadlock!"
            )

    @pytest.mark.asyncio
    async def test_activate_then_paid_tool_requires_credits(self) -> None:
        """After free bootstrap, a paid tool should still require credits."""
        from thebrain_mcp.server import _debit_or_error

        ledger = _ledger_with_balance(0)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            # Bootstrap tools all pass
            for tool_name in BOOTSTRAP_TOOLS:
                assert await _debit_or_error(tool_name) is None

            # But a paid tool is still gated
            result = await _debit_or_error("get_thought")
            assert result is not None
            assert result["success"] is False
            assert "Insufficient balance" in result["error"]


# ---------------------------------------------------------------------------
# No debit recorded for free tools
# ---------------------------------------------------------------------------


class TestNoDebitRecorded:
    """Free tools must not leave any usage footprint on the ledger."""

    @pytest.mark.asyncio
    async def test_activate_session_no_debit_at_positive_balance(self) -> None:
        """Even with positive balance, activate_session should debit 0."""
        from thebrain_mcp.server import _debit_or_error

        ledger = _ledger_with_balance(1000)
        cache = _mock_cache(ledger)
        _activate_dpyc("user-1")

        with _patch_cloud_user("user-1"), _patch_ledger_cache(cache):
            result = await _debit_or_error("activate_session")

        assert result is None
        # Balance unchanged
        assert ledger.balance_api_sats == 1000
        cache.mark_dirty.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollback_on_free_tool_is_noop(self) -> None:
        """Rollback on a free auth tool must be a no-op."""
        from thebrain_mcp.server import _rollback_debit

        for tool_name in AUTH_IDENTITY_TOOLS:
            await _rollback_debit(tool_name)
            # Should not raise or interact with any state
