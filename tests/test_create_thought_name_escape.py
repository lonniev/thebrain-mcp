"""Tests for create-path HTML-entity escaping of thought name/label (issue #207).

TheBrain's POST /thoughts HTML-entity-encodes characters such as ``&`` in
``name``/``label`` (so ``Growth & Adoption`` is persisted as
``Growth &amp; Adoption``). PATCH does not. Our client must repair the
create path so names round-trip verbatim, matching update behavior.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.api.client import TheBrainAPI, _field_needs_entity_repair
from thebrain_mcp.tools.thoughts import create_thought_tool

BRAIN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
THOUGHT_ID = "11111111-2222-3333-4444-555555555555"


class TestFieldNeedsEntityRepair:
    def test_ampersand(self) -> None:
        assert _field_needs_entity_repair("Growth & Adoption") is True

    def test_angle_brackets(self) -> None:
        assert _field_needs_entity_repair("a < b > c") is True

    def test_quotes(self) -> None:
        assert _field_needs_entity_repair('say "hi"') is True
        assert _field_needs_entity_repair("it's") is True

    def test_clean_name(self) -> None:
        assert _field_needs_entity_repair("Growth and Adoption") is False

    def test_pipe_and_emdash_ok(self) -> None:
        # Field report: label with | and em dash round-tripped correctly.
        assert _field_needs_entity_repair("Sales | Research — 2026") is False


class TestCreateThoughtRepairsHtmlEntities:
    @pytest.mark.asyncio
    async def test_create_with_ampersand_issues_repair_patch(self) -> None:
        """POST create followed by PATCH repair when name has &."""
        api = TheBrainAPI("test-key")
        # Simulate upstream POST returning the HTML-escaped name.
        api._request = AsyncMock(
            return_value={"id": THOUGHT_ID, "name": "Growth &amp; Adoption"}
        )
        api.update_thought = AsyncMock(return_value={})

        name = "Growth & Adoption"
        result = await api.create_thought(BRAIN, {"name": name, "kind": 1, "acType": 0})

        api._request.assert_awaited_once()
        api.update_thought.assert_awaited_once_with(BRAIN, THOUGHT_ID, {"name": name})
        # Response reflects the intended (unescaped) name, not the POST body.
        assert result["name"] == name
        assert result["id"] == THOUGHT_ID
        assert "&amp;" not in result["name"]

        await api.close()

    @pytest.mark.asyncio
    async def test_create_with_label_ampersand_repairs_both(self) -> None:
        api = TheBrainAPI("test-key")
        api._request = AsyncMock(return_value={"id": THOUGHT_ID})
        api.update_thought = AsyncMock(return_value={})

        name = "R&D"
        label = "Research & Development"
        await api.create_thought(
            BRAIN, {"name": name, "label": label, "kind": 1, "acType": 0}
        )

        api.update_thought.assert_awaited_once_with(
            BRAIN, THOUGHT_ID, {"name": name, "label": label}
        )

        await api.close()

    @pytest.mark.asyncio
    async def test_create_clean_name_skips_repair(self) -> None:
        """No extra PATCH when name/label have no HTML-sensitive characters."""
        api = TheBrainAPI("test-key")
        api._request = AsyncMock(return_value={"id": THOUGHT_ID, "name": "Plain Name"})
        api.update_thought = AsyncMock(return_value={})

        await api.create_thought(BRAIN, {"name": "Plain Name", "kind": 1, "acType": 0})

        api.update_thought.assert_not_awaited()

        await api.close()

    @pytest.mark.asyncio
    async def test_create_without_id_skips_repair(self) -> None:
        api = TheBrainAPI("test-key")
        api._request = AsyncMock(return_value={})
        api.update_thought = AsyncMock(return_value={})

        await api.create_thought(
            BRAIN, {"name": "A & B", "kind": 1, "acType": 0}
        )

        api.update_thought.assert_not_awaited()

        await api.close()


class TestCreateThoughtToolRoundTrip:
    @pytest.mark.asyncio
    async def test_tool_returns_verbatim_name_and_triggers_client_create(self) -> None:
        """Tool surface must expose the caller-supplied name, not an escaped form."""
        api = MagicMock()
        api.create_thought = AsyncMock(
            return_value={"id": THOUGHT_ID, "name": "Growth & Adoption"}
        )

        name = "Growth & Adoption Strategy"
        result = await create_thought_tool(api, BRAIN, name=name)

        assert result["success"] is True
        assert result["thought"]["name"] == name
        assert "&" in result["thought"]["name"]
        assert "&amp;" not in result["thought"]["name"]
        api.create_thought.assert_awaited_once()
        sent = api.create_thought.await_args.args[1]
        assert sent["name"] == name
