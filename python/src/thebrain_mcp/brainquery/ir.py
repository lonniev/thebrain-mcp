"""Intermediate representation for BrainQuery parse results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


@dataclass
class NodePattern:
    """A node pattern like (n:Person {name: "Alice"})."""

    variable: str
    label: str | None = None
    properties: dict[str, str] = field(default_factory=dict)


MAX_HOP_DEPTH = 5


@dataclass
class RelPattern:
    """A relationship pattern like -[:CHILD]->, -->, or -[:CHILD|JUMP*1..3]->."""

    rel_types: list[str] | None  # None = wildcard (any), ["CHILD"] = single, ["CHILD","JUMP"] = union
    source: str  # variable name of source node
    target: str  # variable name of target node
    min_hops: int = 1  # 1 = single hop (default)
    max_hops: int = 1  # 1 = single hop (default)
    variable: str | None = None  # optional variable binding for DELETE

    @property
    def is_variable_length(self) -> bool:
        return self.min_hops != 1 or self.max_hops != 1


@dataclass
class WhereClause:
    """A WHERE filter like n.name = "value" or n.name CONTAINS "sub"."""

    variable: str
    field: str  # currently always "name"
    operator: Literal["=", "CONTAINS", "STARTS WITH", "ENDS WITH", "=~"]
    value: str


@dataclass
class WhereNot:
    """Negation of a WHERE expression."""
    operand: WhereExpression


@dataclass
class WhereAnd:
    """Conjunction of WHERE expressions."""
    operands: list[WhereExpression]


@dataclass
class WhereXor:
    """Exclusive disjunction of WHERE expressions."""
    operands: list[WhereExpression]


@dataclass
class WhereOr:
    """Disjunction of WHERE expressions."""
    operands: list[WhereExpression]


@dataclass
class ExistenceCondition:
    """Property existence check (IS NULL / IS NOT NULL)."""

    variable: str
    property: str  # canonical form: "label", "typeId", etc.
    negated: bool  # True for IS NOT NULL


# Valid property names for existence checks and SET assignments.
# Keys are lowercase (for case-insensitive matching), values are canonical forms.
QUERYABLE_PROPERTIES: dict[str, str] = {
    "name": "name",
    "id": "id",
    "label": "label",
    "typeid": "typeId",
    "foregroundcolor": "foregroundColor",
    "backgroundcolor": "backgroundColor",
    "kind": "kind",
}

# Properties that can be updated via SET (maps canonical name to API field).
SETTABLE_PROPERTIES: dict[str, str] = {
    "name": "name",
    "label": "label",
    "foregroundColor": "foregroundColor",
    "backgroundColor": "backgroundColor",
}

# Maximum number of thoughts SET can modify in a single query.
MAX_SET_BATCH = 10

# Maximum number of items DELETE can remove in a single query.
MAX_DELETE_BATCH = 5


@dataclass
class PropertyAssignment:
    """A SET assignment like p.label = "value" or p.label = NULL."""

    variable: str
    property: str  # canonical form: "label", "foregroundColor", etc.
    value: str | None  # None means SET to NULL (clear)


@dataclass
class TypeAssignment:
    """A SET type assignment like p:Person."""

    variable: str
    type_name: str


@dataclass
class SetClause:
    """A SET clause with one or more assignments."""

    assignments: list[PropertyAssignment | TypeAssignment]


@dataclass
class DeleteClause:
    """A DELETE or DETACH DELETE clause."""

    variables: list[str]
    detach: bool = False  # True for DETACH DELETE


WhereExpression = Union[
    WhereClause, WhereNot, WhereAnd, WhereXor, WhereOr, ExistenceCondition
]


def collect_variables(expr: WhereExpression) -> set[str]:
    """Return all variable names referenced in a WHERE expression tree."""
    if isinstance(expr, WhereClause):
        return {expr.variable}
    if isinstance(expr, ExistenceCondition):
        return {expr.variable}
    if isinstance(expr, WhereNot):
        return collect_variables(expr.operand)
    # WhereAnd, WhereXor, or WhereOr
    result: set[str] = set()
    for operand in expr.operands:
        result |= collect_variables(operand)
    return result


def extract_for_variable(expr: WhereExpression, var: str) -> WhereExpression | None:
    """Extract the subtree of a WHERE expression relevant to a single variable.

    For OR/XOR nodes, returns None if they span multiple variables
    (cross-variable OR/XOR is rejected later by the planner).
    """
    if isinstance(expr, WhereClause):
        return expr if expr.variable == var else None
    if isinstance(expr, ExistenceCondition):
        return expr if expr.variable == var else None
    if isinstance(expr, WhereNot):
        inner = extract_for_variable(expr.operand, var)
        return WhereNot(operand=inner) if inner is not None else None
    if isinstance(expr, WhereAnd):
        relevant = [extract_for_variable(op, var) for op in expr.operands]
        relevant = [r for r in relevant if r is not None]
        if not relevant:
            return None
        if len(relevant) == 1:
            return relevant[0]
        return WhereAnd(operands=relevant)
    if isinstance(expr, (WhereOr, WhereXor)):
        # OR/XOR across different variables is not extractable per-variable
        vars_in_expr = collect_variables(expr)
        if vars_in_expr != {var}:
            return None
        return expr
    return None


@dataclass
class ReturnField:
    """A RETURN item like n or n.name."""

    variable: str
    field: str | None = None  # None = full thought, "name", "id"


@dataclass
class BrainQuery:
    """Parsed BrainQuery ready for the planner."""

    action: Literal[
        "match", "create", "match_create", "merge", "match_merge", "match_delete"
    ]
    nodes: list[NodePattern] = field(default_factory=list)
    relationships: list[RelPattern] = field(default_factory=list)
    where_expr: WhereExpression | None = None
    set_clause: SetClause | None = None
    delete_clause: DeleteClause | None = None
    on_create_set: SetClause | None = None
    on_match_set: SetClause | None = None
    return_fields: list[ReturnField] = field(default_factory=list)
    match_variables: set[str] = field(default_factory=set)
    # For MERGE: which variables are in the MERGE pattern (vs MATCH)
    merge_variables: set[str] = field(default_factory=set)
    # For DELETE: relationship variables bound in MATCH patterns
    rel_variables: dict[str, RelPattern] = field(default_factory=dict)
    # Whether deletion is confirmed (dry-run by default)
    confirm_delete: bool = False
