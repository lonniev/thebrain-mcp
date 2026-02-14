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
    """A relationship pattern like -[:CHILD]-> or -[:CHILD*1..3]->."""

    rel_type: str  # CHILD, PARENT, JUMP, SIBLING
    source: str  # variable name of source node
    target: str  # variable name of target node
    min_hops: int = 1  # 1 = single hop (default)
    max_hops: int = 1  # 1 = single hop (default)

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


WhereExpression = Union[WhereClause, WhereNot, WhereAnd, WhereXor, WhereOr]


def collect_variables(expr: WhereExpression) -> set[str]:
    """Return all variable names referenced in a WHERE expression tree."""
    if isinstance(expr, WhereClause):
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

    action: Literal["match", "create", "match_create"]
    nodes: list[NodePattern] = field(default_factory=list)
    relationships: list[RelPattern] = field(default_factory=list)
    where_expr: WhereExpression | None = None
    return_fields: list[ReturnField] = field(default_factory=list)
    match_variables: set[str] = field(default_factory=set)
