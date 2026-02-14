"""Tests for the brain_query MCP tool logic.

Tests the parse→execute pipeline that the brain_query tool uses,
as well as error handling for invalid inputs.
"""

from unittest.mock import AsyncMock

import pytest

from thebrain_mcp.api.models import SearchResult, Thought, ThoughtGraph
from thebrain_mcp.brainquery import BrainQuerySyntaxError, execute, parse


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _thought(id: str, name: str, type_id: str | None = None, brain_id: str = "brain") -> Thought:
    return Thought.model_validate({
        "id": id,
        "brainId": brain_id,
        "name": name,
        "kind": 1,
        "acType": 0,
        "typeId": type_id,
    })


def _search_result(thought: Thought) -> SearchResult:
    return SearchResult.model_validate({
        "searchResultType": 0,
        "sourceThought": {
            "id": thought.id,
            "brainId": thought.brain_id,
            "name": thought.name,
            "kind": thought.kind,
            "acType": thought.ac_type,
            "typeId": thought.type_id,
        },
    })


def _graph(active: Thought, children=None, parents=None, jumps=None, siblings=None) -> ThoughtGraph:
    def to_dict(t):
        return {
            "id": t.id, "brainId": t.brain_id, "name": t.name,
            "kind": t.kind, "acType": t.ac_type, "typeId": t.type_id,
        }
    return ThoughtGraph.model_validate({
        "activeThought": to_dict(active),
        "children": [to_dict(t) for t in (children or [])],
        "parents": [to_dict(t) for t in (parents or [])],
        "jumps": [to_dict(t) for t in (jumps or [])],
        "siblings": [to_dict(t) for t in (siblings or [])],
    })


def _mock_api():
    api = AsyncMock()
    api.get_thought_by_name = AsyncMock(return_value=None)
    api.search_thoughts = AsyncMock(return_value=[])
    api.get_types = AsyncMock(return_value=[])
    api.get_thought = AsyncMock(return_value=None)
    api.get_thought_graph = AsyncMock(return_value=_graph(_thought("root", "Root")))
    api.create_thought = AsyncMock(return_value={"id": "new-id"})
    api.create_link = AsyncMock(return_value={"id": "new-link-id"})
    return api


async def _run_query(api, query_str: str, brain_id: str = "brain") -> dict:
    """Simulate what the brain_query tool does: parse → execute → to_dict."""
    parsed = parse(query_str)
    result = await execute(api, brain_id, parsed)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Error handling (parse phase)
# ---------------------------------------------------------------------------


class TestParseErrors:
    def test_syntax_error(self) -> None:
        with pytest.raises(BrainQuerySyntaxError):
            parse("THIS IS NOT VALID")

    def test_empty_query(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Empty query"):
            parse("")

    def test_unsupported_delete(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="DELETE"):
            parse('DELETE (n {name: "X"})')


# ---------------------------------------------------------------------------
# End-to-end: parse → execute → to_dict
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_match_by_name(self) -> None:
        api = _mock_api()
        t = _thought("t1", "Test Thought")
        api.get_thought_by_name = AsyncMock(return_value=t)

        result = await _run_query(api, 'MATCH (n {name: "Test Thought"}) RETURN n')

        assert result["success"] is True
        assert result["action"] == "match"
        assert len(result["results"]["n"]) == 1
        assert result["results"]["n"][0]["id"] == "t1"
        assert result["results"]["n"][0]["name"] == "Test Thought"

    @pytest.mark.asyncio
    async def test_match_with_child_traversal(self) -> None:
        api = _mock_api()
        parent = _thought("p1", "Projects")
        child1 = _thought("c1", "Alpha")
        child2 = _thought("c2", "Beta")
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[child1, child2])
        )

        result = await _run_query(
            api, 'MATCH (n {name: "Projects"})-[:CHILD]->(m) RETURN m'
        )

        assert result["success"] is True
        assert len(result["results"]["m"]) == 2
        names = {r["name"] for r in result["results"]["m"]}
        assert names == {"Alpha", "Beta"}

    @pytest.mark.asyncio
    async def test_match_with_contains(self) -> None:
        api = _mock_api()
        t = _thought("t1", "MCP Server")
        api.search_thoughts = AsyncMock(return_value=[_search_result(t)])

        result = await _run_query(
            api, 'MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n'
        )

        assert result["success"] is True
        assert len(result["results"]["n"]) == 1
        assert result["results"]["n"][0]["name"] == "MCP Server"

    @pytest.mark.asyncio
    async def test_create_standalone(self) -> None:
        api = _mock_api()

        result = await _run_query(api, 'CREATE (n {name: "New Idea"})')

        assert result["success"] is True
        assert result["action"] == "create"
        assert len(result["created"]) == 1
        assert result["created"][0]["name"] == "New Idea"
        assert result["created"][0]["type"] == "thought"

    @pytest.mark.asyncio
    async def test_match_create_child(self) -> None:
        api = _mock_api()
        parent = _thought("p1", "Projects")
        api.get_thought_by_name = AsyncMock(return_value=parent)

        result = await _run_query(
            api,
            'MATCH (p {name: "Projects"}) '
            'CREATE (p)-[:CHILD]->(n {name: "New Project"})',
        )

        assert result["success"] is True
        assert result["action"] == "match_create"
        assert len(result["created"]) == 1
        assert result["created"][0]["name"] == "New Project"
        assert result["created"][0]["relation"] == "CHILD"
        assert result["created"][0]["parent"] == "Projects"

    @pytest.mark.asyncio
    async def test_match_create_link(self) -> None:
        api = _mock_api()
        alice = _thought("a1", "Alice")
        bob = _thought("b1", "Bob")

        async def name_lookup(brain_id, name):
            if name == "Alice":
                return alice
            if name == "Bob":
                return bob
            return None
        api.get_thought_by_name = AsyncMock(side_effect=name_lookup)

        result = await _run_query(
            api,
            'MATCH (a {name: "Alice"}), (b {name: "Bob"}) '
            'CREATE (a)-[:JUMP]->(b)',
        )

        assert result["success"] is True
        assert len(result["created"]) == 1
        assert result["created"][0]["type"] == "link"
        assert result["created"][0]["relation"] == "JUMP"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:
        api = _mock_api()

        result = await _run_query(
            api, 'MATCH (n {name: "Nonexistent"}) RETURN n'
        )

        assert result["success"] is True
        assert result["results"]["n"] == []

    @pytest.mark.asyncio
    async def test_to_dict_omits_empty_sections(self) -> None:
        """to_dict should not include 'created' or 'errors' keys when empty."""
        api = _mock_api()
        t = _thought("t1", "Test")
        api.get_thought_by_name = AsyncMock(return_value=t)

        result = await _run_query(api, 'MATCH (n {name: "Test"}) RETURN n')

        assert "created" not in result
        assert "errors" not in result

    @pytest.mark.asyncio
    async def test_create_omits_results_section(self) -> None:
        """CREATE-only queries should not include 'results' key."""
        api = _mock_api()

        result = await _run_query(api, 'CREATE (n {name: "X"})')

        assert "results" not in result
        assert "created" in result


