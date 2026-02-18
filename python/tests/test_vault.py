"""Tests for credential vault: crypto, session management, and vault class."""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.vault import (
    CredentialNotFoundError,
    CredentialVault,
    DecryptionError,
    PersonalBrainVault,
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
        assert envelope["v"] == 1
        assert "salt" in envelope
        assert "data" in envelope

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
# CredentialVault
# ---------------------------------------------------------------------------


def _mock_vault_api(index: dict[str, str] | None = None, note_content: str | None = None):
    """Create a mock TheBrainAPI for vault operations."""
    api = AsyncMock()

    # Mock get_note for index reads
    index_note = MagicMock()
    index_note.markdown = json.dumps(index) if index else None
    api.get_note = AsyncMock(return_value=index_note)

    # For fetch, we need different responses for index vs credential notes.
    # We'll set this up per-test as needed.
    if note_content is not None:
        cred_note = MagicMock()
        cred_note.markdown = note_content

        async def get_note_side_effect(brain_id, thought_id, fmt):
            if thought_id == "home":
                return index_note
            return cred_note

        api.get_note = AsyncMock(side_effect=get_note_side_effect)

    api.create_or_update_note = AsyncMock()
    api.create_thought = AsyncMock(return_value={"id": "new-thought-id"})
    return api


class TestCredentialVault:
    @pytest.mark.asyncio
    async def test_store_new_user(self) -> None:
        api = _mock_vault_api(index={})
        vault = CredentialVault(api, "vault-brain", "home")
        tid = await vault.store("user1", "encrypted-blob")
        assert tid == "new-thought-id"
        api.create_thought.assert_called_once()
        assert api.create_or_update_note.call_count == 2  # blob + index

    @pytest.mark.asyncio
    async def test_store_existing_user(self) -> None:
        api = _mock_vault_api(index={"user1": "existing-thought"})
        vault = CredentialVault(api, "vault-brain", "home")
        tid = await vault.store("user1", "new-blob")
        assert tid == "existing-thought"
        api.create_thought.assert_not_called()
        api.create_or_update_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_success(self) -> None:
        blob = encrypt_credentials("key", "brain", "pass")
        api = _mock_vault_api(
            index={"user1": "thought-1"},
            note_content=blob,
        )
        vault = CredentialVault(api, "vault-brain", "home")
        result = await vault.fetch("user1")
        assert result == blob

    @pytest.mark.asyncio
    async def test_fetch_user_not_in_index(self) -> None:
        api = _mock_vault_api(index={})
        vault = CredentialVault(api, "vault-brain", "home")
        with pytest.raises(CredentialNotFoundError, match="No credentials found"):
            await vault.fetch("unknown-user")

    @pytest.mark.asyncio
    async def test_snapshot_ledger_creates_child(self) -> None:
        api = _mock_vault_api(index={"user1/ledger": "ledger-thought-1"})
        vault = PersonalBrainVault(api, "vault-brain", "home")
        snapshot_id = await vault.snapshot_ledger(
            "user1", '{"balance_api_sats": 500}', "2026-02-16T12:00:00Z"
        )
        assert snapshot_id == "new-thought-id"
        api.create_thought.assert_called_once()
        call_args = api.create_thought.call_args[0]
        assert call_args[1]["name"] == "2026-02-16T12:00:00Z"
        assert call_args[1]["sourceThoughtId"] == "ledger-thought-1"
        assert call_args[1]["relation"] == 1  # Child
        api.create_or_update_note.assert_called()

    @pytest.mark.asyncio
    async def test_snapshot_ledger_no_ledger_returns_none(self) -> None:
        api = _mock_vault_api(index={})
        vault = PersonalBrainVault(api, "vault-brain", "home")
        result = await vault.snapshot_ledger(
            "user1", '{"balance_api_sats": 0}', "2026-02-16T12:00:00Z"
        )
        assert result is None
        api.create_thought.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_empty_note(self) -> None:
        api = _mock_vault_api(
            index={"user1": "thought-1"},
            note_content="",
        )
        # Override to return empty markdown
        cred_note = MagicMock()
        cred_note.markdown = ""
        index_note = MagicMock()
        index_note.markdown = json.dumps({"user1": "thought-1"})

        async def get_note_side_effect(brain_id, thought_id, fmt):
            if thought_id == "home":
                return index_note
            return cred_note

        api.get_note = AsyncMock(side_effect=get_note_side_effect)
        vault = CredentialVault(api, "vault-brain", "home")
        with pytest.raises(CredentialNotFoundError, match="empty"):
            await vault.fetch("user1")
