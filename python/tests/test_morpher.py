"""Tests for the morpher tool (reparent / retype)."""

from unittest.mock import AsyncMock

import pytest

from thebrain_mcp.api.client import TheBrainAPIError
from thebrain_mcp.api.models import Link, Thought, ThoughtGraph
from thebrain_mcp.tools.morpher import morpher_tool

BRAIN = "brain-00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Mock helpers (same patterns as test_brainquery_planner.py)
# ---------------------------------------------------------------------------


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


def _graph(
    active: Thought,
    parents: list[Thought] | None = None,
    children: list[Thought] | None = None,
    links: list[Link] | None = None,
) -> ThoughtGraph:
    def to_dict(t: Thought) -> dict:
        return {
            "id": t.id, "brainId": t.brain_id, "name": t.name,
            "kind": t.kind, "acType": t.ac_type, "typeId": t.type_id,
        }
    def link_dict(lk: Link) -> dict:
        return {
            "id": lk.id, "brainId": lk.brain_id,
            "thoughtIdA": lk.thought_id_a, "thoughtIdB": lk.thought_id_b,
            "relation": lk.relation,
        }
    return ThoughtGraph.model_validate({
        "activeThought": to_dict(active),
        "parents": [to_dict(p) for p in (parents or [])],
        "children": [to_dict(c) for c in (children or [])],
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReparentOnly:
    @pytest.mark.asyncio
    async def test_reparent_deletes_old_and_creates_new(self):
        child = _thought("child-1", "My Thought")
        old_parent = _thought("parent-a", "Old Parent")
        parent_link = _link("link-1", "parent-a", "child-1", relation=1)

        graph = _graph(child, parents=[old_parent], links=[parent_link])
        api = _mock_api(graph)

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-b")

        assert result["success"] is True
        api.delete_link_verified.assert_called_once_with(BRAIN, "link-1")
        api.create_link.assert_called_once_with(BRAIN, {
            "thoughtIdA": "parent-b",
            "thoughtIdB": "child-1",
            "relation": 1,
        })
        assert result["reparent"]["old_parents"] == [{"id": "parent-a", "name": "Old Parent"}]
        assert result["reparent"]["new_parent_id"] == "parent-b"
        assert result["reparent"]["deleted_links"] == ["link-1"]
        assert result["reparent"]["created_link_id"] == "new-link-id"

    @pytest.mark.asyncio
    async def test_reparent_no_existing_parents(self):
        """Thought with no parents — just creates the new link."""
        child = _thought("child-1", "Orphan")
        graph = _graph(child, parents=[], links=[])
        api = _mock_api(graph)

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-b")

        assert result["success"] is True
        api.delete_link_verified.assert_not_called()
        api.create_link.assert_called_once()


class TestRetypeOnly:
    @pytest.mark.asyncio
    async def test_retype_calls_update(self):
        child = _thought("child-1", "My Thought", type_id="old-type")
        graph = _graph(child)
        api = _mock_api(graph)

        result = await morpher_tool(api, BRAIN, "child-1", new_type_id="new-type")

        assert result["success"] is True
        api.update_thought.assert_called_once_with(BRAIN, "child-1", {"typeId": "new-type"})
        assert result["retype"]["old_type_id"] == "old-type"
        assert result["retype"]["new_type_id"] == "new-type"
        assert "reparent" not in result


class TestReparentAndRetype:
    @pytest.mark.asyncio
    async def test_both_operations(self):
        child = _thought("child-1", "My Thought", type_id="old-type")
        old_parent = _thought("parent-a", "Old Parent")
        parent_link = _link("link-1", "parent-a", "child-1")

        graph = _graph(child, parents=[old_parent], links=[parent_link])
        api = _mock_api(graph)

        result = await morpher_tool(
            api, BRAIN, "child-1",
            new_parent_id="parent-b", new_type_id="new-type",
        )

        assert result["success"] is True
        assert "reparent" in result
        assert "retype" in result
        api.delete_link_verified.assert_called_once()
        api.create_link.assert_called_once()
        api.update_thought.assert_called_once()


class TestNoOperation:
    @pytest.mark.asyncio
    async def test_neither_param_returns_error(self):
        api = _mock_api()
        result = await morpher_tool(api, BRAIN, "child-1")

        assert result["success"] is False
        assert "at least one" in result["error"].lower()
        api.get_thought_graph.assert_not_called()


class TestMultiParentReparent:
    @pytest.mark.asyncio
    async def test_multiple_parents_all_deleted(self):
        child = _thought("child-1", "Multi-Parent Child")
        parent_a = _thought("parent-a", "Parent A")
        parent_b = _thought("parent-b", "Parent B")
        link_a = _link("link-a", "parent-a", "child-1")
        link_b = _link("link-b", "parent-b", "child-1")

        graph = _graph(child, parents=[parent_a, parent_b], links=[link_a, link_b])
        api = _mock_api(graph)

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-c")

        assert result["success"] is True
        assert api.delete_link_verified.call_count == 2
        assert set(result["reparent"]["deleted_links"]) == {"link-a", "link-b"}
        api.create_link.assert_called_once()


class TestApiErrorPropagated:
    @pytest.mark.asyncio
    async def test_graph_fetch_error(self):
        api = _mock_api()
        api.get_thought_graph = AsyncMock(side_effect=TheBrainAPIError("404 Not Found"))

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-b")

        assert result["success"] is False
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_link_error(self):
        """Undeletable links are tracked, not fatal — operation continues."""
        child = _thought("child-1", "My Thought")
        old_parent = _thought("parent-a", "Old Parent")
        parent_link = _link("link-1", "parent-a", "child-1")

        graph = _graph(child, parents=[old_parent], links=[parent_link])
        api = _mock_api(graph)
        api.delete_link_verified = AsyncMock(side_effect=TheBrainAPIError("Server error"))

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-b")

        assert result["success"] is True
        assert result["reparent"]["undeletable_links"] == ["link-1"]

    @pytest.mark.asyncio
    async def test_update_thought_error(self):
        child = _thought("child-1", "My Thought")
        graph = _graph(child)
        api = _mock_api(graph)
        api.update_thought = AsyncMock(side_effect=TheBrainAPIError("Permission denied"))

        result = await morpher_tool(api, BRAIN, "child-1", new_type_id="new-type")

        assert result["success"] is False
        assert "permission" in result["error"].lower()


class TestStaleCacheTolerance:
    """Ghost links (stale cache) are handled by delete_link_verified.

    The morpher delegates to delete_link_verified which returns
    {"success": True, "ghost": True} for ghost links. These are
    counted as deleted.
    """

    @pytest.mark.asyncio
    async def test_ghost_link_tolerated(self):
        """Single ghost link in graph — delete_link_verified returns ghost flag."""
        child = _thought("child-1", "My Thought")
        old_parent = _thought("parent-a", "Old Parent")
        ghost_link = _link("ghost-link", "parent-a", "child-1")

        graph = _graph(child, parents=[old_parent], links=[ghost_link])
        api = _mock_api(graph)
        api.delete_link_verified = AsyncMock(
            return_value={"success": True, "ghost": True}
        )

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-b")

        assert result["success"] is True
        assert result["reparent"]["deleted_links"] == ["ghost-link"]
        api.create_link.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_real_and_ghost_links(self):
        """Two parent links: one real (deletes ok), one ghost. Both succeed."""
        child = _thought("child-1", "My Thought")
        parent_a = _thought("parent-a", "Parent A")
        parent_b = _thought("parent-b", "Parent B")
        real_link = _link("real-link", "parent-a", "child-1")
        ghost_link = _link("ghost-link", "parent-b", "child-1")

        graph = _graph(child, parents=[parent_a, parent_b], links=[real_link, ghost_link])
        api = _mock_api(graph)

        async def selective_delete(brain_id, link_id):
            if link_id == "ghost-link":
                return {"success": True, "ghost": True}
            return {"success": True}

        api.delete_link_verified = AsyncMock(side_effect=selective_delete)

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-c")

        assert result["success"] is True
        assert set(result["reparent"]["deleted_links"]) == {"real-link", "ghost-link"}
        api.create_link.assert_called_once()


class TestUndeletableLinks:
    """Links that exist but the API refuses to delete (desktop-synced).

    delete_link_verified raises TheBrainAPIError for these. The morpher
    tracks them as undeletable rather than failing the whole operation.
    """

    @pytest.mark.asyncio
    async def test_undeletable_link_tracked_in_result(self):
        """Desktop-synced link → tracked in undeletable_links, operation continues."""
        child = _thought("child-1", "My Thought")
        old_parent = _thought("parent-a", "Old Parent")
        desktop_link = _link("desktop-link", "parent-a", "child-1")

        graph = _graph(child, parents=[old_parent], links=[desktop_link])
        api = _mock_api(graph)
        api.delete_link_verified = AsyncMock(
            side_effect=TheBrainAPIError(
                "TheBrain API refused to delete link desktop-link. "
                "Links synced from the desktop app cannot be deleted via the API."
            )
        )

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-b")

        assert result["success"] is True
        assert result["reparent"]["deleted_links"] == []
        assert result["reparent"]["undeletable_links"] == ["desktop-link"]
        api.create_link.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_deletable_and_undeletable(self):
        """One link deletes ok, one is undeletable — both tracked separately."""
        child = _thought("child-1", "My Thought")
        parent_a = _thought("parent-a", "Parent A")
        parent_b = _thought("parent-b", "Parent B")
        ok_link = _link("ok-link", "parent-a", "child-1")
        stuck_link = _link("stuck-link", "parent-b", "child-1")

        graph = _graph(child, parents=[parent_a, parent_b], links=[ok_link, stuck_link])
        api = _mock_api(graph)

        async def selective_delete(brain_id, link_id):
            if link_id == "stuck-link":
                raise TheBrainAPIError("API refused to delete")
            return {"success": True}

        api.delete_link_verified = AsyncMock(side_effect=selective_delete)

        result = await morpher_tool(api, BRAIN, "child-1", new_parent_id="parent-c")

        assert result["success"] is True
        assert result["reparent"]["deleted_links"] == ["ok-link"]
        assert result["reparent"]["undeletable_links"] == ["stuck-link"]
