"""Tests for BrainQuery parser."""

import pytest

from thebrain_mcp.brainquery import (
    BrainQuery,
    ExistenceCondition,
    NodePattern,
    RelPattern,
    WhereAnd,
    WhereClause,
    WhereNot,
    WhereOr,
    WhereXor,
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
# Multi-hop chains
# ---------------------------------------------------------------------------


class TestMultiHopChains:
    def test_two_hop_chain(self) -> None:
        q = parse('MATCH (a {name: "Root"})-[:CHILD]->(b)-[:CHILD]->(c) RETURN c')
        assert len(q.nodes) == 3
        assert len(q.relationships) == 2
        assert q.relationships[0].source == "a"
        assert q.relationships[0].target == "b"
        assert q.relationships[1].source == "b"
        assert q.relationships[1].target == "c"

    def test_three_hop_chain(self) -> None:
        q = parse('MATCH (a {name: "R"})-[:CHILD]->(b)-[:JUMP]->(c)-[:PARENT]->(d) RETURN d')
        assert len(q.nodes) == 4
        assert len(q.relationships) == 3
        assert q.relationships[0].rel_type == "CHILD"
        assert q.relationships[1].rel_type == "JUMP"
        assert q.relationships[2].rel_type == "PARENT"

    def test_intermediate_variables_bindable(self) -> None:
        q = parse('MATCH (a {name: "R"})-[:CHILD]->(b)-[:CHILD]->(c) RETURN b, c')
        assert len(q.return_fields) == 2
        assert q.return_fields[0].variable == "b"
        assert q.return_fields[1].variable == "c"

    def test_chain_no_duplicate_nodes(self) -> None:
        q = parse('MATCH (a {name: "R"})-[:CHILD]->(b)-[:CHILD]->(c) RETURN c')
        var_names = [n.variable for n in q.nodes]
        assert var_names == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Variable-length paths
# ---------------------------------------------------------------------------


class TestVariableLengthPaths:
    def test_fixed_hops(self) -> None:
        q = parse('MATCH (n {name: "Root"})-[:CHILD*2]->(m) RETURN m')
        assert len(q.relationships) == 1
        assert q.relationships[0].min_hops == 2
        assert q.relationships[0].max_hops == 2

    def test_range_hops(self) -> None:
        q = parse('MATCH (n {name: "Root"})-[:CHILD*1..3]->(m) RETURN m')
        assert q.relationships[0].min_hops == 1
        assert q.relationships[0].max_hops == 3

    def test_single_hop_default(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(m) RETURN m')
        assert q.relationships[0].min_hops == 1
        assert q.relationships[0].max_hops == 1

    def test_rejects_unbounded_star(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Unbounded"):
            parse('MATCH (n)-[:CHILD*]->(m) RETURN m')

    def test_rejects_unbounded_range(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Unbounded"):
            parse('MATCH (n)-[:CHILD*2..]->(m) RETURN m')

    def test_rejects_exceeding_max_depth(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Maximum hop depth"):
            parse('MATCH (n {name: "R"})-[:CHILD*1..10]->(m) RETURN m')

    def test_rejects_min_greater_than_max(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="must be >="):
            parse('MATCH (n {name: "R"})-[:CHILD*3..1]->(m) RETURN m')

    def test_variable_length_with_chain(self) -> None:
        q = parse('MATCH (a {name: "R"})-[:CHILD*2]->(b)-[:JUMP]->(c) RETURN c')
        assert q.relationships[0].min_hops == 2
        assert q.relationships[0].max_hops == 2
        assert q.relationships[1].min_hops == 1
        assert q.relationships[1].max_hops == 1


# ---------------------------------------------------------------------------
# WHERE clause
# ---------------------------------------------------------------------------


class TestWhereClause:
    def test_where_equals(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "Claude Thoughts" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        w = q.where_expr
        assert w.variable == "n"
        assert w.field == "name"
        assert w.operator == "="
        assert w.value == "Claude Thoughts"

    def test_where_contains(self) -> None:
        q = parse('MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "CONTAINS"
        assert q.where_expr.value == "MCP"

    def test_where_with_typed_node(self) -> None:
        q = parse('MATCH (n:Person) WHERE n.name CONTAINS "Van" RETURN n')
        assert q.nodes[0].label == "Person"
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.value == "Van"

    def test_case_insensitive_contains(self) -> None:
        q = parse('MATCH (n) WHERE n.name contains "test" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "CONTAINS"

    def test_starts_with(self) -> None:
        q = parse('MATCH (n) WHERE n.name STARTS WITH "MCP" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "STARTS WITH"
        assert q.where_expr.value == "MCP"

    def test_ends_with(self) -> None:
        q = parse('MATCH (n) WHERE n.name ENDS WITH "Server" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "ENDS WITH"
        assert q.where_expr.value == "Server"

    def test_similar(self) -> None:
        q = parse('MATCH (n) WHERE n.name =~ "Claude" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "=~"
        assert q.where_expr.value == "Claude"

    def test_case_insensitive_starts_with(self) -> None:
        q = parse('MATCH (n) WHERE n.name starts with "X" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "STARTS WITH"

    def test_case_insensitive_ends_with(self) -> None:
        q = parse('MATCH (n) WHERE n.name ends with "X" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "ENDS WITH"


# ---------------------------------------------------------------------------
# Compound WHERE (AND / OR)
# ---------------------------------------------------------------------------


class TestCompoundWhere:
    def test_single_condition_backward_compat(self) -> None:
        """A single WHERE condition produces a plain WhereClause, not WhereAnd/Or."""
        q = parse('MATCH (n) WHERE n.name = "X" RETURN n')
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.operator == "="

    def test_two_condition_and(self) -> None:
        q = parse('MATCH (n) WHERE n.name CONTAINS "A" AND n.name CONTAINS "B" RETURN n')
        assert isinstance(q.where_expr, WhereAnd)
        assert len(q.where_expr.operands) == 2
        assert all(isinstance(op, WhereClause) for op in q.where_expr.operands)
        assert q.where_expr.operands[0].value == "A"
        assert q.where_expr.operands[1].value == "B"

    def test_three_condition_and(self) -> None:
        q = parse(
            'MATCH (n) WHERE n.name CONTAINS "A" AND n.name CONTAINS "B" '
            'AND n.name CONTAINS "C" RETURN n'
        )
        assert isinstance(q.where_expr, WhereAnd)
        assert len(q.where_expr.operands) == 3

    def test_two_condition_or(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "A" OR n.name = "B" RETURN n')
        assert isinstance(q.where_expr, WhereOr)
        assert len(q.where_expr.operands) == 2
        assert q.where_expr.operands[0].value == "A"
        assert q.where_expr.operands[1].value == "B"

    def test_precedence_and_binds_tighter(self) -> None:
        """A OR B AND C → WhereOr([A, WhereAnd([B, C])])"""
        q = parse(
            'MATCH (n) WHERE n.name = "A" OR n.name = "B" AND n.name = "C" RETURN n'
        )
        assert isinstance(q.where_expr, WhereOr)
        assert len(q.where_expr.operands) == 2
        assert isinstance(q.where_expr.operands[0], WhereClause)
        assert q.where_expr.operands[0].value == "A"
        assert isinstance(q.where_expr.operands[1], WhereAnd)
        assert len(q.where_expr.operands[1].operands) == 2

    def test_parens_override_precedence(self) -> None:
        """(A OR B) AND C → WhereAnd([WhereOr([A, B]), C])"""
        q = parse(
            'MATCH (n) WHERE (n.name = "A" OR n.name = "B") AND n.name = "C" RETURN n'
        )
        assert isinstance(q.where_expr, WhereAnd)
        assert len(q.where_expr.operands) == 2
        assert isinstance(q.where_expr.operands[0], WhereOr)
        assert isinstance(q.where_expr.operands[1], WhereClause)

    def test_nested_parens(self) -> None:
        """((A AND B) OR C)"""
        q = parse(
            'MATCH (n) WHERE (n.name CONTAINS "A" AND n.name CONTAINS "B") '
            'OR n.name = "C" RETURN n'
        )
        assert isinstance(q.where_expr, WhereOr)
        assert isinstance(q.where_expr.operands[0], WhereAnd)
        assert isinstance(q.where_expr.operands[1], WhereClause)

    def test_case_insensitive_and(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "A" and n.name = "B" RETURN n')
        assert isinstance(q.where_expr, WhereAnd)

    def test_case_insensitive_or(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "A" or n.name = "B" RETURN n')
        assert isinstance(q.where_expr, WhereOr)

    def test_multi_variable_and(self) -> None:
        """AND across different variables is allowed."""
        q = parse(
            'MATCH (a {name: "Root"})-[:CHILD]->(b) '
            'WHERE a.name = "Root" AND b.name CONTAINS "X" RETURN b'
        )
        assert isinstance(q.where_expr, WhereAnd)
        assert len(q.where_expr.operands) == 2
        assert q.where_expr.operands[0].variable == "a"
        assert q.where_expr.operands[1].variable == "b"

    def test_not(self) -> None:
        q = parse('MATCH (n) WHERE NOT n.name = "X" RETURN n')
        assert isinstance(q.where_expr, WhereNot)
        assert isinstance(q.where_expr.operand, WhereClause)
        assert q.where_expr.operand.value == "X"

    def test_double_not(self) -> None:
        q = parse('MATCH (n) WHERE NOT NOT n.name = "X" RETURN n')
        assert isinstance(q.where_expr, WhereNot)
        assert isinstance(q.where_expr.operand, WhereNot)
        assert isinstance(q.where_expr.operand.operand, WhereClause)

    def test_not_with_and(self) -> None:
        """n.name =~ "Lonnie" AND NOT n.name CONTAINS "Jr" """
        q = parse(
            'MATCH (n) WHERE n.name =~ "Lonnie" AND NOT n.name CONTAINS "Jr" RETURN n'
        )
        assert isinstance(q.where_expr, WhereAnd)
        assert isinstance(q.where_expr.operands[0], WhereClause)
        assert isinstance(q.where_expr.operands[1], WhereNot)

    def test_not_with_parens(self) -> None:
        """NOT (A OR B)"""
        q = parse(
            'MATCH (n) WHERE NOT (n.name = "A" OR n.name = "B") RETURN n'
        )
        assert isinstance(q.where_expr, WhereNot)
        assert isinstance(q.where_expr.operand, WhereOr)

    def test_case_insensitive_not(self) -> None:
        q = parse('MATCH (n) WHERE not n.name = "X" RETURN n')
        assert isinstance(q.where_expr, WhereNot)

    def test_xor(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "A" XOR n.name = "B" RETURN n')
        assert isinstance(q.where_expr, WhereXor)
        assert len(q.where_expr.operands) == 2

    def test_case_insensitive_xor(self) -> None:
        q = parse('MATCH (n) WHERE n.name = "A" xor n.name = "B" RETURN n')
        assert isinstance(q.where_expr, WhereXor)

    def test_xor_precedence(self) -> None:
        """A OR B XOR C → WhereOr([A, WhereXor([B, C])])"""
        q = parse(
            'MATCH (n) WHERE n.name = "A" OR n.name = "B" XOR n.name = "C" RETURN n'
        )
        assert isinstance(q.where_expr, WhereOr)
        assert isinstance(q.where_expr.operands[0], WhereClause)
        assert isinstance(q.where_expr.operands[1], WhereXor)

    def test_full_precedence_not_and_xor_or(self) -> None:
        """NOT A AND B XOR C OR D parses as ((NOT A AND B) XOR C) OR D
        Actually: NOT > AND > XOR > OR so:
        NOT A AND B → WhereAnd([WhereNot(A), B])
        (WhereAnd([WhereNot(A), B])) XOR C → WhereXor([WhereAnd(...), C])
        WhereXor(...) OR D → WhereOr([WhereXor(...), D])
        """
        q = parse(
            'MATCH (n) WHERE NOT n.name = "A" AND n.name = "B" '
            'XOR n.name = "C" OR n.name = "D" RETURN n'
        )
        assert isinstance(q.where_expr, WhereOr)
        assert isinstance(q.where_expr.operands[1], WhereClause)  # D
        xor = q.where_expr.operands[0]
        assert isinstance(xor, WhereXor)
        assert isinstance(xor.operands[1], WhereClause)  # C
        and_expr = xor.operands[0]
        assert isinstance(and_expr, WhereAnd)
        assert isinstance(and_expr.operands[0], WhereNot)  # NOT A
        assert isinstance(and_expr.operands[1], WhereClause)  # B


# ---------------------------------------------------------------------------
# IS NULL / IS NOT NULL
# ---------------------------------------------------------------------------


class TestIsNullParsing:
    def test_is_null(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.label IS NULL RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.variable == "c"
        assert q.where_expr.property == "label"
        assert q.where_expr.negated is False

    def test_is_not_null(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.label IS NOT NULL RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.variable == "c"
        assert q.where_expr.property == "label"
        assert q.where_expr.negated is True

    def test_typeid_property(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.typeId IS NULL RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.property == "typeId"

    def test_case_insensitive_property(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.typeid IS NOT NULL RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.property == "typeId"

    def test_foreground_color_property(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.foregroundColor IS NOT NULL RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.property == "foregroundColor"

    def test_combined_with_name_condition(self) -> None:
        q = parse(
            'MATCH (n {name: "X"})-[:CHILD]->(c) '
            'WHERE c.label IS NOT NULL AND c.name =~ "Y" RETURN c'
        )
        assert isinstance(q.where_expr, WhereAnd)
        assert isinstance(q.where_expr.operands[0], ExistenceCondition)
        assert isinstance(q.where_expr.operands[1], WhereClause)

    def test_case_insensitive_is_null(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.label is null RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.negated is False

    def test_case_insensitive_is_not_null(self) -> None:
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.label is not null RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.negated is True

    def test_invalid_property_rejected(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Unknown property"):
            parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.bogus IS NULL RETURN c')

    def test_name_is_null(self) -> None:
        """name IS NULL is valid syntax (always returns empty in practice)."""
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE c.name IS NULL RETURN c')
        assert isinstance(q.where_expr, ExistenceCondition)
        assert q.where_expr.property == "name"

    def test_not_is_null(self) -> None:
        """NOT c.label IS NULL (via compound NOT)."""
        q = parse('MATCH (n {name: "X"})-[:CHILD]->(c) WHERE NOT c.label IS NULL RETURN c')
        assert isinstance(q.where_expr, WhereNot)
        assert isinstance(q.where_expr.operand, ExistenceCondition)
        assert q.where_expr.operand.negated is False


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
        assert isinstance(q.where_expr, WhereClause)
        assert q.where_expr.value == "X"


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

    def test_unsupported_unbounded_variable_length(self) -> None:
        with pytest.raises(BrainQuerySyntaxError, match="Unbounded"):
            parse('MATCH (n)-[:CHILD*]->(m) RETURN m')

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
        assert isinstance(q.where_expr, WhereClause)
        assert isinstance(q.return_fields[0], ReturnField)

    def test_no_duplicate_nodes(self) -> None:
        """When a variable appears in both MATCH and CREATE, it should only be in nodes once."""
        q = parse('MATCH (p {name: "Parent"}) CREATE (p)-[:CHILD]->(c {name: "Child"})')
        var_names = [n.variable for n in q.nodes]
        assert var_names == ["p", "c"]  # p not duplicated
