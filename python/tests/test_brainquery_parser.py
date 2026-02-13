"""Tests for BrainQuery parser."""

import pytest

from thebrain_mcp.brainquery import (
    BrainQuery,
    NodePattern,
    RelPattern,
    WhereClause,
    parse,
)
from thebrain_mcp.brainquery.ir import ReturnField
from thebrain_mcp.brainquery.parser import BrainQuerySyntaxError


# ---------------------------------------------------------------------------
# Simple node MATCH patterns
# ---------------------------------------------------------------------------


class TestMatchNodePatterns:
    def test_match_by_name(self) -> None:
        q = parse('MATCH (n {name: "Claude Thoughts"}) RETURN n')
        assert q.action == "match"
        assert len(q.nodes) == 1
        assert q.nodes[0].variable == "n"
        assert q.nodes[0].properties == {"name": "Claude Thoughts"}
        assert q.nodes[0].label is None

    def test_match_by_type(self) -> None:
        q = parse("MATCH (n:Person) RETURN n")
        assert q.nodes[0].label == "Person"
        assert q.nodes[0].properties == {}

    def test_match_by_type_and_name(self) -> None:
        q = parse('MATCH (p:Person {name: "Lonnie VanZandt"}) RETURN p')
        assert q.nodes[0].variable == "p"
        assert q.nodes[0].label == "Person"
        assert q.nodes[0].properties == {"name": "Lonnie VanZandt"}

    def test_match_bare_variable(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "test" RETURN n')
        assert q.nodes[0].variable == "n"
        assert q.nodes[0].label is None
        assert q.nodes[0].properties == {}

    def test_multiword_type_label(self) -> None:
        q = parse("MATCH (n:Team Activity) RETURN n")
        assert q.nodes[0].label == "Team Activity"


# ---------------------------------------------------------------------------
# Relationship traversal
# ---------------------------------------------------------------------------


class TestMatchRelationships:
    def test_child_traversal(self) -> None:
        q = parse('MATCH (n {name: "My Thoughts"})-[:CHILD]->(m) RETURN m')
        assert len(q.nodes) == 2
        assert len(q.relationships) == 1
        rel = q.relationships[0]
        assert rel.rel_type == "CHILD"
        assert rel.source == "n"
        assert rel.target == "m"

    def test_parent_traversal(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:PARENT]->(p) RETURN p')
        assert q.relationships[0].rel_type == "PARENT"

    def test_jump_traversal(self) -> None:
        q = parse('MATCH (n {name: "A"})-[:JUMP]->(j) RETURN j')
        assert q.relationships[0].rel_type == "JUMP"

    def test_sibling_traversal(self) -> None:
        q = parse('MATCH (n {name: "T1"})-[:SIBLING]->(s) RETURN s')
        assert q.relationships[0].rel_type == "SIBLING"

    def test_case_insensitive_rel_type(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:child]->(m) RETURN m')
        assert q.relationships[0].rel_type == "CHILD"


# ---------------------------------------------------------------------------
# WHERE clause
# ---------------------------------------------------------------------------


class TestWhereClause:
    def test_where_equals(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "Claude Thoughts" RETURN n')
        assert len(q.where_clauses) == 1
        w = q.where_clauses[0]
        assert w.variable == "n"
        assert w.field == "name"
        assert w.operator == "="
        assert w.value == "Claude Thoughts"

    def test_where_contains(self) -> None:
        q = parse('MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n')
        w = q.where_clauses[0]
        assert w.operator == "CONTAINS"
        assert w.value == "MCP"

    def test_where_with_typed_node(self) -> None:
        q = parse('MATCH (n:Person) WHERE n.name CONTAINS "Van" RETURN n')
        assert q.nodes[0].label == "Person"
        assert q.where_clauses[0].value == "Van"

    def test_case_insensitive_contains(self) -> None:
        q = parse('MATCH (n) WHERE n.name contains "test" RETURN n')
        assert q.where_clauses[0].operator == "CONTAINS"


# ---------------------------------------------------------------------------
# RETURN clause
# ---------------------------------------------------------------------------


class TestReturnClause:
    def test_return_variable(self) -> None:
        q = parse('MATCH (n {name: "X"}) RETURN n')
        assert len(q.return_fields) == 1
        assert q.return_fields[0].variable == "n"
        assert q.return_fields[0].field is None

    def test_return_name_field(self) -> None:
        q = parse('MATCH (n {name: "X"}) RETURN n.name')
        assert q.return_fields[0].field == "name"

    def test_return_id_field(self) -> None:
        q = parse('MATCH (n {name: "X"}) RETURN n.id')
        assert q.return_fields[0].field == "id"

    def test_return_multiple(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(m) RETURN n, m')
        assert len(q.return_fields) == 2
        assert q.return_fields[0].variable == "n"
        assert q.return_fields[1].variable == "m"

    def test_return_mixed_fields(self) -> None:
        q = parse('MATCH (n {name: "X"}) RETURN n.name, n.id')
        assert q.return_fields[0].field == "name"
        assert q.return_fields[1].field == "id"


# ---------------------------------------------------------------------------
# CREATE queries
# ---------------------------------------------------------------------------


class TestCreateQueries:
    def test_create_standalone(self) -> None:
        q = parse('CREATE (n {name: "New Idea"})')
        assert q.action == "create"
        assert len(q.nodes) == 1
        assert q.nodes[0].properties == {"name": "New Idea"}

    def test_create_typed(self) -> None:
        q = parse('CREATE (n:Concept {name: "New Idea"})')
        assert q.nodes[0].label == "Concept"
        assert q.nodes[0].properties == {"name": "New Idea"}

    def test_create_with_relationship(self) -> None:
        q = parse('CREATE (n)-[:CHILD]->(m {name: "New Child"})')
        assert q.action == "create"
        assert len(q.nodes) == 2
        assert len(q.relationships) == 1
        assert q.relationships[0].rel_type == "CHILD"


# ---------------------------------------------------------------------------
# MATCH + CREATE (match_create)
# ---------------------------------------------------------------------------


class TestMatchCreateQueries:
    def test_match_create_child(self) -> None:
        q = parse('MATCH (p {name: "Projects"}) CREATE (p)-[:CHILD]->(n {name: "New Project"})')
        assert q.action == "match_create"
        assert len(q.nodes) == 2
        assert q.nodes[0].properties == {"name": "Projects"}
        assert q.nodes[1].properties == {"name": "New Project"}
        assert q.relationships[0].rel_type == "CHILD"
        assert q.relationships[0].source == "p"
        assert q.relationships[0].target == "n"

    def test_match_create_typed(self) -> None:
        q = parse('MATCH (p {name: "Projects"}) CREATE (p)-[:CHILD]->(n:Concept {name: "Idea"})')
        assert q.nodes[1].label == "Concept"

    def test_match_two_create_link(self) -> None:
        q = parse('MATCH (a {name: "Alice"}), (b {name: "Bob"}) CREATE (a)-[:JUMP]->(b)')
        assert q.action == "match_create"
        assert len(q.nodes) == 2
        assert q.nodes[0].properties == {"name": "Alice"}
        assert q.nodes[1].properties == {"name": "Bob"}
        assert q.relationships[0].rel_type == "JUMP"

    def test_match_create_sibling(self) -> None:
        q = parse('MATCH (a {name: "T1"}), (b {name: "T2"}) CREATE (a)-[:SIBLING]->(b)')
        assert q.relationships[0].rel_type == "SIBLING"


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


class TestCaseInsensitivity:
    def test_lowercase_match(self) -> None:
        q = parse('match (n {name: "X"}) return n')
        assert q.action == "match"

    def test_mixed_case(self) -> None:
        q = parse('Match (n {name: "X"}) Return n')
        assert q.action == "match"

    def test_lowercase_create(self) -> None:
        q = parse('create (n {name: "X"})')
        assert q.action == "create"

    def test_lowercase_where(self) -> None:
        q = parse('MATCH (n) where n.name = "X" RETURN n')
        assert q.where_clauses[0].value == "X"


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


class TestComments:
    def test_line_comment_ignored(self) -> None:
        q = parse('-- find by name\nMATCH (n {name: "X"}) RETURN n')
        assert q.nodes[0].properties == {"name": "X"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_empty_query(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Empty query"):
            parse("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Empty query"):
            parse("   ")

    def test_unsupported_delete(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="DELETE.*not supported"):
            parse('DELETE (n {name: "X"})')

    def test_unsupported_set(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="SET.*not supported"):
            parse('MATCH (n {name: "X"}) SET n.name = "Y"')

    def test_unsupported_merge(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="MERGE.*not supported"):
            parse('MERGE (n {name: "X"})')

    def test_unsupported_optional(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="OPTIONAL.*not supported"):
            parse('OPTIONAL MATCH (n {name: "X"}) RETURN n')

    def test_unsupported_variable_length_path(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Variable-length"):
            parse('MATCH (n)-[*1..3]->(m) RETURN m')

    def test_invalid_syntax(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Syntax error|Failed to parse"):
            parse("THIS IS NOT VALID")

    def test_missing_return(self) -> None:
        with pytest.raises(BrainQuerySyntaxError):
            parse('MATCH (n {name: "X"})')

    def test_unknown_rel_type(self) -> None:
        with pytest.raises(BrainQuerySyntaxError):
            parse('MATCH (n)-[:KNOWS]->(m) RETURN m')


# ---------------------------------------------------------------------------
# IR structure verification
# ---------------------------------------------------------------------------


class TestIRStructure:
    def test_brainquery_fields(self) -> None:
        q = parse('MATCH (n:Person {name: "X"}) WHERE n.name CONTAINS "Y" RETURN n.name, n.id')
        assert isinstance(q, BrainQuery)
        assert isinstance(q.nodes[0], NodePattern)
        assert isinstance(q.where_clauses[0], WhereClause)
        assert isinstance(q.return_fields[0], ReturnField)

    def test_no_duplicate_nodes(self) -> None:
        """When a variable appears in both MATCH and CREATE, it should only be in nodes once."""
        q = parse('MATCH (p {name: "Parent"}) CREATE (p)-[:CHILD]->(c {name: "Child"})')
        var_names = [n.variable for n in q.nodes]
        assert var_names == ["p", "c"]  # p not duplicated
