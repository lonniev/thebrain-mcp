"""Tests for UUID validation in TheBrain API client."""

import pytest

from thebrain_mcp.api.client import TheBrainAPI, _validate_uuid


VALID_UUID = "9e115e02-fedb-4254-a1ae-39cce16c63e6"
VALID_UUID_UPPER = "9E115E02-FEDB-4254-A1AE-39CCE16C63E6"


# ---------------------------------------------------------------------------
# Unit tests for _validate_uuid helper
# ---------------------------------------------------------------------------


class TestValidateUuid:
    def test_valid_uuid_passes(self):
        assert _validate_uuid(VALID_UUID, "test_param") == VALID_UUID

    def test_uppercase_uuid_passes(self):
        assert _validate_uuid(VALID_UUID_UPPER, "test_param") == VALID_UUID_UPPER

    def test_short_prefix_rejected(self):
        with pytest.raises(ValueError, match="not a valid UUID"):
            _validate_uuid("9e115e02", "brain_id")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="not a valid UUID"):
            _validate_uuid("../../admin", "brain_id")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="not a valid UUID"):
            _validate_uuid("", "brain_id")

    def test_spaces_rejected(self):
        with pytest.raises(ValueError, match="not a valid UUID"):
            _validate_uuid("not a uuid", "thought_id")

    def test_uuid_without_hyphens_rejected(self):
        with pytest.raises(ValueError, match="not a valid UUID"):
            _validate_uuid("9e115e02fedb4254a1ae39cce16c63e6", "brain_id")

    def test_error_message_includes_param_name(self):
        with pytest.raises(ValueError, match="Invalid brain_id"):
            _validate_uuid("bad", "brain_id")

    def test_error_message_includes_value(self):
        with pytest.raises(ValueError, match="'badvalue'"):
            _validate_uuid("badvalue", "test")


# ---------------------------------------------------------------------------
# Integration tests: validation fires before HTTP
# ---------------------------------------------------------------------------


class TestApiMethodValidation:
    """Verify that API methods reject bad IDs before making HTTP requests."""

    @pytest.fixture
    def api(self):
        return TheBrainAPI(api_key="test-key")

    @pytest.mark.asyncio
    async def test_get_thought_validates_brain_id(self, api):
        with pytest.raises(ValueError, match="brain_id"):
            await api.get_thought("bad", VALID_UUID)

    @pytest.mark.asyncio
    async def test_get_thought_validates_thought_id(self, api):
        with pytest.raises(ValueError, match="thought_id"):
            await api.get_thought(VALID_UUID, "also-bad")

    @pytest.mark.asyncio
    async def test_create_thought_validates_brain_id(self, api):
        with pytest.raises(ValueError, match="brain_id"):
            await api.create_thought("bad", {"name": "test"})

    @pytest.mark.asyncio
    async def test_get_link_validates_link_id(self, api):
        with pytest.raises(ValueError, match="link_id"):
            await api.get_link(VALID_UUID, "bad-link")

    @pytest.mark.asyncio
    async def test_get_attachment_validates_attachment_id(self, api):
        with pytest.raises(ValueError, match="attachment_id"):
            await api.get_attachment(VALID_UUID, "bad-attachment")

    @pytest.mark.asyncio
    async def test_get_note_validates_thought_id(self, api):
        with pytest.raises(ValueError, match="thought_id"):
            await api.get_note(VALID_UUID, "bad-thought")

    @pytest.mark.asyncio
    async def test_search_thoughts_validates_brain_id(self, api):
        with pytest.raises(ValueError, match="brain_id"):
            await api.search_thoughts("bad", "query")

    @pytest.mark.asyncio
    async def test_delete_link_validates_both_ids(self, api):
        with pytest.raises(ValueError, match="brain_id"):
            await api.delete_link("bad", VALID_UUID)
        with pytest.raises(ValueError, match="link_id"):
            await api.delete_link(VALID_UUID, "bad")
