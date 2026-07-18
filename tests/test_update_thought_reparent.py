"""Tests for update_thought's unified mutation (scalar fields + reparent).

Covers the enhancement that lets a single update_thought call set any subset
of {name, label, type, parent}, reusing the morpher's reparent link-surgery.
"""

from unittest.mock import AsyncMock

import pytest

from thebrain_mcp.api.client import TheBrainAPIError
from thebrain_mcp.api.models import Link, Thought, ThoughtGraph
from thebrain_mcp.tools.thoughts import update_thought_tool

BRAIN = "brain-00000000-0000-0000-0000-000000000000"


def _thought(id: str, name: str, type_id: str | None = None) -> Thought:
    return Thought.model_validate({
        "id": id, "brainId": BRAIN, "name": name, "kind": 1, "acType": 0,
        "typeId": type_id,
    })


def _link(id: str, a: str, b: str, relation: int = 1) -> Link:
    return Link.model_validate({
        "id": id, "brainId": BRAIN, "thoughtIdA": a, "thoughtIdB": b,
        "relation": relation,
    })


def _graph(active, parents=None, links=None) -> ThoughtGraph:
    def to_dict(t):
        return {
            "id": t.id, "brainId": t.brain_id, "name": t.name,
            "kind": t.kind, "acType": t.ac_type, "typeId": t.type_id,
        }
    def link_dict(lk):
        return {
            "id": lk.id, "brainId": lk.brain_id,
            "thoughtIdA": lk.thought_id_a, "thoughtIdB": lk.thought_id_b,
            "relation": lk.relation,
        }
    return ThoughtGraph.model_validate({
        "activeThought": to_dict(active),
        "parents": [to_dict(p) for p in (parents or [])],
        "links": [link_dict(lk) for lk in (links or [])],
    })


def _mock_api(graph: ThoughtGraph | None = None) -> AsyncMock:
    api = AsyncMock()
    if graph:
        api.get_thought_graph = AsyncMock(return_value=graph)
    api.delete_link_verified = AsyncMock(return_value={"success": True})
    api.create_link = AsyncMock(return_value={"id": "new-link-id"})
    api.update_thought = AsyncMock(return_value={})
    return api


class TestScalarOnly:
    @pytest.mark.asyncio
    async def test_name_and_label_only_no_reparent(self):
        """Scalar-only update must not fetch the graph or reparent."""
        api = _mock_api()

        result = await update_thought_tool(
            api, BRAIN, "child-1", name="Renamed", label="A label",
        )

        assert result["success"] is True
        assert result["updates"] == {"name": "Renamed", "label": "A label"}
        assert "reparent" not in result
        api.update_thought.assert_called_once_with(
            BRAIN, "child-1", {"name": "Renamed", "label": "A label"}
        )
        api.get_thought_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_update_does_not_call_api(self):
        """No fields and no parent → no update_thought call, still succeeds."""
        api = _mock_api()

        result = await update_thought_tool(api, BRAIN, "child-1")

        assert result["success"] is True
        assert result["updates"] == {}
        api.update_thought.assert_not_called()
        api.get_thought_graph.assert_not_called()


class TestReparentOnly:
    @pytest.mark.asyncio
    async def test_parent_only_skips_scalar_update(self):
        """Only new_parent_id → no scalar update, but reparent happens."""
        child = _thought("child-1", "My Thought")
        old_parent = _thought("parent-a", "Old Parent")
        parent_link = _link("link-1", "parent-a", "child-1")
        api = _mock_api(_graph(child, parents=[old_parent], links=[parent_link]))

        result = await update_thought_tool(
            api, BRAIN, "child-1", new_parent_id="parent-b",
        )

        assert result["success"] is True
        assert result["updates"] == {}
        api.update_thought.assert_not_called()
        api.delete_link_verified.assert_called_once_with(BRAIN, "link-1")
        api.create_link.assert_called_once_with(BRAIN, {
            "thoughtIdA": "parent-b", "thoughtIdB": "child-1", "relation": 1,
        })
        assert result["reparent"]["deleted_links"] == ["link-1"]
        assert result["reparent"]["created_link_id"] == "new-link-id"


class TestUnifiedMutation:
    @pytest.mark.asyncio
    async def test_name_label_type_and_parent_in_one_call(self):
        """All four field families set in a single call."""
        child = _thought("child-1", "Old Name")
        old_parent = _thought("parent-a", "Old Parent")
        parent_link = _link("link-1", "parent-a", "child-1")
        api = _mock_api(_graph(child, parents=[old_parent], links=[parent_link]))

        result = await update_thought_tool(
            api, BRAIN, "child-1",
            name="New Name", label="New Label", type_id="type-x",
            new_parent_id="parent-b",
        )

        assert result["success"] is True
        api.update_thought.assert_called_once_with(BRAIN, "child-1", {
            "name": "New Name", "label": "New Label", "typeId": "type-x",
        })
        assert result["reparent"]["new_parent_id"] == "parent-b"
        api.delete_link_verified.assert_called_once()
        api.create_link.assert_called_once()


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_scalar_update_error_propagated(self):
        api = _mock_api()
        api.update_thought = AsyncMock(side_effect=TheBrainAPIError("Permission denied"))

        result = await update_thought_tool(api, BRAIN, "child-1", name="X")

        assert result["success"] is False
        assert "permission" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_reparent_graph_fetch_error_propagated(self):
        api = _mock_api()
        api.get_thought_graph = AsyncMock(side_effect=TheBrainAPIError("404 Not Found"))

        result = await update_thought_tool(
            api, BRAIN, "child-1", new_parent_id="parent-b",
        )

        assert result["success"] is False
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_undeletable_parent_link_aborts_reparent(self):
        """Undeletable old parent link aborts the reparent (issue #186).

        update_thought reuses the morpher's link-surgery, so a move that
        cannot persist must surface as success=False rather than a silent
        revert.
        """
        child = _thought("child-1", "My Thought")
        old_parent = _thought("parent-a", "Old Parent")
        stuck_link = _link("stuck-link", "parent-a", "child-1")
        api = _mock_api(_graph(child, parents=[old_parent], links=[stuck_link]))
        api.delete_link_verified = AsyncMock(
            side_effect=TheBrainAPIError("API refused to delete")
        )

        result = await update_thought_tool(
            api, BRAIN, "child-1", new_parent_id="parent-b",
        )

        assert result["success"] is False
        assert "stuck-link" in result["error"]
        api.create_link.assert_not_called()
