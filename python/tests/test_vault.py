"""Tests for credential vault: crypto, session management, and vault class."""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.vault import (
    CredentialNotFoundError,
    CredentialVault,
    DecryptionError,
    UserSession,
    clear_session,
    decrypt_credentials,
    derive_key,
    encrypt_credentials,
    get_session,
    set_session,
    _sessions,
    SESSION_TTL_SECONDS,
)


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------


class TestDeriveKey:
    def test_deterministic(self) -> None:
        salt = b"fixed_salt_16byt"
        k1 = derive_key("passphrase", salt)
        k2 = derive_key("passphrase", salt)
        assert k1 == k2

    def test_different_salt_different_key(self) -> None:
        k1 = derive_key("passphrase", b"salt_aaaaaaa_16b")
        k2 = derive_key("passphrase", b"salt_bbbbbbb_16b")
        assert k1 != k2

    def test_different_passphrase_different_key(self) -> None:
        salt = b"fixed_salt_16byt"
        k1 = derive_key("alpha", salt)
        k2 = derive_key("bravo", salt)
        assert k1 != k2


class TestEncryptDecrypt:
    def test_roundtrip(self) -> None:
        blob = encrypt_credentials("my-api-key", "brain-123", "secret")
        result = decrypt_credentials(blob, "secret")
        assert result == {"api_key": "my-api-key", "brain_id": "brain-123"}

    def test_envelope_structure(self) -> None:
        blob = encrypt_credentials("key", "brain", "pass")
        envelope = json.loads(blob)
        assert envelope["v"] == 2
        assert "salt" in envelope
        assert "data" in envelope

    def test_roundtrip_with_npub(self) -> None:
        blob = encrypt_credentials(
            "my-api-key", "brain-123", "secret",
            npub="npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf",
        )
        result = decrypt_credentials(blob, "secret")
        assert result == {
            "api_key": "my-api-key",
            "brain_id": "brain-123",
            "npub": "npub1l94pd4qu4eszrl6ek032ftcnsu3tt9a7xvq2zp7eaxeklp6mrpzssmq8pf",
        }

    def test_legacy_v1_blob_still_decrypts(self) -> None:
        """v1 blobs (without npub) still decrypt correctly."""
        blob = encrypt_credentials("key", "brain", "pass")
        result = decrypt_credentials(blob, "pass")
        assert "npub" not in result
        assert result["api_key"] == "key"
        assert result["brain_id"] == "brain"

    def test_wrong_passphrase_raises(self) -> None:
        blob = encrypt_credentials("key", "brain", "correct")
        with pytest.raises(DecryptionError, match="Wrong passphrase"):
            decrypt_credentials(blob, "wrong")

    def test_corrupted_json_raises(self) -> None:
        with pytest.raises(DecryptionError, match="invalid JSON"):
            decrypt_credentials("not json at all", "pass")

    def test_missing_fields_raises(self) -> None:
        with pytest.raises(DecryptionError, match="missing fields"):
            decrypt_credentials('{"v": 1}', "pass")

    def test_none_blob_raises(self) -> None:
        with pytest.raises(DecryptionError, match="invalid JSON"):
            decrypt_credentials(None, "pass")  # type: ignore[arg-type]


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


# ---------------------------------------------------------------------------
# CredentialVault (delegates to mock TheBrainVault)
# ---------------------------------------------------------------------------


def _mock_thebrain_vault(
    members: dict[str, str] | None = None,
    note_content: str | None = None,
) -> AsyncMock:
    """Create a mock TheBrainVault for CredentialVault tests.

    ``members``: {user_id: thought_id} that _discover_members returns.
    ``note_content``: what fetch_member_note returns for known members.
    """
    mock_vault = AsyncMock()

    if members is None:
        members = {}

    async def store_member_note(user_id: str, content: str) -> str:
        tid = members.get(user_id, "new-thought-id")
        members[user_id] = tid
        return tid

    async def fetch_member_note(user_id: str) -> str | None:
        if user_id not in members:
            return None
        return note_content

    mock_vault.store_member_note = AsyncMock(side_effect=store_member_note)
    mock_vault.fetch_member_note = AsyncMock(side_effect=fetch_member_note)

    return mock_vault


class TestCredentialVault:
    @pytest.mark.asyncio
    async def test_store_new_user(self) -> None:
        mock_vault = _mock_thebrain_vault(members={})
        vault = CredentialVault(vault=mock_vault)
        tid = await vault.store("user1", "encrypted-blob")
        assert tid == "new-thought-id"
        mock_vault.store_member_note.assert_called_once_with("user1", "encrypted-blob")

    @pytest.mark.asyncio
    async def test_store_existing_user(self) -> None:
        mock_vault = _mock_thebrain_vault(members={"user1": "existing-thought"})
        vault = CredentialVault(vault=mock_vault)
        tid = await vault.store("user1", "new-blob")
        assert tid == "existing-thought"
        mock_vault.store_member_note.assert_called_once_with("user1", "new-blob")

    @pytest.mark.asyncio
    async def test_fetch_success(self) -> None:
        blob = encrypt_credentials("key", "brain", "pass")
        mock_vault = _mock_thebrain_vault(
            members={"user1": "thought-1"},
            note_content=blob,
        )
        vault = CredentialVault(vault=mock_vault)
        result = await vault.fetch("user1")
        assert result == blob

    @pytest.mark.asyncio
    async def test_fetch_user_not_found(self) -> None:
        mock_vault = _mock_thebrain_vault(members={})
        vault = CredentialVault(vault=mock_vault)
        with pytest.raises(CredentialNotFoundError, match="No credentials found"):
            await vault.fetch("unknown-user")

    @pytest.mark.asyncio
    async def test_fetch_empty_note(self) -> None:
        mock_vault = _mock_thebrain_vault(
            members={"user1": "thought-1"},
            note_content="",
        )
        vault = CredentialVault(vault=mock_vault)
        with pytest.raises(CredentialNotFoundError, match="No credentials found"):
            await vault.fetch("user1")

    @pytest.mark.asyncio
    async def test_fetch_none_note(self) -> None:
        """fetch_member_note returns None → CredentialNotFoundError."""
        mock_vault = AsyncMock()
        mock_vault.fetch_member_note = AsyncMock(return_value=None)
        vault = CredentialVault(vault=mock_vault)
        with pytest.raises(CredentialNotFoundError, match="No credentials found"):
            await vault.fetch("user1")
