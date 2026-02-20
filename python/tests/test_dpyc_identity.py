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
# activate_dpyc (deprecated stub)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_dpyc_returns_deprecation_error():
    import thebrain_mcp.server as srv

    result = await srv.activate_dpyc(SAMPLE_NPUB)

    assert result["success"] is False
    assert "deprecated" in result["error"].lower()
    assert "register_credentials" in result["error"]


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


# ---------------------------------------------------------------------------
# register_credentials — npub integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_credentials_with_npub():
    """register_credentials stores npub and auto-activates DPYC session."""
    import thebrain_mcp.server as srv

    mock_api = AsyncMock()
    mock_api.get_brain = AsyncMock(return_value={"id": "brain-1"})
    mock_api.close = AsyncMock()

    mock_vault = AsyncMock()
    mock_vault.store = AsyncMock(return_value="thought-123")

    mock_settings = MagicMock()
    mock_settings.seed_balance_sats = 0

    with patch.object(srv, "_require_user_id", return_value="horizon-1"), \
         patch.object(srv, "_get_vault", return_value=mock_vault), \
         patch.object(srv, "get_settings", return_value=mock_settings), \
         patch("thebrain_mcp.server.TheBrainAPI", return_value=mock_api), \
         patch("thebrain_mcp.server.encrypt_credentials", return_value="encrypted") as mock_encrypt, \
         patch("thebrain_mcp.server.set_session"):
        result = await srv.register_credentials(
            thebrain_api_key="key-1", brain_id="brain-1",
            passphrase="pass", npub=SAMPLE_NPUB,
        )

    assert result["success"] is True
    assert result["dpyc_npub"] == SAMPLE_NPUB
    # Verify npub was passed to encrypt_credentials
    mock_encrypt.assert_called_once_with("key-1", "brain-1", "pass", npub=SAMPLE_NPUB)
    # Verify DPYC session auto-activated
    assert srv._dpyc_sessions["horizon-1"] == SAMPLE_NPUB


@pytest.mark.asyncio
async def test_register_credentials_without_npub_fails():
    """register_credentials rejects calls without a valid npub."""
    import thebrain_mcp.server as srv

    result = await srv.register_credentials(
        thebrain_api_key="key-1", brain_id="brain-1",
        passphrase="pass", npub="not-an-npub",
    )

    assert result["success"] is False
    assert "Invalid npub" in result["error"]
    assert "dpyc-oracle" in result["error"]


# ---------------------------------------------------------------------------
# activate_session — npub auto-activation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_session_with_npub_in_vault():
    """activate_session auto-activates DPYC when vault blob contains npub."""
    import thebrain_mcp.server as srv

    mock_vault = AsyncMock()
    mock_vault.fetch = AsyncMock(return_value="encrypted-blob")

    with patch.object(srv, "_require_user_id", return_value="horizon-1"), \
         patch.object(srv, "_get_vault", return_value=mock_vault), \
         patch("thebrain_mcp.server.decrypt_credentials", return_value={
             "api_key": "key-1", "brain_id": "brain-1", "npub": SAMPLE_NPUB,
         }), \
         patch("thebrain_mcp.server.set_session"):
        result = await srv.activate_session(passphrase="pass")

    assert result["success"] is True
    assert result["dpyc_npub"] == SAMPLE_NPUB
    assert "dpyc_warning" not in result
    assert srv._dpyc_sessions["horizon-1"] == SAMPLE_NPUB


@pytest.mark.asyncio
async def test_activate_session_legacy_blob_warns():
    """activate_session with a legacy blob (no npub) warns about re-registration."""
    import thebrain_mcp.server as srv

    mock_vault = AsyncMock()
    mock_vault.fetch = AsyncMock(return_value="encrypted-blob")

    with patch.object(srv, "_require_user_id", return_value="horizon-1"), \
         patch.object(srv, "_get_vault", return_value=mock_vault), \
         patch("thebrain_mcp.server.decrypt_credentials", return_value={
             "api_key": "key-1", "brain_id": "brain-1",
         }), \
         patch("thebrain_mcp.server.set_session"):
        result = await srv.activate_session(passphrase="pass")

    assert result["success"] is True
    assert "dpyc_npub" not in result
    assert "dpyc_warning" in result
    assert "upgrade_credentials" in result["dpyc_warning"]
    assert "horizon-1" not in srv._dpyc_sessions


# ---------------------------------------------------------------------------
# upgrade_credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upgrade_credentials_adds_npub():
    """Active session + valid npub → vault updated, DPYC activated."""
    import thebrain_mcp.server as srv
    from thebrain_mcp.vault import UserSession

    mock_session = MagicMock(spec=UserSession)
    mock_session.api_key = "key-1"
    mock_session.brain_id = "brain-1"

    mock_vault = AsyncMock()
    mock_vault.store = AsyncMock(return_value="thought-123")

    mock_settings = MagicMock()
    mock_settings.seed_balance_sats = 0

    with patch.object(srv, "_require_user_id", return_value="horizon-1"), \
         patch("thebrain_mcp.server.get_session", return_value=mock_session), \
         patch.object(srv, "_get_vault", return_value=mock_vault), \
         patch.object(srv, "get_settings", return_value=mock_settings), \
         patch("thebrain_mcp.server.encrypt_credentials", return_value="encrypted-v2") as mock_encrypt:
        result = await srv.upgrade_credentials(passphrase="pass", npub=SAMPLE_NPUB)

    assert result["success"] is True
    assert result["dpyc_npub"] == SAMPLE_NPUB
    assert result["brainId"] == "brain-1"
    assert "upgraded" in result["message"].lower() or "upgrade" in result["message"].lower()
    # Verify re-encryption with npub
    mock_encrypt.assert_called_once_with("key-1", "brain-1", "pass", npub=SAMPLE_NPUB)
    # Verify vault store called
    mock_vault.store.assert_called_once_with("horizon-1", "encrypted-v2")
    # Verify DPYC session activated
    assert srv._dpyc_sessions["horizon-1"] == SAMPLE_NPUB


@pytest.mark.asyncio
async def test_upgrade_credentials_no_session_fails():
    """No active session → helpful error telling user to activate first."""
    import thebrain_mcp.server as srv

    with patch.object(srv, "_require_user_id", return_value="horizon-1"), \
         patch("thebrain_mcp.server.get_session", return_value=None):
        result = await srv.upgrade_credentials(passphrase="pass", npub=SAMPLE_NPUB)

    assert result["success"] is False
    assert "activate_session" in result["error"]


@pytest.mark.asyncio
async def test_upgrade_credentials_invalid_npub_fails():
    """Bad npub format → error with guidance."""
    import thebrain_mcp.server as srv

    result = await srv.upgrade_credentials(passphrase="pass", npub="not-an-npub")

    assert result["success"] is False
    assert "Invalid npub" in result["error"]
    assert "dpyc-oracle" in result["error"]


# ---------------------------------------------------------------------------
# Paid tools fail without DPYC session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debit_or_error_fails_without_dpyc_session():
    """Paid tools return helpful error when no DPYC session is active."""
    from thebrain_mcp.server import _debit_or_error

    with patch("thebrain_mcp.server._get_current_user_id", return_value="horizon-1"):
        result = await _debit_or_error("search_thoughts")

    assert result is not None
    assert result["success"] is False
    assert "No DPYC identity active" in result["error"]
    assert "register_credentials" in result["error"]
