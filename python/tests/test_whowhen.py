"""Tests for the whowhen tool (event_for_person)."""

from unittest.mock import AsyncMock

import pytest

from thebrain_mcp.api.client import TheBrainAPIError
from thebrain_mcp.api.models import Brain, SearchResult, Thought
from thebrain_mcp.tools.whowhen import (
    _find_person_type_id,
    _parse_date,
    _resolve_day,
    _resolve_person,
    event_for_person_tool,
)
from thebrain_mcp.utils.constants import RelationType, ThoughtKind

BRAIN = "brain-00000000-0000-0000-0000-000000000000"
HOME = "home-00000000-0000-0000-0000-000000000000"
PERSON_TYPE = "ptype-0000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _thought(id: str, name: str, type_id: str | None = None, kind: int = 1) -> Thought:
    return Thought.model_validate({
        "id": id, "brainId": BRAIN, "name": name, "kind": kind, "acType": 0,
        "typeId": type_id,
    })


def _search_result(thought: Thought) -> SearchResult:
    return SearchResult.model_validate({
        "searchResultType": 1,
        "sourceThought": {
            "id": thought.id, "brainId": thought.brain_id,
            "name": thought.name, "kind": thought.kind, "acType": thought.ac_type,
            "typeId": thought.type_id,
        },
    })


def _brain() -> Brain:
    return Brain.model_validate({
        "id": BRAIN, "name": "Test Brain", "homeThoughtId": HOME,
    })


def _mock_api() -> AsyncMock:
    api = AsyncMock()
    api.get_brain = AsyncMock(return_value=_brain())
    api.get_types = AsyncMock(return_value=[
        _thought(PERSON_TYPE, "Person", kind=2),
        _thought("org-type", "Organization", kind=2),
    ])
    api.get_thought_by_name = AsyncMock(return_value=None)
    api.search_thoughts = AsyncMock(return_value=[])
    api.create_thought = AsyncMock(return_value={"id": "new-thought-id"})
    api.create_link = AsyncMock(return_value={"id": "new-link-id"})
    api.create_or_update_note = AsyncMock(return_value={})
    return api


# ---------------------------------------------------------------------------
# TestDateParsing
# ---------------------------------------------------------------------------


class TestDateParsing:
    def test_iso_date(self):
        year, month, day = _parse_date("2026-03-01")
        assert year == 2026
        assert month == "March"
        assert day == 1

    def test_natural_language(self):
        year, month, day = _parse_date("February 24, 2026")
        assert year == 2026
        assert month == "February"
        assert day == 24

    def test_short_format(self):
        year, month, day = _parse_date("Jan 5 2025")
        assert year == 2025
        assert month == "January"
        assert day == 5

    def test_invalid_date(self):
        with pytest.raises(ValueError):
            _parse_date("not a date at all xyzzy")


# ---------------------------------------------------------------------------
# TestPersonResolution
# ---------------------------------------------------------------------------


class TestPersonResolution:
    @pytest.mark.asyncio
    async def test_uuid_lookup(self):
        api = _mock_api()
        uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        api.get_thought = AsyncMock(return_value=_thought(uuid, "Sarah Smith"))

        pid, pname, created = await _resolve_person(api, BRAIN, uuid, PERSON_TYPE, HOME)

        assert pid == uuid
        assert pname == "Sarah Smith"
        assert created is False
        api.get_thought.assert_called_once_with(BRAIN, uuid)

    @pytest.mark.asyncio
    async def test_search_finds_one_person(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])

        pid, pname, created = await _resolve_person(
            api, BRAIN, "Sarah Smith", PERSON_TYPE, HOME
        )

        assert pid == "sarah-id"
        assert pname == "Sarah Smith"
        assert created is False

    @pytest.mark.asyncio
    async def test_creates_new_person_when_none_found(self):
        api = _mock_api()
        api.search_thoughts = AsyncMock(return_value=[])
        api.create_thought = AsyncMock(return_value={"id": "new-person-id"})

        pid, pname, created = await _resolve_person(
            api, BRAIN, "New Person", PERSON_TYPE, HOME
        )

        assert pid == "new-person-id"
        assert pname == "New Person"
        assert created is True
        api.create_thought.assert_called_once()
        call_data = api.create_thought.call_args[0][1]
        assert call_data["name"] == "New Person"
        assert call_data["kind"] == ThoughtKind.NORMAL
        assert call_data["typeId"] == PERSON_TYPE

    @pytest.mark.asyncio
    async def test_disambiguation_multiple_matches(self):
        api = _mock_api()
        s1 = _thought("sarah-1", "Sarah Smith", type_id=PERSON_TYPE)
        s2 = _thought("sarah-2", "Sarah Smith Jones", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(s1), _search_result(s2),
        ])

        with pytest.raises(ValueError) as exc_info:
            await _resolve_person(api, BRAIN, "Sarah", PERSON_TYPE, HOME)

        data = exc_info.value.args[0]
        assert data["disambiguation_needed"] is True
        assert len(data["candidates"]) == 2

    @pytest.mark.asyncio
    async def test_creates_without_type_when_none(self):
        """Person type not found in brain — still creates, just without typeId."""
        api = _mock_api()
        api.search_thoughts = AsyncMock(return_value=[])
        api.create_thought = AsyncMock(return_value={"id": "new-id"})

        pid, pname, created = await _resolve_person(
            api, BRAIN, "No Type Person", None, HOME
        )

        assert created is True
        call_data = api.create_thought.call_args[0][1]
        assert "typeId" not in call_data


