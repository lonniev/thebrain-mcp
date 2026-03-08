"""Tests for DPYC identity tools and effective user ID resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clean_dpyc_sessions():
    """Ensure DPYC sessions are clean before and after each test."""
    import thebrain_mcp.server as srv
    srv._dpyc_sessions.clear()
    yield
    srv._dpyc_sessions.clear()


SAMPLE_NPUB = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"


# ---------------------------------------------------------------------------
# _get_effective_user_id — strict npub mode
# ---------------------------------------------------------------------------


def test_get_effective_user_id_without_dpyc_raises():
    """Without a DPYC session, _get_effective_user_id raises ValueError."""
    import thebrain_mcp.server as srv

    with patch.object(srv, "_require_user_id", return_value="horizon-1"):
        with pytest.raises(ValueError, match="No DPYC identity active"):
            srv._get_effective_user_id()


def test_get_effective_user_id_with_dpyc():
    import thebrain_mcp.server as srv

    srv._dpyc_sessions["horizon-1"] = SAMPLE_NPUB

    with patch.object(srv, "_require_user_id", return_value="horizon-1"):
        eid = srv._get_effective_user_id()

    assert eid == SAMPLE_NPUB


# ---------------------------------------------------------------------------
# session_status — DPYC fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_status_shows_dpyc_npub():
    import thebrain_mcp.server as srv

    srv._dpyc_sessions["horizon-1"] = SAMPLE_NPUB

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"):
        with patch("thebrain_mcp.server.get_session", return_value=None):
            result = await srv.session_status()

    assert result["dpyc_npub"] == SAMPLE_NPUB
    assert result["effective_credit_id"] == SAMPLE_NPUB
    assert "dpyc_warning" not in result


@pytest.mark.asyncio
async def test_session_status_no_dpyc_shows_warning():
    import thebrain_mcp.server as srv

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"):
        with patch("thebrain_mcp.server.get_session", return_value=None):
            result = await srv.session_status()

    assert result["effective_credit_id"] is None
    assert "dpyc_warning" in result
    assert "npub" in result["dpyc_warning"]


@pytest.mark.asyncio
async def test_session_status_not_activated_includes_next_steps():
    """session_status for unactivated user includes Courier next_steps."""
    import thebrain_mcp.server as srv

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"):
        with patch("thebrain_mcp.server.get_session", return_value=None):
            result = await srv.session_status()

    assert result["mode"] == "not activated"
    assert "next_steps" in result
    assert result["next_steps"]["action"] == "secure_courier_onboarding"


# ---------------------------------------------------------------------------
# _on_thebrain_credentials_received callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_activates_session():
    """Callback with valid credentials activates session and DPYC identity."""
    import thebrain_mcp.server as srv

    mock_api = AsyncMock()
    mock_api.get_brain = AsyncMock(return_value={"id": "brain-1"})
    mock_api.close = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.seed_balance_sats = 0

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"), \
         patch("thebrain_mcp.server.TheBrainAPI", return_value=mock_api), \
         patch("thebrain_mcp.server.set_session") as mock_set_session, \
         patch.object(srv, "get_settings", return_value=mock_settings), \
         patch.object(srv, "_seed_balance", new_callable=AsyncMock, return_value=False):
        result = await srv._on_thebrain_credentials_received(
            sender_npub=SAMPLE_NPUB,
            credentials={"api_key": "key-1", "brain_id": "brain-1"},
            service="thebrain",
        )

    assert result["session_activated"] is True
    assert result["dpyc_npub"] == SAMPLE_NPUB
    mock_set_session.assert_called_once_with("horizon-1", "key-1", "brain-1")
    assert srv._dpyc_sessions["horizon-1"] == SAMPLE_NPUB


@pytest.mark.asyncio
async def test_callback_invalid_credentials():
    """Callback with invalid API key returns error."""
    import thebrain_mcp.server as srv

    mock_api = AsyncMock()
    mock_api.get_brain = AsyncMock(side_effect=Exception("401 Unauthorized"))
    mock_api.close = AsyncMock()

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"), \
         patch("thebrain_mcp.server.TheBrainAPI", return_value=mock_api):
        result = await srv._on_thebrain_credentials_received(
            sender_npub=SAMPLE_NPUB,
            credentials={"api_key": "bad-key", "brain_id": "brain-1"},
            service="thebrain",
        )

    assert result["session_activated"] is False
    assert "Invalid" in result["error"]


@pytest.mark.asyncio
async def test_callback_missing_fields():
    """Callback with missing credential fields returns empty dict."""
    import thebrain_mcp.server as srv

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"):
        result = await srv._on_thebrain_credentials_received(
            sender_npub=SAMPLE_NPUB,
            credentials={"api_key": "key-1"},  # missing brain_id
            service="thebrain",
        )

    assert result == {}


# ---------------------------------------------------------------------------
# Paid tools fail without DPYC session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debit_or_error_fails_without_dpyc_session():
    """Paid tools return helpful error when no DPYC session is active."""
    from thebrain_mcp.server import _debit_or_error

    async def _fake_ensure():
        raise ValueError(
            "No DPYC identity active. Credit operations require an npub. "
            "Follow the Secure Courier onboarding flow."
        )

    with patch("thebrain_mcp.server._get_current_user_id", return_value="horizon-1"), \
         patch("thebrain_mcp.server._ensure_dpyc_session", side_effect=_fake_ensure):
        result = await _debit_or_error("search_thoughts")

    assert result is not None
    assert result["success"] is False
    assert "Secure Courier" in result["error"] or "No DPYC identity active" in result["error"]
