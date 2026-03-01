"""Tests for session management (vault.py)."""

import time

import pytest

from thebrain_mcp.vault import (
    UserSession,
    clear_session,
    get_session,
    set_session,
    _sessions,
    SESSION_TTL_SECONDS,
)


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


class TestSessionStore:
    def setup_method(self) -> None:
        _sessions.clear()

    def test_set_and_get(self) -> None:
        session = set_session("user1", "key", "brain")
        assert session.brain_id == "brain"
        assert session.active_brain_id == "brain"
        retrieved = get_session("user1")
        assert retrieved is session

    def test_get_missing(self) -> None:
        assert get_session("nonexistent") is None

    def test_expired_session_returns_none(self) -> None:
        session = set_session("user1", "key", "brain")
        session.created_at = time.time() - SESSION_TTL_SECONDS - 1
        assert get_session("user1") is None
        assert "user1" not in _sessions

    def test_clear_session(self) -> None:
        set_session("user1", "key", "brain")
        clear_session("user1")
        assert get_session("user1") is None

    def test_clear_nonexistent_no_error(self) -> None:
        clear_session("nonexistent")  # should not raise


class TestUserSession:
    def test_repr_redacts_api_key(self) -> None:
        from thebrain_mcp.api.client import TheBrainAPI

        session = UserSession(
            api_key="super-secret-key",
            brain_id="brain-123",
            api_client=TheBrainAPI("super-secret-key"),
        )
        r = repr(session)
        assert "super-secret-key" not in r
        assert "<redacted>" in r
        assert "brain-123" in r

    def test_is_expired(self) -> None:
        from thebrain_mcp.api.client import TheBrainAPI

        session = UserSession(
            api_key="key",
            brain_id="brain",
            api_client=TheBrainAPI("key"),
        )
        assert not session.is_expired
        session.created_at = time.time() - SESSION_TTL_SECONDS - 1
        assert session.is_expired

    def test_age_seconds(self) -> None:
        from thebrain_mcp.api.client import TheBrainAPI

        session = UserSession(
            api_key="key",
            brain_id="brain",
            api_client=TheBrainAPI("key"),
            created_at=time.time() - 42,
        )
        assert 41 <= session.age_seconds <= 43
