"""BrainQuery parser — converts BrainQuery strings into IR dataclasses."""

from __future__ import annotations

from lark import Lark, Transformer, v_args, exceptions as lark_exceptions

from thebrain_mcp.brainquery.ir import (
    BrainQuery,
    NodePattern,
    RelPattern,
    ReturnField,
    WhereClause,
)

# ---------------------------------------------------------------------------
# Lark grammar
# ---------------------------------------------------------------------------

_GRAMMAR = r"""
    start: match_query | create_query | match_create_query

    match_query: match_clause where_clause? return_clause
    create_query: create_clause
    match_create_query: match_clause create_clause

    match_clause: "MATCH"i pattern_list
    create_clause: "CREATE"i pattern_list

    pattern_list: pattern ("," pattern)*

    pattern: node_pattern (rel_pattern node_pattern)?

    node_pattern: "(" VARIABLE (":" TYPE_LABEL)? ("{" property_map "}")? ")"

    rel_pattern: "-[:" REL_TYPE "]->"

    property_map: property ("," property)*
    property: "name"i ":" STRING

    where_clause: "WHERE"i where_expr
    where_expr: VARIABLE "." "name"i where_op STRING
    where_op: "=" -> eq_op
            | "CONTAINS"i -> contains_op
            | "STARTS"i "WITH"i -> starts_with_op
            | "ENDS"i "WITH"i -> ends_with_op
            | "=~" -> similar_op

    return_clause: "RETURN"i return_item ("," return_item)*
    return_item: VARIABLE ("." FIELD_NAME)?

    VARIABLE: /[a-zA-Z_][a-zA-Z0-9_]*/
    TYPE_LABEL: /[a-zA-Z_][a-zA-Z0-9_ ]*/
    REL_TYPE: "CHILD"i | "PARENT"i | "JUMP"i | "SIBLING"i
    FIELD_NAME: "name"i | "id"i
    STRING: "\"" /[^"]*/ "\""

    %import common.WS
    %ignore WS
    %ignore /--[^\n]*/
"""

_parser = Lark(_GRAMMAR, parser="earley", ambiguity="resolve")

# ---------------------------------------------------------------------------
# Unsupported syntax detection
# ---------------------------------------------------------------------------

_UNSUPPORTED = {
    "DELETE": "Use the delete_thought tool instead.",
    "DETACH": "Use the delete_thought tool instead.",
    "SET": "Use the update_thought tool instead.",
    "MERGE": "Use MATCH first, then CREATE if not found.",
    "OPTIONAL": "Run two separate queries instead.",
    "UNION": "Run queries independently.",
    "COUNT": "Use get_brain_stats for counts.",
    "COLLECT": "Aggregations are not supported.",
    "WITH": "Multi-part queries are not supported.",
}


