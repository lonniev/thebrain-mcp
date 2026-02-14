"""Tests for BrainQuery planner & executor."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from thebrain_mcp.api.models import SearchResult, Thought, ThoughtGraph
from thebrain_mcp.brainquery import execute, parse


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
        d = {
            "id": t.id, "brainId": t.brain_id, "name": t.name,
            "kind": t.kind, "acType": t.ac_type, "typeId": t.type_id,
        }
        if t.label is not None:
            d["label"] = t.label
        if t.foreground_color is not None:
            d["foregroundColor"] = t.foreground_color
        if t.background_color is not None:
            d["backgroundColor"] = t.background_color
        return d
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


# ---------------------------------------------------------------------------
# MATCH: name resolution
# ---------------------------------------------------------------------------


class TestMatchByName:
    @pytest.mark.asyncio
    async def test_exact_name_found(self) -> None:
        api = _mock_api()
        t = _thought("t1", "Claude Thoughts")
        api.get_thought_by_name = AsyncMock(return_value=t)

        q = parse('MATCH (n {name: "Claude Thoughts"}) RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        assert result.results["n"][0].id == "t1"
        api.get_thought_by_name.assert_called_once()

    @pytest.mark.asyncio
    async def test_exact_name_no_fallback(self) -> None:
        """Inline {name: ...} is strict — no search fallback."""
        api = _mock_api()
        api.get_thought_by_name = AsyncMock(return_value=None)
        api.search_thoughts = AsyncMock(return_value=[_search_result(_thought("t1", "Claude Thoughts"))])

        q = parse('MATCH (n {name: "Claude Thoughts"}) RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert result.results["n"] == []
        api.search_thoughts.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_results(self) -> None:
        api = _mock_api()

        q = parse('MATCH (n {name: "Nonexistent"}) RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert result.results["n"] == []


class TestMatchWithWhere:
    @pytest.mark.asyncio
    async def test_where_equals(self) -> None:
        api = _mock_api()
        t = _thought("t1", "Test")
        api.get_thought_by_name = AsyncMock(return_value=t)

        q = parse('MATCH (n) WHERE n.name = "Test" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        api.get_thought_by_name.assert_called_with("brain", "Test")

    @pytest.mark.asyncio
    async def test_where_contains(self) -> None:
        api = _mock_api()
        t = _thought("t1", "MCP Server")
        api.search_thoughts = AsyncMock(return_value=[_search_result(t)])

        q = parse('MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        api.search_thoughts.assert_called_once()


# ---------------------------------------------------------------------------
# MATCH: name matching modes
# ---------------------------------------------------------------------------


class TestMatchingModes:
    @pytest.mark.asyncio
    async def test_where_equals_strict(self) -> None:
        """WHERE = is strict exact match, no fallback."""
        api = _mock_api()
        api.get_thought_by_name = AsyncMock(return_value=None)

        q = parse('MATCH (n) WHERE n.name = "Missing" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert result.results["n"] == []
        api.search_thoughts.assert_not_called()

    @pytest.mark.asyncio
    async def test_starts_with(self) -> None:
        api = _mock_api()
        t1 = _thought("t1", "MCP Server")
        t2 = _thought("t2", "MCP Client")
        t3 = _thought("t3", "Other Thing")
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t1), _search_result(t2), _search_result(t3),
        ])

        q = parse('MATCH (n) WHERE n.name STARTS WITH "MCP" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 2
        names = {r.name for r in result.results["n"]}
        assert names == {"MCP Server", "MCP Client"}

    @pytest.mark.asyncio
    async def test_ends_with(self) -> None:
        api = _mock_api()
        t1 = _thought("t1", "MCP Server")
        t2 = _thought("t2", "Web Server")
        t3 = _thought("t3", "MCP Client")
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t1), _search_result(t2), _search_result(t3),
        ])

        q = parse('MATCH (n) WHERE n.name ENDS WITH "Server" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 2
        names = {r.name for r in result.results["n"]}
        assert names == {"MCP Server", "Web Server"}

    @pytest.mark.asyncio
    async def test_contains_filters(self) -> None:
        """CONTAINS post-filters search results by substring."""
        api = _mock_api()
        t1 = _thought("t1", "MCP Server")
        t2 = _thought("t2", "Other Thing")
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t1), _search_result(t2),
        ])

        q = parse('MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        assert result.results["n"][0].name == "MCP Server"

    @pytest.mark.asyncio
    async def test_similar_exact_hit(self) -> None:
        """=~ returns exact match when available."""
        api = _mock_api()
        t = _thought("t1", "Claude Thoughts")
        api.get_thought_by_name = AsyncMock(return_value=t)

        q = parse('MATCH (n) WHERE n.name =~ "Claude Thoughts" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        assert result.results["n"][0].id == "t1"
        api.search_thoughts.assert_not_called()

    @pytest.mark.asyncio
    async def test_similar_fallback_to_search(self) -> None:
        """=~ falls back to search and ranks results."""
        api = _mock_api()
        t1 = _thought("t1", "Claude Thoughts")
        t2 = _thought("t2", "Claude Code Extensions")
        api.get_thought_by_name = AsyncMock(return_value=None)
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t2), _search_result(t1),
        ])

        q = parse('MATCH (n) WHERE n.name =~ "Claude" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 2
        api.search_thoughts.assert_called_once()

    @pytest.mark.asyncio
    async def test_case_insensitive_matching(self) -> None:
        """String matching is case-insensitive."""
        api = _mock_api()
        t = _thought("t1", "MCP Server")
        api.search_thoughts = AsyncMock(return_value=[_search_result(t)])

        q = parse('MATCH (n) WHERE n.name STARTS WITH "mcp" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1


# ---------------------------------------------------------------------------
# MATCH: type filtering (lazy)
# ---------------------------------------------------------------------------


class TestMatchWithType:
    @pytest.mark.asyncio
    async def test_type_filter_applied_lazily(self) -> None:
        api = _mock_api()
        person_type = _thought("type-person", "Person", brain_id="brain")
        lonnie = _thought("t1", "Lonnie", type_id="type-person")

        api.get_thought_by_name = AsyncMock(return_value=lonnie)
        api.get_types = AsyncMock(return_value=[person_type])

        q = parse('MATCH (p:Person {name: "Lonnie"}) RETURN p')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["p"]) == 1
        # Types were fetched (lazy) because a type label was specified
        api.get_types.assert_called_once()

    @pytest.mark.asyncio
    async def test_type_filter_excludes_wrong_type(self) -> None:
        api = _mock_api()
        person_type = _thought("type-person", "Person", brain_id="brain")
        company = _thought("t1", "Lonnie", type_id="type-company")

        api.get_thought_by_name = AsyncMock(return_value=company)
        api.get_types = AsyncMock(return_value=[person_type])

        q = parse('MATCH (p:Person {name: "Lonnie"}) RETURN p')
        result = await execute(api, "brain", q)

        assert result.success
        assert result.results["p"] == []

    @pytest.mark.asyncio
    async def test_type_not_fetched_when_no_candidates(self) -> None:
        api = _mock_api()

        q = parse('MATCH (p:Person {name: "Nobody"}) RETURN p')
        result = await execute(api, "brain", q)

        assert result.success
        assert result.results["p"] == []
        # Types should NOT have been fetched — no candidates to filter
        api.get_types.assert_not_called()

    @pytest.mark.asyncio
    async def test_type_only_query(self) -> None:
        api = _mock_api()
        person_type = _thought("type-person", "Person", brain_id="brain")
        api.get_types = AsyncMock(return_value=[person_type])
        api.get_thought = AsyncMock(return_value=person_type)

        q = parse("MATCH (n:Person) RETURN n")
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        assert result.results["n"][0].id == "type-person"


# ---------------------------------------------------------------------------
# MATCH: relationship traversal
# ---------------------------------------------------------------------------


class TestMatchRelationships:
    @pytest.mark.asyncio
    async def test_child_traversal(self) -> None:
        api = _mock_api()
        parent = _thought("p1", "My Thoughts")
        child1 = _thought("c1", "Child 1")
        child2 = _thought("c2", "Child 2")
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[child1, child2])
        )

        q = parse('MATCH (n {name: "My Thoughts"})-[:CHILD]->(m) RETURN m')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["m"]) == 2
        assert {r.id for r in result.results["m"]} == {"c1", "c2"}

    @pytest.mark.asyncio
    async def test_jump_traversal(self) -> None:
        api = _mock_api()
        src = _thought("s1", "Source")
        jump = _thought("j1", "Jump Target")
        api.get_thought_by_name = AsyncMock(return_value=src)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(src, jumps=[jump])
        )

        q = parse('MATCH (n {name: "Source"})-[:JUMP]->(j) RETURN j')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["j"]) == 1
        assert result.results["j"][0].name == "Jump Target"

    @pytest.mark.asyncio
    async def test_traversal_with_no_source(self) -> None:
        api = _mock_api()

        q = parse('MATCH (n {name: "Missing"})-[:CHILD]->(m) RETURN m')
        result = await execute(api, "brain", q)

        assert result.success
        assert result.results["m"] == []


# ---------------------------------------------------------------------------
# MATCH: variable-length traversal
# ---------------------------------------------------------------------------


class TestVariableLengthTraversal:
    @pytest.mark.asyncio
    async def test_fixed_two_hops(self) -> None:
        """*2 traverses exactly 2 levels."""
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

        q = parse('MATCH (n {name: "Root"})-[:CHILD*2]->(m) RETURN m')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["m"]) == 1
        assert result.results["m"][0].name == "Grandchild"

    @pytest.mark.asyncio
    async def test_range_one_to_two(self) -> None:
        """*1..2 returns both children and grandchildren."""
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

        q = parse('MATCH (n {name: "Root"})-[:CHILD*1..2]->(m) RETURN m')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["m"]) == 2
        names = {r.name for r in result.results["m"]}
        assert names == {"Child", "Grandchild"}

    @pytest.mark.asyncio
    async def test_cycle_detection(self) -> None:
        """BFS should not revisit nodes in cycles."""
        api = _mock_api()
        a = _thought("a1", "A")
        b = _thought("b1", "B")
        api.get_thought_by_name = AsyncMock(return_value=a)

        async def graph_lookup(brain_id, thought_id):
            if thought_id == "a1":
                return _graph(a, jumps=[b])
            if thought_id == "b1":
                return _graph(b, jumps=[a])
            return _graph(_thought(thought_id, "X"))
        api.get_thought_graph = AsyncMock(side_effect=graph_lookup)

        q = parse('MATCH (n {name: "A"})-[:JUMP*1..3]->(m) RETURN m')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["m"]) == 1
        assert result.results["m"][0].name == "B"

    @pytest.mark.asyncio
    async def test_empty_frontier_early_exit(self) -> None:
        """Traversal stops when no more nodes to expand."""
        api = _mock_api()
        root = _thought("r1", "Root")
        leaf = _thought("l1", "Leaf")
        api.get_thought_by_name = AsyncMock(return_value=root)

        async def graph_lookup(brain_id, thought_id):
            if thought_id == "r1":
                return _graph(root, children=[leaf])
            return _graph(_thought(thought_id, "X"))
        api.get_thought_graph = AsyncMock(side_effect=graph_lookup)

        q = parse('MATCH (n {name: "Root"})-[:CHILD*1..5]->(m) RETURN m')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["m"]) == 1
        assert result.results["m"][0].name == "Leaf"
        assert api.get_thought_graph.call_count == 2


# ---------------------------------------------------------------------------
# MATCH: multi-hop chain execution
# ---------------------------------------------------------------------------


class TestMultiHopChainExecution:
    @pytest.mark.asyncio
    async def test_two_hop_chain(self) -> None:
        api = _mock_api()
        root = _thought("r1", "Root")
        mid = _thought("m1", "Middle")
        leaf = _thought("l1", "Leaf")
        api.get_thought_by_name = AsyncMock(return_value=root)

        async def graph_lookup(brain_id, thought_id):
            if thought_id == "r1":
                return _graph(root, children=[mid])
            if thought_id == "m1":
                return _graph(mid, children=[leaf])
            return _graph(_thought(thought_id, "X"))
        api.get_thought_graph = AsyncMock(side_effect=graph_lookup)

        q = parse('MATCH (a {name: "Root"})-[:CHILD]->(b)-[:CHILD]->(c) RETURN c')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["c"]) == 1
        assert result.results["c"][0].name == "Leaf"

    @pytest.mark.asyncio
    async def test_chain_intermediate_return(self) -> None:
        api = _mock_api()
        root = _thought("r1", "Root")
        mid = _thought("m1", "Middle")
        leaf = _thought("l1", "Leaf")
        api.get_thought_by_name = AsyncMock(return_value=root)

        async def graph_lookup(brain_id, thought_id):
            if thought_id == "r1":
                return _graph(root, children=[mid])
            if thought_id == "m1":
                return _graph(mid, children=[leaf])
            return _graph(_thought(thought_id, "X"))
        api.get_thought_graph = AsyncMock(side_effect=graph_lookup)

        q = parse('MATCH (a {name: "Root"})-[:CHILD]->(b)-[:CHILD]->(c) RETURN b, c')
        result = await execute(api, "brain", q)

        assert result.success
        assert "b" in result.results
        assert "c" in result.results
        assert result.results["b"][0].name == "Middle"
        assert result.results["c"][0].name == "Leaf"


# ---------------------------------------------------------------------------
# MATCH: compound WHERE execution
# ---------------------------------------------------------------------------


class TestCompoundWhereExecution:
    @pytest.mark.asyncio
    async def test_same_variable_and(self) -> None:
        """AND on same variable: primary search + post-filter."""
        api = _mock_api()
        t1 = _thought("t1", "MCP Server")
        t2 = _thought("t2", "MCP Client")
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t1), _search_result(t2),
        ])

        q = parse('MATCH (n) WHERE n.name CONTAINS "MCP" AND n.name ENDS WITH "Server" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        assert result.results["n"][0].name == "MCP Server"

    @pytest.mark.asyncio
    async def test_same_variable_or(self) -> None:
        """OR on same variable: union of two searches."""
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

        q = parse('MATCH (n) WHERE n.name = "Alice" OR n.name = "Bob" RETURN n')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 2
        names = {r.name for r in result.results["n"]}
        assert names == {"Alice", "Bob"}

    @pytest.mark.asyncio
    async def test_multi_variable_and_in_chain(self) -> None:
        """AND across variables in a chain: conditions routed to correct hop."""
        api = _mock_api()
        root = _thought("r1", "Root")
        child1 = _thought("c1", "Alpha Child")
        child2 = _thought("c2", "Beta Child")
        api.get_thought_by_name = AsyncMock(return_value=root)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(root, children=[child1, child2])
        )

        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(b) '
            'WHERE b.name CONTAINS "Alpha" RETURN b'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["b"]) == 1
        assert result.results["b"][0].name == "Alpha Child"

    @pytest.mark.asyncio
    async def test_cross_variable_or_rejected(self) -> None:
        """OR across different variables should produce an error."""
        api = _mock_api()

        q = parse(
            'MATCH (a)-[:CHILD]->(b) '
            'WHERE a.name = "X" OR b.name = "Y" RETURN b'
        )
        result = await execute(api, "brain", q)

        assert not result.success
        assert any("OR across different variables" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_parens_and_or_mixed(self) -> None:
        """(A OR B) AND C evaluates correctly."""
        api = _mock_api()
        t1 = _thought("t1", "MCP Server Alpha")
        t2 = _thought("t2", "MCP Client Alpha")
        t3 = _thought("t3", "MCP Server Beta")
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t1), _search_result(t2), _search_result(t3),
        ])

        q = parse(
            'MATCH (n) WHERE (n.name CONTAINS "Server" OR n.name CONTAINS "Client") '
            'AND n.name CONTAINS "Alpha" RETURN n'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 2
        names = {r.name for r in result.results["n"]}
        assert names == {"MCP Server Alpha", "MCP Client Alpha"}

    @pytest.mark.asyncio
    async def test_or_deduplicates(self) -> None:
        """OR unions should not produce duplicate results."""
        api = _mock_api()
        t1 = _thought("t1", "MCP Server")
        # Both OR branches could match the same thought
        api.search_thoughts = AsyncMock(return_value=[_search_result(t1)])

        q = parse(
            'MATCH (n) WHERE n.name CONTAINS "MCP" OR n.name CONTAINS "Server" RETURN n'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1

    @pytest.mark.asyncio
    async def test_not_in_chain_filters(self) -> None:
        """NOT on a traversal target filters out matching results."""
        api = _mock_api()
        root = _thought("r1", "Root")
        child1 = _thought("c1", "Kelsey")
        child2 = _thought("c2", "Meagan")
        child3 = _thought("c3", "Other")
        api.get_thought_by_name = AsyncMock(return_value=root)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(root, children=[child1, child2, child3])
        )

        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(p) '
            'WHERE NOT p.name =~ "Kelsey" RETURN p'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["p"]) == 2
        names = {r.name for r in result.results["p"]}
        assert names == {"Meagan", "Other"}

    @pytest.mark.asyncio
    async def test_bare_not_on_typed_traversal_target(self) -> None:
        """Bare NOT on a typed traversal target should filter chain candidates."""
        api = _mock_api()
        root = _thought("r1", "Root")
        person_type = _thought("type-person", "Person")
        child1 = _thought("c1", "Kelsey", type_id="type-person")
        child2 = _thought("c2", "Meagan", type_id="type-person")
        child3 = _thought("c3", "Other", type_id="type-person")
        api.get_thought_by_name = AsyncMock(return_value=root)
        api.get_types = AsyncMock(return_value=[person_type])
        api.get_thought_graph = AsyncMock(
            return_value=_graph(root, children=[child1, child2, child3])
        )

        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(p:Person) '
            'WHERE NOT p.name =~ "Kelsey" RETURN p'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["p"]) == 2
        names = {r.name for r in result.results["p"]}
        assert names == {"Meagan", "Other"}

    @pytest.mark.asyncio
    async def test_bare_not_on_non_traversal_target_rejected(self) -> None:
        """Bare NOT on a non-traversal node should still be rejected."""
        api = _mock_api()
        person_type = _thought("type-person", "Person")
        api.get_types = AsyncMock(return_value=[person_type])
        api.get_thought = AsyncMock(return_value=person_type)

        q = parse('MATCH (p:Person) WHERE NOT p.name =~ "Kelsey" RETURN p')
        result = await execute(api, "brain", q)

        assert not result.success
        assert any("NOT requires" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_multiple_nots_on_traversal_target(self) -> None:
        """Multiple NOTs via AND on a traversal target should work."""
        api = _mock_api()
        root = _thought("r1", "Root")
        child1 = _thought("c1", "Kelsey")
        child2 = _thought("c2", "Meagan")
        child3 = _thought("c3", "Other")
        api.get_thought_by_name = AsyncMock(return_value=root)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(root, children=[child1, child2, child3])
        )

        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(p) '
            'WHERE NOT p.name =~ "Kelsey" AND NOT p.name =~ "Meagan" RETURN p'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["p"]) == 1
        assert result.results["p"][0].name == "Other"

    @pytest.mark.asyncio
    async def test_not_on_multihop_terminal(self) -> None:
        """NOT on the terminal node of a multi-hop chain should work."""
        api = _mock_api()
        root = _thought("r1", "Root")
        mid = _thought("m1", "Middle")
        leaf1 = _thought("l1", "Keep")
        leaf2 = _thought("l2", "Remove")
        api.get_thought_by_name = AsyncMock(return_value=root)

        async def graph_lookup(brain_id, thought_id):
            if thought_id == "r1":
                return _graph(root, children=[mid])
            if thought_id == "m1":
                return _graph(mid, children=[leaf1, leaf2])
            return _graph(_thought(thought_id, "X"))
        api.get_thought_graph = AsyncMock(side_effect=graph_lookup)

        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(b)-[:CHILD]->(c) '
            'WHERE NOT c.name = "Remove" RETURN c'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["c"]) == 1
        assert result.results["c"][0].name == "Keep"

    @pytest.mark.asyncio
    async def test_double_not_on_traversal_target(self) -> None:
        """NOT NOT on a traversal target: double negation = positive."""
        api = _mock_api()
        root = _thought("r1", "Root")
        child1 = _thought("c1", "Kelsey")
        child2 = _thought("c2", "Meagan")
        child3 = _thought("c3", "Other")
        api.get_thought_by_name = AsyncMock(return_value=root)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(root, children=[child1, child2, child3])
        )

        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(p) '
            'WHERE NOT NOT p.name =~ "Kelsey" RETURN p'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["p"]) == 1
        assert result.results["p"][0].name == "Kelsey"

    @pytest.mark.asyncio
    async def test_not_with_and_positive(self) -> None:
        """AND with NOT: positive clause drives search, NOT post-filters."""
        api = _mock_api()
        t1 = _thought("t1", "Lonnie VanZandt")
        t2 = _thought("t2", "Lonnie VanZandt Jr")
        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t1), _search_result(t2),
        ])

        q = parse(
            'MATCH (n) WHERE n.name =~ "Lonnie" AND NOT n.name CONTAINS "Jr" RETURN n'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 1
        assert result.results["n"][0].name == "Lonnie VanZandt"

    @pytest.mark.asyncio
    async def test_not_alone_on_unconstrained_rejected(self) -> None:
        """NOT as sole constraint on a direct-resolve node should error."""
        api = _mock_api()

        q = parse('MATCH (n) WHERE NOT n.name = "X" RETURN n')
        result = await execute(api, "brain", q)

        assert not result.success
        assert any("NOT requires" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_not_parenthesized_or(self) -> None:
        """NOT (A OR B) excludes both."""
        api = _mock_api()
        root = _thought("r1", "Root")
        child1 = _thought("c1", "Kelsey")
        child2 = _thought("c2", "Meagan")
        child3 = _thought("c3", "Other")
        api.get_thought_by_name = AsyncMock(return_value=root)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(root, children=[child1, child2, child3])
        )

        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(p) '
            'WHERE NOT (p.name =~ "Kelsey" OR p.name =~ "Meagan") RETURN p'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["p"]) == 1
        assert result.results["p"][0].name == "Other"

    @pytest.mark.asyncio
    async def test_xor_symmetric_difference(self) -> None:
        """XOR returns results in exactly one branch."""
        api = _mock_api()
        t1 = _thought("t1", "Kelsey VanZandt")
        t2 = _thought("t2", "Meagan VanZandt")
        t3 = _thought("t3", "Kelsey Meagan")  # matches both → excluded

        api.search_thoughts = AsyncMock(return_value=[
            _search_result(t1), _search_result(t2), _search_result(t3),
        ])

        q = parse(
            'MATCH (n) WHERE n.name CONTAINS "Kelsey" XOR n.name CONTAINS "Meagan" RETURN n'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["n"]) == 2
        names = {r.name for r in result.results["n"]}
        assert names == {"Kelsey VanZandt", "Meagan VanZandt"}

    @pytest.mark.asyncio
    async def test_cross_variable_xor_rejected(self) -> None:
        """XOR across different variables should produce an error."""
        api = _mock_api()

        q = parse(
            'MATCH (a)-[:CHILD]->(b) '
            'WHERE a.name = "X" XOR b.name = "Y" RETURN b'
        )
        result = await execute(api, "brain", q)

        assert not result.success
        assert any("XOR across different variables" in e for e in result.errors)


# ---------------------------------------------------------------------------
# MATCH: IS NULL / IS NOT NULL
# ---------------------------------------------------------------------------


class TestExistenceChecks:
    @pytest.mark.asyncio
    async def test_is_not_null_filters_on_traversal(self) -> None:
        """IS NOT NULL on a traversal target filters candidates with null values."""
        api = _mock_api()
        parent = _thought("p1", "Parent")
        child_with_label = _thought("c1", "Child A")
        child_with_label.label = "Has a label"
        child_no_label = _thought("c2", "Child B")
        child_no_label.label = None
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[child_with_label, child_no_label])
        )

        q = parse(
            'MATCH (a {name: "Parent"})-[:CHILD]->(c) '
            'WHERE c.label IS NOT NULL RETURN c'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["c"]) == 1
        assert result.results["c"][0].name == "Child A"

    @pytest.mark.asyncio
    async def test_is_null_filters_on_traversal(self) -> None:
        """IS NULL on a traversal target returns candidates where property is null."""
        api = _mock_api()
        parent = _thought("p1", "Parent")
        child_typed = _thought("c1", "Typed", type_id="type-1")
        child_untyped = _thought("c2", "Untyped")
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[child_typed, child_untyped])
        )

        q = parse(
            'MATCH (a {name: "Parent"})-[:CHILD]->(c) '
            'WHERE c.typeId IS NULL RETURN c'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["c"]) == 1
        assert result.results["c"][0].name == "Untyped"

    @pytest.mark.asyncio
    async def test_existence_combined_with_name(self) -> None:
        """IS NOT NULL combined with name condition via AND."""
        api = _mock_api()
        parent = _thought("p1", "Parent")
        c1 = _thought("c1", "Alice")
        c1.label = "Person"
        c2 = _thought("c2", "Bob")
        c2.label = None
        c3 = _thought("c3", "Alice Clone")
        c3.label = None  # No label — filtered by IS NOT NULL
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[c1, c2, c3])
        )

        q = parse(
            'MATCH (a {name: "Parent"})-[:CHILD]->(c) '
            'WHERE c.label IS NOT NULL AND c.name STARTS WITH "Ali" RETURN c'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["c"]) == 1
        assert result.results["c"][0].name == "Alice"

    @pytest.mark.asyncio
    async def test_existence_alone_on_non_traversal_rejected(self) -> None:
        """IS NULL as sole constraint on non-traversal node should error."""
        api = _mock_api()

        q = parse('MATCH (n) WHERE n.label IS NULL RETURN n')
        result = await execute(api, "brain", q)

        assert not result.success
        assert any("IS NULL" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_name_is_null_returns_empty(self) -> None:
        """name IS NULL on traversal target should return empty (name is never null)."""
        api = _mock_api()
        parent = _thought("p1", "Parent")
        child = _thought("c1", "Child")
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[child])
        )

        q = parse(
            'MATCH (a {name: "Parent"})-[:CHILD]->(c) '
            'WHERE c.name IS NULL RETURN c'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["c"]) == 0

    @pytest.mark.asyncio
    async def test_name_is_not_null_returns_all(self) -> None:
        """name IS NOT NULL on traversal target returns all (name is never null)."""
        api = _mock_api()
        parent = _thought("p1", "Parent")
        c1 = _thought("c1", "Child A")
        c2 = _thought("c2", "Child B")
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[c1, c2])
        )

        q = parse(
            'MATCH (a {name: "Parent"})-[:CHILD]->(c) '
            'WHERE c.name IS NOT NULL RETURN c'
        )
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.results["c"]) == 2


# ---------------------------------------------------------------------------
# CREATE: standalone
# ---------------------------------------------------------------------------


class TestCreateStandalone:
    @pytest.mark.asyncio
    async def test_create_untyped(self) -> None:
        api = _mock_api()

        q = parse('CREATE (n {name: "New Idea"})')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.created) == 1
        assert result.created[0]["name"] == "New Idea"
        assert result.created[0]["type"] == "thought"
        api.create_thought.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_typed(self) -> None:
        api = _mock_api()
        concept_type = _thought("type-concept", "Concept", brain_id="brain")
        api.get_types = AsyncMock(return_value=[concept_type])

        q = parse('CREATE (n:Concept {name: "New Idea"})')
        result = await execute(api, "brain", q)

        assert result.success
        assert result.created[0]["typeId"] == "type-concept"


# ---------------------------------------------------------------------------
# MATCH + CREATE
# ---------------------------------------------------------------------------


class TestMatchCreate:
    @pytest.mark.asyncio
    async def test_create_child_of_existing(self) -> None:
        api = _mock_api()
        parent = _thought("p1", "Projects")
        api.get_thought_by_name = AsyncMock(return_value=parent)

        q = parse('MATCH (p {name: "Projects"}) CREATE (p)-[:CHILD]->(n {name: "New Project"})')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.created) == 1
        assert result.created[0]["name"] == "New Project"
        assert result.created[0]["parent"] == "Projects"
        assert result.created[0]["relation"] == "CHILD"
        api.create_thought.assert_called_once()
        call_args = api.create_thought.call_args[0]
        assert call_args[1]["sourceThoughtId"] == "p1"
        assert call_args[1]["relation"] == 1

    @pytest.mark.asyncio
    async def test_create_link_between_existing(self) -> None:
        api = _mock_api()
        alice = _thought("a1", "Alice")
        bob = _thought("b1", "Bob")

        call_count = 0
        async def name_lookup(brain_id, name):
            nonlocal call_count
            call_count += 1
            if name == "Alice":
                return alice
            if name == "Bob":
                return bob
            return None
        api.get_thought_by_name = AsyncMock(side_effect=name_lookup)

        q = parse('MATCH (a {name: "Alice"}), (b {name: "Bob"}) CREATE (a)-[:JUMP]->(b)')
        result = await execute(api, "brain", q)

        assert result.success
        assert len(result.created) == 1
        assert result.created[0]["type"] == "link"
        assert result.created[0]["relation"] == "JUMP"
        api.create_link.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_fails_when_source_not_found(self) -> None:
        api = _mock_api()

        q = parse('MATCH (p {name: "Missing"}) CREATE (p)-[:CHILD]->(n {name: "Orphan"})')
        result = await execute(api, "brain", q)

        assert not result.success
        assert any("Could not resolve" in e for e in result.errors)
        api.create_thought.assert_not_called()


# ---------------------------------------------------------------------------
# Return field filtering
# ---------------------------------------------------------------------------


class TestReturnFields:
    @pytest.mark.asyncio
    async def test_returns_only_requested_variable(self) -> None:
        api = _mock_api()
        parent = _thought("p1", "Parent")
        child = _thought("c1", "Child")
        api.get_thought_by_name = AsyncMock(return_value=parent)
        api.get_thought_graph = AsyncMock(
            return_value=_graph(parent, children=[child])
        )

        q = parse('MATCH (n {name: "Parent"})-[:CHILD]->(m) RETURN m')
        result = await execute(api, "brain", q)

        assert "m" in result.results
        assert "n" not in result.results  # n not in RETURN


# ---------------------------------------------------------------------------
# QueryResult serialization
# ---------------------------------------------------------------------------


class TestQueryResultDict:
    @pytest.mark.asyncio
    async def test_to_dict(self) -> None:
        api = _mock_api()
        t = _thought("t1", "Test")
        api.get_thought_by_name = AsyncMock(return_value=t)

        q = parse('MATCH (n {name: "Test"}) RETURN n')
        result = await execute(api, "brain", q)
        d = result.to_dict()

        assert d["success"] is True
        assert d["action"] == "match"
        assert len(d["results"]["n"]) == 1
        assert d["results"]["n"][0]["id"] == "t1"
        assert d["results"]["n"][0]["name"] == "Test"
