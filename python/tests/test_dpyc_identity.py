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


@pytest.mark.asyncio
async def test_activate_dpyc_valid_npub():
    import thebrain_mcp.server as srv

    npub = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"
    with patch.object(srv, "_require_user_id", return_value="horizon-1"):
        result = await srv.activate_dpyc.fn(npub)

    assert result["success"] is True
    assert result["horizon_id"] == "horizon-1"
    assert result["effective_id"] == npub


@pytest.mark.asyncio
async def test_activate_dpyc_invalid_format():
    import thebrain_mcp.server as srv

    with patch.object(srv, "_require_user_id", return_value="horizon-1"):
        result = await srv.activate_dpyc.fn("not-an-npub")

    assert result["success"] is False
    assert "Invalid npub" in result["error"]


@pytest.mark.asyncio
async def test_get_dpyc_identity_without_session():
    import thebrain_mcp.server as srv
    from thebrain_mcp.config import Settings

    mock_settings = MagicMock(spec=Settings)
    mock_settings.dpyc_operator_npub = "npub1operator"
    mock_settings.dpyc_authority_npub = "npub1authority"

    with (
        patch.object(srv, "_require_user_id", return_value="horizon-1"),
        patch("thebrain_mcp.server.get_settings", return_value=mock_settings),
    ):
        result = await srv.get_dpyc_identity.fn()

    assert result["horizon_id"] == "horizon-1"
    assert result["dpyc_npub"] is None
    assert result["effective_id"] == "horizon-1"
    assert result["operator_npub"] == "npub1operator"
    assert result["authority_npub"] == "npub1authority"


@pytest.mark.asyncio
async def test_get_dpyc_identity_with_session():
    import thebrain_mcp.server as srv
    from thebrain_mcp.config import Settings

    npub = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"
    srv._dpyc_sessions["horizon-1"] = npub

    mock_settings = MagicMock(spec=Settings)
    mock_settings.dpyc_operator_npub = None
    mock_settings.dpyc_authority_npub = None

    with (
        patch.object(srv, "_require_user_id", return_value="horizon-1"),
        patch("thebrain_mcp.server.get_settings", return_value=mock_settings),
    ):
        result = await srv.get_dpyc_identity.fn()

    assert result["dpyc_npub"] == npub
    assert result["effective_id"] == npub


def test_get_effective_user_id_without_dpyc():
    import thebrain_mcp.server as srv

    with patch.object(srv, "_require_user_id", return_value="horizon-1"):
        eid = srv._get_effective_user_id()

    assert eid == "horizon-1"


def test_get_effective_user_id_with_dpyc():
    import thebrain_mcp.server as srv

    npub = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"
    srv._dpyc_sessions["horizon-1"] = npub

    with patch.object(srv, "_require_user_id", return_value="horizon-1"):
        eid = srv._get_effective_user_id()

    assert eid == npub


@pytest.mark.asyncio
async def test_session_status_shows_dpyc_npub():
    import thebrain_mcp.server as srv

    npub = "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf"
    srv._dpyc_sessions["horizon-1"] = npub

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"):
        with patch("thebrain_mcp.server.get_session", return_value=None):
            result = await srv.session_status.fn()

    assert result["dpyc_npub"] == npub
    assert result["effective_credit_id"] == npub


@pytest.mark.asyncio
async def test_session_status_no_dpyc():
    import thebrain_mcp.server as srv

    with patch.object(srv, "_get_current_user_id", return_value="horizon-1"):
        with patch("thebrain_mcp.server.get_session", return_value=None):
            result = await srv.session_status.fn()

    assert "dpyc_npub" not in result
    assert result["effective_credit_id"] == "horizon-1"
