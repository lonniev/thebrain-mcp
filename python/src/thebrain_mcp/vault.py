"""Multi-tenant credential vault for TheBrain MCP server.

Handles encryption/decryption of user credentials, vault brain CRUD,
and in-memory session management.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VaultError(Exception):
    """Base exception for vault operations."""


class VaultNotConfiguredError(VaultError):
    """Raised when the vault brain is not configured by the operator."""


class CredentialNotFoundError(VaultError):
    """Raised when no credentials are stored for a user."""


class DecryptionError(VaultError):
    """Raised when credential decryption fails (wrong passphrase or corrupted blob)."""


class CredentialValidationError(VaultError):
    """Raised when provided credentials fail validation against TheBrain API."""


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 600_000  # OWASP 2023 recommendation


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet key from passphrase + salt using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt_credentials(
    api_key: str, brain_id: str, passphrase: str, *, npub: str | None = None
) -> str:
    """Encrypt credentials into a JSON envelope with embedded salt.

    Returns a JSON string: {"v": 2, "salt": "<base64>", "data": "<fernet token>"}.
    v2 blobs include the optional npub field. v1 blobs (without npub) are
    still readable by decrypt_credentials — they just won't have an "npub" key.
    """
    salt = os.urandom(16)
    key = derive_key(passphrase, salt)
    f = Fernet(key)

    payload_dict: dict[str, str] = {"api_key": api_key, "brain_id": brain_id}
    if npub:
        payload_dict["npub"] = npub
    payload = json.dumps(payload_dict).encode("utf-8")
    ciphertext = f.encrypt(payload)

    return json.dumps({
        "v": 2,
        "salt": base64.b64encode(salt).decode("ascii"),
        "data": ciphertext.decode("ascii"),
    })


def decrypt_credentials(blob: str, passphrase: str) -> dict[str, str]:
    """Decrypt a credential blob. Returns {"api_key": ..., "brain_id": ...}.

    Raises DecryptionError on wrong passphrase or corrupted data.
    """
    try:
        envelope = json.loads(blob)
    except (json.JSONDecodeError, TypeError) as e:
        raise DecryptionError("Credential blob is corrupted (invalid JSON).") from e

    if "salt" not in envelope or "data" not in envelope:
        raise DecryptionError("Credential blob is corrupted (missing fields).")

    try:
        salt = base64.b64decode(envelope["salt"])
        key = derive_key(passphrase, salt)
        f = Fernet(key)
        plaintext = f.decrypt(envelope["data"].encode("ascii"))
        return json.loads(plaintext)
    except InvalidToken:
        raise DecryptionError("Wrong passphrase.")
    except Exception as e:
        raise DecryptionError("Credential blob is corrupted.") from e


# ---------------------------------------------------------------------------
# Credential vault (encapsulates vault brain access)
# ---------------------------------------------------------------------------


class CredentialVault:
    """Manages encrypted credential storage in a TheBrain vault brain.

    The vault stores each user's encrypted credentials as a note on a
    private thought, with a JSON index on the home thought mapping
    user IDs to thought IDs.
    """

    def __init__(
        self,
        vault_api: TheBrainAPI,
        vault_brain_id: str,
        home_thought_id: str,
    ) -> None:
        self._api = vault_api
        self._brain_id = vault_brain_id
        self._home_thought_id = home_thought_id

    async def _read_index(self) -> dict[str, str]:
        """Read the user_id -> thought_id index from the vault home thought."""
        try:
            note = await self._api.get_note(
                self._brain_id, self._home_thought_id, "markdown"
            )
            if note.markdown:
                return json.loads(note.markdown)
        except TheBrainAPIError:
            logger.warning("Failed to read vault index from home thought.")
        except json.JSONDecodeError:
            logger.warning("Vault index is corrupted (invalid JSON).")
        return {}

    async def _write_index(self, index: dict[str, str]) -> None:
        """Write the user_id -> thought_id index to the vault home thought."""
        await self._api.create_or_update_note(
            self._brain_id, self._home_thought_id, json.dumps(index)
        )

    async def store(self, user_id: str, encrypted_blob: str) -> str:
        """Store an encrypted credential blob for a user.

        Creates a thought (or reuses existing) and writes the blob as its note.
        Returns the thought ID where credentials are stored.
        """
        index = await self._read_index()
        thought_id = index.get(user_id)

        if thought_id:
            await self._api.create_or_update_note(
                self._brain_id, thought_id, encrypted_blob
            )
        else:
            result = await self._api.create_thought(self._brain_id, {
                "name": user_id,
                "kind": 1,
                "acType": 1,  # Private
                "sourceThoughtId": self._home_thought_id,
                "relation": 1,  # Child
            })
            thought_id = result["id"]
            await self._api.create_or_update_note(
                self._brain_id, thought_id, encrypted_blob
            )
            index[user_id] = thought_id
            await self._write_index(index)

        return thought_id

    async def fetch(self, user_id: str) -> str:
        """Fetch the encrypted credential blob for a user.

        Raises CredentialNotFoundError if no credentials are stored.
        """
        index = await self._read_index()
        thought_id = index.get(user_id)
        if not thought_id:
            raise CredentialNotFoundError(
                "No credentials found. Use register_credentials first."
            )

        try:
            note = await self._api.get_note(self._brain_id, thought_id, "markdown")
        except TheBrainAPIError as e:
            raise CredentialNotFoundError(
                "Credential storage exists but could not be read."
            ) from e

        if not note.markdown:
            raise CredentialNotFoundError(
                "Credential storage is empty. Re-register with register_credentials."
            )

        return note.markdown

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
