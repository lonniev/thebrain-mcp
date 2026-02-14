"""BrainQuery parser — converts BrainQuery strings into IR dataclasses."""

from __future__ import annotations

from lark import Lark, Transformer, v_args, exceptions as lark_exceptions

import re

from thebrain_mcp.brainquery.ir import (
    MAX_HOP_DEPTH,
    QUERYABLE_PROPERTIES,
    SETTABLE_PROPERTIES,
    BrainQuery,
    DeleteClause,
    ExistenceCondition,
    NodePattern,
    PropertyAssignment,
    RelPattern,
    ReturnField,
    SetClause,
    TypeAssignment,
    WhereAnd,
    WhereClause,
    WhereNot,
    WhereOr,
    WhereXor,
)

# ---------------------------------------------------------------------------
# Lark grammar
# ---------------------------------------------------------------------------

_GRAMMAR = r"""
    start: match_query | create_query | match_create_query
         | merge_query | match_merge_query | match_delete_query

    match_query: match_clause where_clause? set_clause? return_clause
    create_query: create_clause
    match_create_query: match_clause create_clause

    merge_query: merge_clause on_create_clause? on_match_clause? return_clause?
    match_merge_query: match_clause merge_clause on_create_clause? on_match_clause? return_clause?

    match_delete_query: match_clause where_clause? delete_clause

    match_clause: "MATCH"i pattern_list
    create_clause: "CREATE"i pattern_list
    merge_clause: "MERGE"i pattern_list

    pattern_list: pattern ("," pattern)*

    pattern: node_pattern (rel_pattern node_pattern)*

    node_pattern: "(" VARIABLE (":" TYPE_LABEL)? ("{" property_map "}")? ")"

    rel_pattern: "-[" VARIABLE ":" REL_TYPE hop_spec? "]->" -> rel_pattern_named
              | "-[:" REL_TYPE hop_spec? "]->"
    hop_spec: "*" INT ".." INT  -> hop_range
            | "*" INT           -> hop_fixed

    property_map: property ("," property)*
    property: "name"i ":" STRING

    where_clause: "WHERE"i or_expr
    or_expr: xor_expr (_OR xor_expr)*
    xor_expr: and_expr (_XOR and_expr)*
    and_expr: not_expr (_AND not_expr)*
    not_expr: _NOT not_expr -> where_not
            | where_atom
    where_atom: "(" or_expr ")" -> where_paren
              | VARIABLE "." VARIABLE _IS _NOT _NULL -> is_not_null
              | VARIABLE "." VARIABLE _IS _NULL -> is_null
              | VARIABLE "." "name"i where_op STRING
    where_op: "=" -> eq_op
            | "CONTAINS"i -> contains_op
            | "STARTS"i "WITH"i -> starts_with_op
            | "ENDS"i "WITH"i -> ends_with_op
            | "=~" -> similar_op
    _OR: /OR/i
    _XOR: /XOR/i
    _AND: /AND/i
    _NOT: /NOT/i
    _IS: /IS/i
    _NULL: /NULL/i

    set_clause: "SET"i set_item ("," set_item)*
    on_create_clause: _ON _CREATE "SET"i set_item ("," set_item)*
    on_match_clause: _ON _MATCH_KW "SET"i set_item ("," set_item)*
    _ON: /ON/i
    _CREATE: /CREATE/i
    _MATCH_KW: /MATCH/i
    set_item: VARIABLE "." VARIABLE "=" _NULL -> set_null
            | VARIABLE "." VARIABLE "=" STRING -> set_property
            | VARIABLE ":" VARIABLE -> set_type

    delete_clause: _DETACH? _DELETE delete_var_list
    _DETACH: /DETACH/i
    _DELETE: /DELETE/i
    delete_var_list: VARIABLE ("," VARIABLE)*

    return_clause: "RETURN"i return_item ("," return_item)*
    return_item: VARIABLE ("." FIELD_NAME)?

    VARIABLE: /[a-zA-Z_][a-zA-Z0-9_]*/
    TYPE_LABEL: /[a-zA-Z_][a-zA-Z0-9_ ]*/
    REL_TYPE: "CHILD"i | "PARENT"i | "JUMP"i | "SIBLING"i
    FIELD_NAME: "name"i | "id"i
    STRING: "\"" /[^"]*/ "\""

    %import common.WS
    %import common.INT
    %ignore WS
    %ignore /--[^\n]*/
"""

_parser = Lark(_GRAMMAR, parser="earley", ambiguity="resolve")

# ---------------------------------------------------------------------------
# Unsupported syntax detection
# ---------------------------------------------------------------------------