# ---------------------------------------------------------------------------
# TestFindPersonTypeId
# ---------------------------------------------------------------------------


class TestFindPersonTypeId:
    @pytest.mark.asyncio
    async def test_finds_person_type(self):
        api = _mock_api()
        result = await _find_person_type_id(api, BRAIN)
        assert result == PERSON_TYPE

    @pytest.mark.asyncio
    async def test_returns_none_when_no_person_type(self):
        api = _mock_api()
        api.get_types = AsyncMock(return_value=[
            _thought("org-type", "Organization", kind=2),
        ])
        result = await _find_person_type_id(api, BRAIN)
        assert result is None


# ---------------------------------------------------------------------------
# TestDayResolution
# ---------------------------------------------------------------------------


class TestDayResolution:
    @pytest.mark.asyncio
    async def test_day_already_exists(self):
        api = _mock_api()
        api.get_thought_by_name = AsyncMock(
            return_value=_thought("day-id", "24, February, 2026")
        )

        day_id, created = await _resolve_day(api, BRAIN, 2026, "February", 24, HOME)

        assert day_id == "day-id"
        assert created == {"year": False, "month": False, "day": False}

    @pytest.mark.asyncio
    async def test_create_day_only(self):
        """Month exists, day doesn't."""
        api = _mock_api()
        month = _thought("month-id", "February, 2026")

        async def name_lookup(brain_id, name):
            if name == "24, February, 2026":
                return None
            if name == "February, 2026":
                return month
            return None

        api.get_thought_by_name = AsyncMock(side_effect=name_lookup)
        api.create_thought = AsyncMock(return_value={"id": "new-day-id"})

        day_id, created = await _resolve_day(api, BRAIN, 2026, "February", 24, HOME)

        assert day_id == "new-day-id"
        assert created == {"year": False, "month": False, "day": True}
        # Should create day under month
        call_data = api.create_thought.call_args[0][1]
        assert call_data["name"] == "24, February, 2026"
        assert call_data["sourceThoughtId"] == "month-id"

    @pytest.mark.asyncio
    async def test_create_month_and_day(self):
        """Year exists, month and day don't."""
        api = _mock_api()
        year = _thought("year-id", "2026")

        async def name_lookup(brain_id, name):
            if name == "2026":
                return year
            return None

        api.get_thought_by_name = AsyncMock(side_effect=name_lookup)

        call_count = 0

        async def create_thought(brain_id, data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"id": "new-month-id"}
            return {"id": "new-day-id"}

        api.create_thought = AsyncMock(side_effect=create_thought)

        day_id, created = await _resolve_day(api, BRAIN, 2026, "February", 24, HOME)

        assert day_id == "new-day-id"
        assert created == {"year": False, "month": True, "day": True}
        assert api.create_thought.call_count == 2

    @pytest.mark.asyncio
    async def test_create_full_chain(self):
        """Nothing exists — create year, month, day."""
        api = _mock_api()
        api.get_thought_by_name = AsyncMock(return_value=None)

        call_count = 0

        async def create_thought(brain_id, data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"id": "new-year-id"}
            if call_count == 2:
                return {"id": "new-month-id"}
            return {"id": "new-day-id"}

        api.create_thought = AsyncMock(side_effect=create_thought)

        day_id, created = await _resolve_day(api, BRAIN, 2026, "February", 24, HOME)

        assert day_id == "new-day-id"
        assert created == {"year": True, "month": True, "day": True}
        assert api.create_thought.call_count == 3

        # Verify chain: year under home, month under year, day under month
        calls = api.create_thought.call_args_list
        assert calls[0][0][1]["sourceThoughtId"] == HOME  # year under home
        assert calls[1][0][1]["sourceThoughtId"] == "new-year-id"  # month under year
        assert calls[2][0][1]["sourceThoughtId"] == "new-month-id"  # day under month


# ---------------------------------------------------------------------------
# TestEventCreation (full happy path)
# ---------------------------------------------------------------------------


