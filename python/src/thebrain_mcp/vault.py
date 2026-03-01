"""In-memory session management for TheBrain MCP server.

Handles per-user sessions with TTL expiry. Credential persistence is
delegated to NeonCredentialVault (via Secure Courier), not stored here.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from thebrain_mcp.api.client import TheBrainAPI  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VaultError(Exception):
    """Base exception for vault operations."""


class VaultNotConfiguredError(VaultError):
    """Raised when the vault backend is not configured by the operator."""


class CredentialNotFoundError(VaultError):
    """Raised when no credentials are stored for a user."""


class DecryptionError(VaultError):
    """Raised when credential decryption fails."""


class CredentialValidationError(VaultError):
    """Raised when provided credentials fail validation against TheBrain API."""


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

SESSION_TTL_SECONDS = 3600  # 1 hour, matching JWT TTL


@dataclass
class UserSession:
    """Per-user session holding decrypted credentials."""

    api_key: str
    brain_id: str
    api_client: TheBrainAPI
    created_at: float = field(default_factory=time.time)
    active_brain_id: str | None = None

    def __repr__(self) -> str:
        age = int(time.time() - self.created_at)
        return (
            f"UserSession(brain_id={self.brain_id!r}, "
            f"active_brain_id={self.active_brain_id!r}, "
            f"age={age}s, api_key=<redacted>)"
        )

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > SESSION_TTL_SECONDS

    @property
    def age_seconds(self) -> int:
        return int(time.time() - self.created_at)


_sessions: dict[str, UserSession] = {}


def get_session(user_id: str) -> UserSession | None:
    """Get active session, returning None if expired or absent."""
    session = _sessions.get(user_id)
    if session and session.is_expired:
        del _sessions[user_id]
        return None
    return session


def set_session(user_id: str, api_key: str, brain_id: str) -> UserSession:
    """Create or replace a session with a new TheBrainAPI client."""
    client = TheBrainAPI(api_key)
    session = UserSession(
        api_key=api_key,
        brain_id=brain_id,
        api_client=client,
        active_brain_id=brain_id,
    )
    _sessions[user_id] = session
    return session


def clear_session(user_id: str) -> None:
    """Remove a session."""
    _sessions.pop(user_id, None)