_UNSUPPORTED = {
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
    # Reject unbounded variable-length paths (bare * or *N.. without upper bound)
    if re.search(r'\*\s*\]', query):
        raise BrainQuerySyntaxError(
            "Unbounded variable-length paths (*) are not allowed. "
            "Use *N (fixed hops) or *N..M (range, max upper bound 5)."
        )
    if re.search(r'\*\s*\d+\s*\.\.\s*\]', query):
        raise BrainQuerySyntaxError(
            "Unbounded variable-length paths (*N..) are not allowed. "
            "Provide an explicit upper bound: *N..M (max 5)."
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

    def hop_range(self, min_val, max_val):
        return (int(min_val), int(max_val))

    def hop_fixed(self, n):
        val = int(n)
        return (val, val)

    def rel_pattern(self, rel_type, hop_spec=None):
        if hop_spec is None:
            return (rel_type, 1, 1, None)
        min_hops, max_hops = hop_spec
        return (rel_type, min_hops, max_hops, None)

    def rel_pattern_named(self, var_name, rel_type, hop_spec=None):
        if hop_spec is None:
            return (rel_type, 1, 1, var_name)
        min_hops, max_hops = hop_spec
        return (rel_type, min_hops, max_hops, var_name)

    def pattern(self, *args):
        if len(args) == 1:
            return [(args[0], None, None)]  # node only, wrapped in list
        # Chain: node, rel_info, node [, rel_info, node]*
        segments = []
        for i in range(0, len(args) - 2, 2):
            segments.append((args[i], args[i + 1], args[i + 2]))
        return segments

    def pattern_list(self, *patterns):
        flat = []
        for p in patterns:
            flat.extend(p)
        return flat

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

    def or_expr(self, *args):
        if len(args) == 1:
            return args[0]
        return WhereOr(operands=list(args))

    def xor_expr(self, *args):
        if len(args) == 1:
            return args[0]
        return WhereXor(operands=list(args))

    def and_expr(self, *args):
        if len(args) == 1:
            return args[0]
        return WhereAnd(operands=list(args))

    def not_expr(self, inner):
        # Passthrough when not_expr matches where_atom (no NOT prefix)
        return inner

    def where_not(self, inner):
        return WhereNot(operand=inner)

    def where_paren(self, inner):
        return inner

    def _normalize_property(self, token: str) -> str:
        canonical = QUERYABLE_PROPERTIES.get(token.lower())
        if canonical is None:
            valid = ", ".join(sorted(QUERYABLE_PROPERTIES.values()))
            raise BrainQuerySyntaxError(
                f"Unknown property '{token}'. "
                f"Valid properties for IS NULL/IS NOT NULL: {valid}"
            )
        return canonical

    def is_null(self, variable, prop_name):
        return ExistenceCondition(
            variable=variable,
            property=self._normalize_property(prop_name),
            negated=False,
        )

    def is_not_null(self, variable, prop_name):
        return ExistenceCondition(
            variable=variable,
            property=self._normalize_property(prop_name),
            negated=True,
        )

    def where_atom(self, variable, op, value):
        return WhereClause(variable=variable, field="name", operator=op, value=value)

    def _normalize_set_property(self, token: str) -> str:
        canonical = QUERYABLE_PROPERTIES.get(token.lower())
        if canonical is None:
            valid = ", ".join(sorted(SETTABLE_PROPERTIES.keys()))
            raise BrainQuerySyntaxError(
                f"Unknown property '{token}'. "
                f"Settable properties: {valid}"
            )
        if canonical not in SETTABLE_PROPERTIES:
            raise BrainQuerySyntaxError(
                f"Property '{canonical}' is not settable via SET. "
                f"Settable properties: {', '.join(sorted(SETTABLE_PROPERTIES.keys()))}"
            )
        return canonical

    def set_property(self, variable, prop_name, value):
        return PropertyAssignment(
            variable=variable,
            property=self._normalize_set_property(prop_name),
            value=value,
        )

    def set_null(self, variable, prop_name):
        return PropertyAssignment(
            variable=variable,
            property=self._normalize_set_property(prop_name),
            value=None,
        )

    def set_type(self, variable, type_name):
        return TypeAssignment(variable=variable, type_name=type_name)

    def set_item(self, item):
        return item

    def set_clause(self, *items):
        return SetClause(assignments=list(items))

    def where_clause(self, expr):
        return expr

    def return_item(self, *args):
        variable = args[0]
        field_name = args[1] if len(args) > 1 else None
        return ReturnField(variable=variable, field=field_name)

    def return_clause(self, *items):
        return list(items)

    def _build_query(self, action, match_patterns=None, create_patterns=None,
                     merge_patterns=None, where=None, set_cl=None,
                     delete_cl=None, on_create=None, on_match=None,
                     returns=None):
        nodes = []
        rels = []
        seen_vars = set()
        match_variables: set[str] = set()
        rel_variables: dict[str, RelPattern] = {}

        def process_patterns(patterns, *, is_match: bool = False):
            for node_a, rel_info, node_b in patterns:
                if node_a.variable not in seen_vars:
                    nodes.append(node_a)
                    seen_vars.add(node_a.variable)
                if is_match:
                    match_variables.add(node_a.variable)
                if rel_info and node_b:
                    if node_b.variable not in seen_vars:
                        nodes.append(node_b)
                        seen_vars.add(node_b.variable)
                    if is_match:
                        match_variables.add(node_b.variable)
                    rel_type_str, min_hops, max_hops, rel_var = rel_info
                    rel = RelPattern(
                        rel_type=rel_type_str,
                        source=node_a.variable,
                        target=node_b.variable,
                        min_hops=min_hops,
                        max_hops=max_hops,
                        variable=rel_var,
                    )
                    rels.append(rel)
                    if rel_var:
                        rel_variables[rel_var] = rel

        merge_variables: set[str] = set()

        if match_patterns:
            process_patterns(match_patterns, is_match=True)
        if merge_patterns:
            for node_a, rel_info, node_b in merge_patterns:
                if node_a.variable not in seen_vars:
                    nodes.append(node_a)
                    seen_vars.add(node_a.variable)
                merge_variables.add(node_a.variable)
                if rel_info and node_b:
                    if node_b.variable not in seen_vars:
                        nodes.append(node_b)
                        seen_vars.add(node_b.variable)
                    merge_variables.add(node_b.variable)
                    rel_type_str, min_hops, max_hops, rel_var = rel_info
                    rel = RelPattern(
                        rel_type=rel_type_str,
                        source=node_a.variable,
                        target=node_b.variable,
                        min_hops=min_hops,
                        max_hops=max_hops,
                        variable=rel_var,
                    )
                    rels.append(rel)
                    if rel_var:
                        rel_variables[rel_var] = rel
        if create_patterns:
            process_patterns(create_patterns, is_match=False)

        # Validate hop bounds
        for rel in rels:
            if rel.min_hops < 1:
                raise BrainQuerySyntaxError(
                    f"Minimum hop count must be >= 1, got {rel.min_hops}."
                )
            if rel.max_hops < rel.min_hops:
                raise BrainQuerySyntaxError(
                    f"Maximum hops ({rel.max_hops}) must be >= minimum ({rel.min_hops})."
                )
            if rel.max_hops > MAX_HOP_DEPTH:
                raise BrainQuerySyntaxError(
                    f"Maximum hop depth is {MAX_HOP_DEPTH}, got {rel.max_hops}."
                )

        return BrainQuery(
            action=action,
            nodes=nodes,
            relationships=rels,
            where_expr=where,
            set_clause=set_cl,
            delete_clause=delete_cl,
            on_create_set=on_create,
            on_match_set=on_match,
            return_fields=returns or [],
            match_variables=match_variables,
            merge_variables=merge_variables,
            rel_variables=rel_variables,
        )

    def match_query(self, *args):
        match = args[0]
        _, patterns = match
        # Remaining args are some combination of: where?, set?, return
        where = None
        set_cl = None
        returns = None
        for arg in args[1:]:
            if isinstance(arg, SetClause):
                set_cl = arg
            elif isinstance(arg, list):
                # return_clause returns a list of ReturnField
                returns = arg
            else:
                # WhereExpression
                where = arg
        return self._build_query("match", match_patterns=patterns,
                                 where=where, set_cl=set_cl, returns=returns)

    def create_query(self, create):
        _, patterns = create
        return self._build_query("create", create_patterns=patterns)

    def match_create_query(self, match, create):
        _, match_patterns = match
        _, create_patterns = create
        return self._build_query("match_create",
                                 match_patterns=match_patterns,
                                 create_patterns=create_patterns)

    def merge_clause(self, patterns):
        return ("merge", patterns)

    def on_create_clause(self, *items):
        return ("on_create", SetClause(assignments=list(items)))

    def on_match_clause(self, *items):
        return ("on_match", SetClause(assignments=list(items)))

    def merge_query(self, *args):
        merge = args[0]
        _, patterns = merge
        on_create = None
        on_match = None
        returns = None
        for arg in args[1:]:
            if isinstance(arg, tuple) and arg[0] == "on_create":
                on_create = arg[1]
            elif isinstance(arg, tuple) and arg[0] == "on_match":
                on_match = arg[1]
            elif isinstance(arg, list):
                returns = arg
        return self._build_query("merge", merge_patterns=patterns,
                                 on_create=on_create, on_match=on_match,
                                 returns=returns)

    def delete_var_list(self, *args):
        return list(args)

    def delete_clause(self, var_list):
        return DeleteClause(variables=var_list)

    def match_delete_query(self, *args):
        match = args[0]
        _, patterns = match
        where = None
        delete_cl = None
        for arg in args[1:]:
            if isinstance(arg, DeleteClause):
                delete_cl = arg
            else:
                where = arg
        return self._build_query("match_delete", match_patterns=patterns,
                                 where=where, delete_cl=delete_cl)

    def match_merge_query(self, *args):
        match = args[0]
        _, match_patterns = match
        merge = args[1]
        _, merge_patterns = merge
        on_create = None
        on_match = None
        returns = None
        for arg in args[2:]:
            if isinstance(arg, tuple) and arg[0] == "on_create":
                on_create = arg[1]
            elif isinstance(arg, tuple) and arg[0] == "on_match":
                on_match = arg[1]
            elif isinstance(arg, list):
                returns = arg
        return self._build_query("match_merge",
                                 match_patterns=match_patterns,
                                 merge_patterns=merge_patterns,
                                 on_create=on_create, on_match=on_match,
                                 returns=returns)

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
