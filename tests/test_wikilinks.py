"""Tests for wikilink resolution in note-write tools.

Covers GUID<->compact conversion (against known-good vectors), the four token
forms, miss/ambiguous handling, idempotency, code-region skipping, and the
notes-tool wiring that surfaces ``unresolved``.
"""

from unittest.mock import AsyncMock

import pytest

from thebrain_mcp.api.client import TheBrainAPIError
from thebrain_mcp.api.models import Thought
from thebrain_mcp.tools.notes import create_or_update_note_tool
from thebrain_mcp.tools.wikilinks import (
    compact_to_guid,
    guid_to_compact,
    is_compact_id,
    is_guid_or_compact,
    resolve_wikilinks,
)

# Known-good vectors (verified against a live in-plex link).
BRAIN = "50817ae2-2c99-3cb0-ebb8-b7006d2bdef6"
BRAIN_COMPACT = "4nqBUJkssDzruLcAbSve9g"
KYLE_GUID = "655e11c2-15c0-45b3-87be-5e742eb72d14"
KYLE_COMPACT = "whFeZcAVs0WHvl50LrctFA"

KYLE_LINK = f"[Kyle McNamara](brain://api.thebrain.com/{BRAIN_COMPACT}/{KYLE_COMPACT})"


def _thought(id: str, name: str) -> Thought:
    return Thought.model_validate(
        {"id": id, "brainId": BRAIN, "name": name, "kind": 1, "acType": 0}
    )


def _api(by_name=None, by_id=None) -> AsyncMock:
    api = AsyncMock()
    api.get_thoughts_by_name = AsyncMock(return_value=by_name or [])
    api.get_thought = AsyncMock(return_value=by_id)
    return api


# --------------------------------------------------------------------------- #
# GUID <-> compact conversion
# --------------------------------------------------------------------------- #


class TestConversion:
    def test_known_vectors(self):
        assert guid_to_compact(KYLE_GUID) == KYLE_COMPACT
        assert guid_to_compact(BRAIN) == BRAIN_COMPACT

    def test_roundtrip(self):
        for g in (
            KYLE_GUID,
            BRAIN,
            "00000000-0000-0000-0000-000000000000",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "9e115e02-fedb-4254-a1ae-39cce16c63e6",
        ):
            assert compact_to_guid(guid_to_compact(g)) == g

    def test_is_compact_id(self):
        assert is_compact_id(KYLE_COMPACT)
        assert not is_compact_id("Kyle McNamara")
        assert not is_compact_id(KYLE_GUID)  # hyphenated, not compact

    def test_is_guid_or_compact(self):
        assert is_guid_or_compact(KYLE_GUID)
        assert is_guid_or_compact(KYLE_COMPACT)
        assert not is_guid_or_compact("Kyle McNamara")


# --------------------------------------------------------------------------- #
# Token forms
# --------------------------------------------------------------------------- #


class TestTokenForms:
    @pytest.mark.asyncio
    async def test_name(self):
        api = _api(by_name=[_thought(KYLE_GUID, "Kyle McNamara")])
        out, unresolved = await resolve_wikilinks(api, BRAIN, "See [[Kyle McNamara]].")
        assert out == f"See {KYLE_LINK}."
        assert unresolved == []

    @pytest.mark.asyncio
    async def test_name_with_display(self):
        api = _api(by_name=[_thought(KYLE_GUID, "Kyle McNamara")])
        out, unresolved = await resolve_wikilinks(api, BRAIN, "[[Kyle McNamara|Kyle]]")
        assert out == f"[Kyle](brain://api.thebrain.com/{BRAIN_COMPACT}/{KYLE_COMPACT})"
        assert unresolved == []

    @pytest.mark.asyncio
    async def test_hyphenated_id(self):
        api = _api(by_id=_thought(KYLE_GUID, "Kyle McNamara"))
        out, unresolved = await resolve_wikilinks(api, BRAIN, f"[[#{KYLE_GUID}]]")
        assert out == KYLE_LINK
        assert unresolved == []
        api.get_thought.assert_awaited_once_with(BRAIN, KYLE_GUID)
        api.get_thoughts_by_name.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compact_id_normalized_to_guid(self):
        api = _api(by_id=_thought(KYLE_GUID, "Kyle McNamara"))
        out, unresolved = await resolve_wikilinks(api, BRAIN, f"[[#{KYLE_COMPACT}]]")
        assert out == KYLE_LINK
        assert unresolved == []
        # Compact id must be normalized to the hyphenated GUID for the API call.
        api.get_thought.assert_awaited_once_with(BRAIN, KYLE_GUID)

    @pytest.mark.asyncio
    async def test_bare_id_with_display(self):
        api = _api(by_id=_thought(KYLE_GUID, "Kyle McNamara"))
        out, _ = await resolve_wikilinks(api, BRAIN, f"[[{KYLE_GUID}|My Kyle]]")
        assert out == (
            f"[My Kyle](brain://api.thebrain.com/{BRAIN_COMPACT}/{KYLE_COMPACT})"
        )


# --------------------------------------------------------------------------- #
# Misses / ambiguity / failures — token left literal, reported
# --------------------------------------------------------------------------- #