class TestEventCreation:
    @pytest.mark.asyncio
    async def test_happy_path_custom_name(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])
        day = _thought("day-id", "1, March, 2026")
        api.get_thought_by_name = AsyncMock(return_value=day)
        api.create_thought = AsyncMock(return_value={"id": "event-id"})

        result = await event_for_person_tool(
            api, BRAIN, "2026-03-01", "Sarah Smith", event_name="Coffee Chat"
        )

        assert result["success"] is True
        assert result["event_id"] == "event-id"
        assert result["event_name"] == "2026,March,01, Coffee Chat, Sarah Smith"
        assert result["person_id"] == "sarah-id"
        assert result["person_name"] == "Sarah Smith"
        assert result["person_created"] is False
        assert result["day_id"] == "day-id"
        assert result["day_name"] == "1, March, 2026"

    @pytest.mark.asyncio
    async def test_auto_generated_event_name(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])
        day = _thought("day-id", "1, March, 2026")
        api.get_thought_by_name = AsyncMock(return_value=day)
        api.create_thought = AsyncMock(return_value={"id": "event-id"})

        result = await event_for_person_tool(api, BRAIN, "2026-03-01", "Sarah Smith")

        assert result["success"] is True
        assert "Event with Sarah Smith" in result["event_name"]

    @pytest.mark.asyncio
    async def test_with_notes(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])
        day = _thought("day-id", "1, March, 2026")
        api.get_thought_by_name = AsyncMock(return_value=day)
        api.create_thought = AsyncMock(return_value={"id": "event-id"})

        result = await event_for_person_tool(
            api, BRAIN, "2026-03-01", "Sarah Smith",
            event_name="Meeting", notes="Discussed project timeline."
        )

        assert result["success"] is True
        api.create_or_update_note.assert_called_once_with(
            BRAIN, "event-id", "Discussed project timeline."
        )

    @pytest.mark.asyncio
    async def test_event_thought_uses_event_kind(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])
        day = _thought("day-id", "1, March, 2026")
        api.get_thought_by_name = AsyncMock(return_value=day)
        api.create_thought = AsyncMock(return_value={"id": "event-id"})

        await event_for_person_tool(
            api, BRAIN, "2026-03-01", "Sarah Smith", event_name="Test"
        )

        create_data = api.create_thought.call_args[0][1]
        assert create_data["kind"] == ThoughtKind.EVENT


# ---------------------------------------------------------------------------
# TestJumpLinks
# ---------------------------------------------------------------------------


class TestJumpLinks:
    @pytest.mark.asyncio
    async def test_creates_both_jump_links(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])
        day = _thought("day-id", "1, March, 2026")
        api.get_thought_by_name = AsyncMock(return_value=day)
        api.create_thought = AsyncMock(return_value={"id": "event-id"})

        await event_for_person_tool(
            api, BRAIN, "2026-03-01", "Sarah Smith", event_name="Test"
        )

        assert api.create_link.call_count == 2
        calls = api.create_link.call_args_list

        # Event → Person
        assert calls[0][0][1] == {
            "thoughtIdA": "event-id",
            "thoughtIdB": "sarah-id",
            "relation": RelationType.JUMP,
        }
        # Event → Day
        assert calls[1][0][1] == {
            "thoughtIdA": "event-id",
            "thoughtIdB": "day-id",
            "relation": RelationType.JUMP,
        }


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self):
        api = _mock_api()
        result = await event_for_person_tool(api, BRAIN, "xyzzy nonsense", "Sarah")
        assert result["success"] is False
        assert "Could not parse date" in result["error"]

    @pytest.mark.asyncio
    async def test_brain_api_error_propagated(self):
        api = _mock_api()
        api.get_brain = AsyncMock(side_effect=TheBrainAPIError("404 Not Found"))

        result = await event_for_person_tool(api, BRAIN, "2026-03-01", "Sarah")
        assert result["success"] is False
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_disambiguation_returned(self):
        api = _mock_api()
        s1 = _thought("s1", "Sarah A", type_id=PERSON_TYPE)
        s2 = _thought("s2", "Sarah B", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(s1), _search_result(s2),
        ])

        result = await event_for_person_tool(api, BRAIN, "2026-03-01", "Sarah")
        assert result["success"] is False
        assert result["disambiguation_needed"] is True
        assert len(result["candidates"]) == 2

    @pytest.mark.asyncio
    async def test_link_creation_error(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])
        day = _thought("day-id", "1, March, 2026")
        api.get_thought_by_name = AsyncMock(return_value=day)
        api.create_thought = AsyncMock(return_value={"id": "event-id"})
        api.create_link = AsyncMock(side_effect=TheBrainAPIError("Server error"))

        result = await event_for_person_tool(
            api, BRAIN, "2026-03-01", "Sarah Smith", event_name="Test"
        )
        assert result["success"] is False
        assert "Link creation failed" in result["error"]

    @pytest.mark.asyncio
    async def test_note_creation_error(self):
        api = _mock_api()
        sarah = _thought("sarah-id", "Sarah Smith", type_id=PERSON_TYPE)
        api.search_thoughts = AsyncMock(return_value=[_search_result(sarah)])
        day = _thought("day-id", "1, March, 2026")
        api.get_thought_by_name = AsyncMock(return_value=day)
        api.create_thought = AsyncMock(return_value={"id": "event-id"})
        api.create_or_update_note = AsyncMock(
            side_effect=TheBrainAPIError("Note error")
        )

        result = await event_for_person_tool(
            api, BRAIN, "2026-03-01", "Sarah Smith",
            event_name="Test", notes="Some notes"
        )
        assert result["success"] is False
        assert "Note creation failed" in result["error"]
