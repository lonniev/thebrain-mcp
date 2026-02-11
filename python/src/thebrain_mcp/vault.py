"""Multi-tenant credential vault for TheBrain MCP server.

Handles encryption/decryption of user credentials, vault brain CRUD,
and in-memory session management.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError

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


def encrypt_credentials(api_key: str, brain_id: str, passphrase: str) -> str:
    """Encrypt credentials into a JSON envelope with embedded salt.

    Returns a JSON string: {"v": 1, "salt": "<base64>", "data": "<fernet token>"}.
    """
    salt = os.urandom(16)
    key = derive_key(passphrase, salt)
    f = Fernet(key)

    payload = json.dumps({"api_key": api_key, "brain_id": brain_id}).encode("utf-8")
    ciphertext = f.encrypt(payload)

    return json.dumps({
        "v": 1,
        "salt": base64.b64encode(salt).decode("ascii"),
        "data": ciphertext.decode("ascii"),
    })


def decrypt_credentials(blob: str, passphrase: str) -> dict[str, str]:
    """Decrypt a credential blob. Returns {"api_key": ..., "brain_id": ...}.

    Raises cryptography.fernet.InvalidToken on wrong passphrase.
    """
    envelope = json.loads(blob)
    salt = base64.b64decode(envelope["salt"])
    key = derive_key(passphrase, salt)
    f = Fernet(key)

    plaintext = f.decrypt(envelope["data"].encode("ascii"))
    return json.loads(plaintext)


# ---------------------------------------------------------------------------
# Vault brain CRUD (index-based lookup)
# ---------------------------------------------------------------------------


async def _read_index(
    vault_api: TheBrainAPI,
    vault_brain_id: str,
    home_thought_id: str,
) -> dict[str, str]:
    """Read the user_id → thought_id index from the vault home thought's note."""
    try:
        note = await vault_api.get_note(vault_brain_id, home_thought_id, "markdown")
        if note.markdown:
            return json.loads(note.markdown)
    except (TheBrainAPIError, json.JSONDecodeError):
        pass
    return {}


async def _write_index(
    vault_api: TheBrainAPI,
    vault_brain_id: str,
    home_thought_id: str,
    index: dict[str, str],
) -> None:
    """Write the user_id → thought_id index to the vault home thought's note."""
    await vault_api.create_or_update_note(
        vault_brain_id, home_thought_id, json.dumps(index)
    )


async def store_credential(
    vault_api: TheBrainAPI,
    vault_brain_id: str,
    home_thought_id: str,
    user_id: str,
    encrypted_blob: str,
) -> str:
    """Store an encrypted credential blob for a user.

    Creates a thought (or reuses existing) and writes the blob as its note.
    Updates the index on the home thought. Returns the thought ID.
    """
    index = await _read_index(vault_api, vault_brain_id, home_thought_id)
    thought_id = index.get(user_id)

    if thought_id:
        # Overwrite existing note
        await vault_api.create_or_update_note(vault_brain_id, thought_id, encrypted_blob)
    else:
        # Create new thought as child of home
        result = await vault_api.create_thought(vault_brain_id, {
            "name": user_id,
            "kind": 1,
            "acType": 1,  # Private
            "sourceThoughtId": home_thought_id,
            "relation": 1,  # Child
        })
        thought_id = result["id"]
        await vault_api.create_or_update_note(vault_brain_id, thought_id, encrypted_blob)

        # Update index
        index[user_id] = thought_id
        await _write_index(vault_api, vault_brain_id, home_thought_id, index)

    return thought_id


async def fetch_credential_blob(
    vault_api: TheBrainAPI,
    vault_brain_id: str,
    home_thought_id: str,
    user_id: str,
) -> str | None:
    """Fetch the encrypted credential blob for a user. Returns None if not found."""
    index = await _read_index(vault_api, vault_brain_id, home_thought_id)
    thought_id = index.get(user_id)
    if not thought_id:
        return None

    try:
        note = await vault_api.get_note(vault_brain_id, thought_id, "markdown")
        return note.markdown
    except TheBrainAPIError:
        return None


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


_sessions: dict[str, UserSession] = {}


def get_session(user_id: str) -> UserSession | None:
    """Get active session, returning None if expired or absent."""
    session = _sessions.get(user_id)
    if session and (time.time() - session.created_at) > SESSION_TTL_SECONDS:
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