# ---------------------------------------------------------------------------
# Variable-length paths (end-to-end)
# ---------------------------------------------------------------------------


class TestVariableLengthE2E:
    @pytest.mark.asyncio
    async def test_variable_length_e2e(self) -> None:
        api = _mock_api()
        root = _thought("r1", "Root")
        child = _thought("c1", "Child")
        grandchild = _thought("gc1", "Grandchild")
        api.get_thought_by_name = AsyncMock(return_value=root)

        async def graph_lookup(brain_id, thought_id):
            if thought_id == "r1":
                return _graph(root, children=[child])
            if thought_id == "c1":
                return _graph(child, children=[grandchild])
            return _graph(_thought(thought_id, "X"))
        api.get_thought_graph = AsyncMock(side_effect=graph_lookup)

        result = await _run_query(
            api, 'MATCH (n {name: "Root"})-[:CHILD*1..2]->(m) RETURN m'
        )

        assert result["success"] is True
        assert len(result["results"]["m"]) == 2


# ---------------------------------------------------------------------------
# Compound WHERE (end-to-end)
# ---------------------------------------------------------------------------


class TestCompoundWhereE2E:
    @pytest.mark.asyncio
    async def test_and_across_chain_variables(self) -> None:
        """Compound AND with chain: parse → execute → to_dict."""
        api = _mock_api()
        root = _thought("r1", "Root")
        child1 = _thought("c1", "Alpha")
        child2 = _thought("c2", "Beta")
        api.get_thought_by_name = AsyncMock(return_value=root)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(root, children=[child1, child2])
        )

        result = await _run_query(
            api,
            'MATCH (a {name: "Root"})-[:CHILD]->(b) '
            'WHERE b.name STARTS WITH "Al" RETURN b',
        )

        assert result["success"] is True
        assert len(result["results"]["b"]) == 1
        assert result["results"]["b"][0]["name"] == "Alpha"

    @pytest.mark.asyncio
    async def test_or_same_variable_e2e(self) -> None:
        """OR on same variable: parse → execute → to_dict."""
        api = _mock_api()
        t1 = _thought("t1", "Alice")
        t2 = _thought("t2", "Bob")

        async def name_lookup(brain_id, name):
            if name == "Alice":
                return t1
            if name == "Bob":
                return t2
            return None
        api.get_thought_by_name = AsyncMock(side_effect=name_lookup)

        result = await _run_query(
            api,
            'MATCH (n) WHERE n.name = "Alice" OR n.name = "Bob" RETURN n',
        )

        assert result["success"] is True
        assert len(result["results"]["n"]) == 2


# ---------------------------------------------------------------------------
# Tool registration check
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_brain_query_is_registered(self) -> None:
        """The brain_query tool should be registered on the MCP server."""
        from thebrain_mcp.server import mcp
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "brain_query" in tool_names
