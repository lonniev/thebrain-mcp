"""Intermediate representation for BrainQuery parse results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class NodePattern:
    """A node pattern like (n:Person {name: "Alice"})."""

    variable: str
    label: str | None = None
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class RelPattern:
    """A relationship pattern like -[:CHILD]->."""

    rel_type: str  # CHILD, PARENT, JUMP, SIBLING
    source: str  # variable name of source node
    target: str  # variable name of target node


@dataclass
class WhereClause:
    """A WHERE filter like n.name = "value" or n.name CONTAINS "sub"."""

    variable: str
    field: str  # currently always "name"
    operator: Literal["=", "CONTAINS"]
    value: str


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
    where_clauses: list[WhereClause] = field(default_factory=list)
    return_fields: list[ReturnField] = field(default_factory=list)