def _check_unsupported(query: str) -> None:
    """Check for unsupported Cypher keywords and give helpful errors."""
    upper = query.upper().split()
    for keyword, suggestion in _UNSUPPORTED.items():
        if keyword in upper:
            # "WITH" is valid inside "STARTS WITH" and "ENDS WITH"
            if keyword == "WITH":
                idx = upper.index("WITH")
                if idx > 0 and upper[idx - 1] in ("STARTS", "ENDS"):
                    continue
            raise BrainQuerySyntaxError(
                f"'{keyword}' is not supported in BrainQuery. {suggestion}"
            )
    # Variable-length paths
    if "*" in query and (".." in query or "*]" in query):
        raise BrainQuerySyntaxError(
            "Variable-length paths (*1..3) are not supported. "
            "Use step-by-step traversal with chained MATCH clauses."
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BrainQuerySyntaxError(Exception):
    """Raised when a BrainQuery string cannot be parsed."""


# ---------------------------------------------------------------------------
# Tree transformer → IR
# ---------------------------------------------------------------------------


@v_args(inline=True)
class _BrainQueryTransformer(Transformer):
    """Transform the Lark parse tree into BrainQuery IR dataclasses."""

    def STRING(self, token):
        # Strip surrounding quotes
        return str(token)[1:-1]

    def VARIABLE(self, token):
        return str(token)

    def TYPE_LABEL(self, token):
        return str(token).strip()

    def REL_TYPE(self, token):
        return str(token).upper()

    def FIELD_NAME(self, token):
        return str(token).lower()

    def property(self, value):
        return ("name", value)

    def property_map(self, *props):
        return dict(props)

    def node_pattern(self, *args):
        variable = args[0]
        label = None
        properties = {}
        for arg in args[1:]:
            if isinstance(arg, str):
                label = arg
            elif isinstance(arg, dict):
                properties = arg
        return NodePattern(variable=variable, label=label, properties=properties)

    def rel_pattern(self, rel_type):
        return rel_type  # Just the string, source/target added in pattern()

    def pattern(self, *args):
        if len(args) == 1:
            return (args[0], None, None)  # node only
        # node, rel_type, node
        return (args[0], args[1], args[2])

    def pattern_list(self, *patterns):
        return list(patterns)

    def match_clause(self, patterns):
        return ("match", patterns)

    def create_clause(self, patterns):
        return ("create", patterns)

    def eq_op(self):
        return "="

    def contains_op(self):
        return "CONTAINS"

    def starts_with_op(self):
        return "STARTS WITH"

    def ends_with_op(self):
        return "ENDS WITH"

    def similar_op(self):
        return "=~"

    def where_expr(self, variable, op, value):
        return WhereClause(variable=variable, field="name", operator=op, value=value)

    def where_clause(self, expr):
        return expr

    def return_item(self, *args):
        variable = args[0]
        field_name = args[1] if len(args) > 1 else None
        return ReturnField(variable=variable, field=field_name)

    def return_clause(self, *items):
        return list(items)

    def _build_query(self, action, match_patterns=None, create_patterns=None,
                     where=None, returns=None):
        nodes = []
        rels = []
        seen_vars = set()
        match_variables: set[str] = set()

        def process_patterns(patterns, *, is_match: bool = False):
            for node_a, rel_type, node_b in patterns:
                if node_a.variable not in seen_vars:
                    nodes.append(node_a)
                    seen_vars.add(node_a.variable)
                if is_match:
                    match_variables.add(node_a.variable)
                if rel_type and node_b:
                    if node_b.variable not in seen_vars:
                        nodes.append(node_b)
                        seen_vars.add(node_b.variable)
                    if is_match:
                        match_variables.add(node_b.variable)
                    rels.append(RelPattern(
                        rel_type=rel_type,
                        source=node_a.variable,
                        target=node_b.variable,
                    ))

        if match_patterns:
            process_patterns(match_patterns, is_match=True)
        if create_patterns:
            process_patterns(create_patterns, is_match=False)

        return BrainQuery(
            action=action,
            nodes=nodes,
            relationships=rels,
            where_clauses=[where] if where else [],
            return_fields=returns or [],
            match_variables=match_variables,
        )

    def match_query(self, match, where_or_ret=None, ret=None):
        _, patterns = match
        if ret is None:
            # where was omitted, where_or_ret is actually return
            return self._build_query("match", match_patterns=patterns, returns=where_or_ret)
        return self._build_query("match", match_patterns=patterns,
                                 where=where_or_ret, returns=ret)

    def create_query(self, create):
        _, patterns = create
        return self._build_query("create", create_patterns=patterns)

    def match_create_query(self, match, create):
        _, match_patterns = match
        _, create_patterns = create
        return self._build_query("match_create",
                                 match_patterns=match_patterns,
                                 create_patterns=create_patterns)

    def start(self, query):
        return query


_transformer = _BrainQueryTransformer()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(query: str) -> BrainQuery:
    """Parse a BrainQuery string into a BrainQuery IR.

    Raises BrainQuerySyntaxError on invalid syntax with a helpful message.

    Examples:
        >>> parse('MATCH (n {name: "Test"}) RETURN n')
        BrainQuery(action='match', ...)

        >>> parse('CREATE (n:Person {name: "Alice"})')
        BrainQuery(action='create', ...)
    """
    query = query.strip()
    if not query:
        raise BrainQuerySyntaxError("Empty query.")

    _check_unsupported(query)

    try:
        tree = _parser.parse(query)
        return _transformer.transform(tree)
    except lark_exceptions.UnexpectedInput as e:
        raise BrainQuerySyntaxError(
            f"Syntax error at position {e.pos_in_stream}: {e}\n"
            f"See BRAINQUERY.md for supported syntax."
        ) from e
    except Exception as e:
        raise BrainQuerySyntaxError(
            f"Failed to parse query: {e}\n"
            f"See BRAINQUERY.md for supported syntax."
        ) from e