class TestUnresolved:
    @pytest.mark.asyncio
    async def test_not_found(self):
        api = _api(by_name=[])
        out, unresolved = await resolve_wikilinks(api, BRAIN, "x [[Nonexistent]] y")
        assert out == "x [[Nonexistent]] y"
        assert unresolved == [{"token": "[[Nonexistent]]", "reason": "not_found"}]

    @pytest.mark.asyncio
    async def test_case_mismatch_is_not_found(self):
        # Upstream may match case-insensitively; we enforce case-sensitivity.
        api = _api(by_name=[_thought(KYLE_GUID, "kyle mcnamara")])
        out, unresolved = await resolve_wikilinks(api, BRAIN, "[[Kyle McNamara]]")
        assert out == "[[Kyle McNamara]]"
        assert unresolved[0]["reason"] == "not_found"

    @pytest.mark.asyncio
    async def test_ambiguous(self):
        api = _api(
            by_name=[_thought(KYLE_GUID, "Kyle McNamara"), _thought(BRAIN, "Kyle McNamara")]
        )
        out, unresolved = await resolve_wikilinks(api, BRAIN, "[[Kyle McNamara]]")
        assert out == "[[Kyle McNamara]]"
        assert unresolved[0]["reason"] == "ambiguous"
        assert unresolved[0]["candidates"] == [KYLE_GUID, BRAIN]

    @pytest.mark.asyncio
    async def test_id_not_found(self):
        api = _api(by_id=None)
        out, unresolved = await resolve_wikilinks(api, BRAIN, f"[[#{KYLE_GUID}]]")
        assert out == f"[[#{KYLE_GUID}]]"
        assert unresolved[0]["reason"] == "id_not_found"

    @pytest.mark.asyncio
    async def test_lookup_failed_does_not_raise(self):
        api = _api()
        api.get_thoughts_by_name = AsyncMock(side_effect=TheBrainAPIError("500"))
        out, unresolved = await resolve_wikilinks(api, BRAIN, "[[Kyle McNamara]]")
        assert out == "[[Kyle McNamara]]"
        assert unresolved[0]["reason"] == "lookup_failed"

    @pytest.mark.asyncio
    async def test_garbage_id_is_id_not_found(self):
        api = _api()
        out, unresolved = await resolve_wikilinks(api, BRAIN, "[[#not-an-id]]")
        assert out == "[[#not-an-id]]"
        assert unresolved[0]["reason"] == "id_not_found"
        api.get_thought.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_id_lookup_error_does_not_raise(self):
        api = _api()
        api.get_thought = AsyncMock(side_effect=TheBrainAPIError("500"))
        out, unresolved = await resolve_wikilinks(api, BRAIN, f"[[#{KYLE_GUID}]]")
        assert out == f"[[#{KYLE_GUID}]]"
        assert unresolved[0]["reason"] == "id_not_found"


# --------------------------------------------------------------------------- #
# Idempotency and code-region skipping
# --------------------------------------------------------------------------- #


class TestSafety:
    @pytest.mark.asyncio
    async def test_idempotent_on_resolved_links(self):
        api = _api(by_name=[_thought(KYLE_GUID, "Kyle McNamara")])
        body = f"{KYLE_LINK} and [docs](https://example.com/x)"
        out, unresolved = await resolve_wikilinks(api, BRAIN, body)
        assert out == body
        assert unresolved == []
        api.get_thoughts_by_name.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_then_reresolve_is_noop(self):
        api = _api(by_name=[_thought(KYLE_GUID, "Kyle McNamara")])
        once, _ = await resolve_wikilinks(api, BRAIN, "ref [[Kyle McNamara]] end")
        twice, unresolved = await resolve_wikilinks(api, BRAIN, once)
        assert twice == once
        assert unresolved == []

    @pytest.mark.asyncio
    async def test_code_regions_untouched(self):
        api = _api(by_name=[_thought(KYLE_GUID, "Kyle McNamara")])
        body = (
            "Inline `[[Kyle McNamara]]` stays.\n"
            "```\n[[Kyle McNamara]]\n```\n"
            "But [[Kyle McNamara]] resolves."
        )
        out, unresolved = await resolve_wikilinks(api, BRAIN, body)
        assert "`[[Kyle McNamara]]`" in out
        assert "```\n[[Kyle McNamara]]\n```" in out
        assert f"But {KYLE_LINK} resolves." in out
        assert unresolved == []


# --------------------------------------------------------------------------- #
# Notes-tool wiring
# --------------------------------------------------------------------------- #


class TestNotesWiring:
    @pytest.mark.asyncio
    async def test_create_persists_resolved_and_surfaces_unresolved(self):
        api = _api(by_name=[])  # nothing resolves
        api.create_or_update_note = AsyncMock(return_value={})
        result = await create_or_update_note_tool(
            api, BRAIN, "thought-1", "See [[Ghost]]."
        )
        assert result["success"] is True
        assert result["unresolved"] == [{"token": "[[Ghost]]", "reason": "not_found"}]
        # The literal (unresolved) markdown is what gets persisted.
        api.create_or_update_note.assert_awaited_once_with(BRAIN, "thought-1", "See [[Ghost]].")

    @pytest.mark.asyncio
    async def test_create_no_unresolved_key_when_all_resolve(self):
        api = _api(by_name=[_thought(KYLE_GUID, "Kyle McNamara")])
        api.create_or_update_note = AsyncMock(return_value={})
        result = await create_or_update_note_tool(
            api, BRAIN, "thought-1", "[[Kyle McNamara]]"
        )
        assert result["success"] is True
        assert "unresolved" not in result
        api.create_or_update_note.assert_awaited_once_with(BRAIN, "thought-1", KYLE_LINK)
