"""BrainQuery planner & executor — translates parsed IR into TheBrain API calls.

Uses a name-first resolution strategy with lazy type filtering.
Never traverses down from Type uber-nodes to find matches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.api.models import Thought
from thebrain_mcp.brainquery.ir import (
    MAX_SET_BATCH,
    SETTABLE_PROPERTIES,
    BrainQuery,
    ExistenceCondition,
    NodePattern,
    PropertyAssignment,
    RelPattern,
    ReturnField,
    SetClause,
    TypeAssignment,
    WhereAnd,
    WhereClause,
    WhereExpression,
    WhereNot,
    WhereOr,
    WhereXor,
    collect_variables,
)

logger = logging.getLogger(__name__)

# Relation type mapping: BrainQuery name -> TheBrain API integer
_RELATION_MAP = {
    "CHILD": 1,
    "PARENT": 2,
    "JUMP": 3,
    "SIBLING": 4,
}

# Reverse for graph traversal: relation int -> graph attribute name
_GRAPH_RELATION_ATTR = {
    "CHILD": "children",
    "PARENT": "parents",
    "JUMP": "jumps",
    "SIBLING": "siblings",
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ResolvedThought:
    """A thought resolved during query execution."""

    id: str
    name: str
    label: str | None = None  # type name
    type_id: str | None = None


@dataclass
class QueryResult:
    """Result of executing a BrainQuery."""

    success: bool
    action: str
    results: dict[str, list[ResolvedThought]] = field(default_factory=dict)
    created: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        out: dict[str, Any] = {
            "success": self.success,
            "action": self.action,
        }
        if self.results:
            out["results"] = {
                var: [
                    {"id": t.id, "name": t.name, "label": t.label, "typeId": t.type_id}
                    for t in thoughts
                ]
                for var, thoughts in self.results.items()
            }
        if self.created:
            out["created"] = self.created
        if self.errors:
            out["errors"] = self.errors
        return out


# ---------------------------------------------------------------------------
# Type cache (per-execution, lazy)
# ---------------------------------------------------------------------------


class _TypeCache:
    """Lazily resolves and caches thought types for a brain."""

    def __init__(self, api: TheBrainAPI, brain_id: str) -> None:
        self._api = api
        self._brain_id = brain_id
        self._types: dict[str, str] | None = None  # name -> type_id

    async def resolve(self, type_name: str) -> str | None:
        """Get the type ID for a type name, fetching types lazily."""
        if self._types is None:
            types = await self._api.get_types(self._brain_id)
            self._types = {}
            for t in types:
                self._types[t.name] = t.id
                if t.label and t.label != t.name:
                    self._types[t.label] = t.id
        return self._types.get(type_name)


# ---------------------------------------------------------------------------
# Node resolution (name-first strategy)
# ---------------------------------------------------------------------------


async def _resolve_exact(
    api: TheBrainAPI, brain_id: str, name: str
) -> list[Thought]:
    """Resolve thoughts by strict exact name. No search fallback."""
    thought = await api.get_thought_by_name(brain_id, name)
    if thought:
        return [thought]
    return []


async def _resolve_by_search(
    api: TheBrainAPI, brain_id: str, query: str, max_results: int = 30
) -> list[Thought]:
    """Resolve thoughts via search API."""
    try:
        results = await api.search_thoughts(brain_id, query, max_results=max_results)
        thoughts = []
        for r in results:
            if r.source_thought:
                thoughts.append(r.source_thought)
        return thoughts
    except TheBrainAPIError:
        return []


async def _resolve_similar(
    api: TheBrainAPI, brain_id: str, name: str
) -> list[Thought]:
    """Resolve thoughts by similarity: exact name first, then search fallback.

    Results are ranked by similarity — shorter, closer matches first.
    """
    # Step 1: exact name lookup (cheap)
    thought = await api.get_thought_by_name(brain_id, name)
    if thought:
        return [thought]

    # Step 2: search fallback
    candidates = await _resolve_by_search(api, brain_id, name, max_results=10)

    # Rank by similarity: prefer shorter names and those containing the query
    name_lower = name.lower()

    def _similarity_key(t: Thought) -> tuple[int, int, str]:
        t_lower = t.name.lower()
        # Exact match first (distance 0), then by edit distance proxy
        if t_lower == name_lower:
            return (0, 0, t_lower)
        # Starts-with gets priority
        starts = 0 if t_lower.startswith(name_lower) else 1
        return (1, starts, t_lower)

    candidates.sort(key=_similarity_key)
    return candidates


async def _filter_by_type(
    api: TheBrainAPI,
    brain_id: str,
    candidates: list[Thought],
    type_cache: _TypeCache,
    type_name: str,
) -> list[Thought]:
    """Filter candidates by type, fetching full thought details if needed."""
    type_id = await type_cache.resolve(type_name)
    if type_id is None:
        return []  # Unknown type

    filtered = []
    for candidate in candidates:
        # If the candidate already has type_id populated, check it directly
        if candidate.type_id is not None:
            if candidate.type_id == type_id:
                filtered.append(candidate)
            continue

        # Otherwise fetch full thought to check type
        try:
            full = await api.get_thought(brain_id, candidate.id)
            if full.type_id == type_id:
                filtered.append(full)
        except TheBrainAPIError:
            continue

    return filtered


# ---------------------------------------------------------------------------
# Compound WHERE helpers
# ---------------------------------------------------------------------------


def _validate_where_expr(expr: WhereExpression | None) -> None:
    """Validate a WHERE expression tree.

    Raises ValueError for:
    - Cross-variable OR or XOR
    - NOT as the sole constraint on an unconstrained node (no chain context)
    """
    if expr is None:
        return
    if isinstance(expr, (WhereClause, ExistenceCondition)):
        return
    if isinstance(expr, WhereNot):
        _validate_where_expr(expr.operand)
        return
    if isinstance(expr, WhereAnd):
        for op in expr.operands:
            _validate_where_expr(op)
        return
    if isinstance(expr, (WhereOr, WhereXor)):
        variables = collect_variables(expr)
        kind = "OR" if isinstance(expr, WhereOr) else "XOR"
        if len(variables) > 1:
            raise ValueError(
                f"{kind} across different variables ({', '.join(sorted(variables))}) "
                f"is not supported. Use separate queries instead."
            )
        for op in expr.operands:
            _validate_where_expr(op)


def _where_for_variables(
    expr: WhereExpression | None,
) -> dict[str, WhereExpression]:
    """Decompose a WHERE expression into per-variable subtrees.

    Top-level AND is split by variable. OR/XOR is kept as a unit (single-variable only).
    NOT is kept with its operand's variable.
    """
    if expr is None:
        return {}
    if isinstance(expr, WhereClause):
        return {expr.variable: expr}
    if isinstance(expr, ExistenceCondition):
        return {expr.variable: expr}
    if isinstance(expr, WhereNot):
        variables = collect_variables(expr)
        if len(variables) == 1:
            var = next(iter(variables))
            return {var: expr}
        return {}
    if isinstance(expr, (WhereOr, WhereXor)):
        # Single-variable OR/XOR (validated earlier)
        variables = collect_variables(expr)
        if len(variables) == 1:
            var = next(iter(variables))
            return {var: expr}
        return {}
    if isinstance(expr, WhereAnd):
        result: dict[str, list[WhereExpression]] = {}
        for op in expr.operands:
            op_vars = collect_variables(op)
            if len(op_vars) == 1:
                var = next(iter(op_vars))
                result.setdefault(var, []).append(op)
            else:
                # Multi-variable operand within AND — distribute to each var
                for var in op_vars:
                    result.setdefault(var, []).append(op)
        return {
            var: ops[0] if len(ops) == 1 else WhereAnd(operands=ops)
            for var, ops in result.items()
        }
    return {}



def _get_property(thought: Thought, prop: str) -> Any:
    """Get a property value from a Thought by canonical property name."""
    _ACCESSORS: dict[str, Any] = {
        "name": lambda t: t.name,
        "id": lambda t: t.id,
        "label": lambda t: t.label,
        "typeId": lambda t: t.type_id,
        "foregroundColor": lambda t: t.foreground_color,
        "backgroundColor": lambda t: t.background_color,
        "kind": lambda t: t.kind,
    }
    accessor = _ACCESSORS.get(prop)
    return accessor(thought) if accessor else None


def _check_existence(thought: Thought, cond: ExistenceCondition) -> bool:
    """Check if a thought satisfies an existence condition."""
    value = _get_property(thought, cond.property)
    is_null = value is None
    if cond.negated:  # IS NOT NULL
        return not is_null
    return is_null  # IS NULL


def _matches_clause(thought: Thought, clause: WhereClause) -> bool:
    """In-memory match of a thought against a single WHERE clause."""
    if clause.field != "name":
        return False
    name = thought.name
    val = clause.value
    op = clause.operator
    if op == "=":
        return name == val
    val_lower = val.lower()
    name_lower = name.lower()
    if op == "CONTAINS":
        return val_lower in name_lower
    if op == "STARTS WITH":
        return name_lower.startswith(val_lower)
    if op == "ENDS WITH":
        return name_lower.endswith(val_lower)
    if op == "=~":
        return val_lower in name_lower
    return False


def _apply_filter(candidates: list[Thought], expr: WhereExpression) -> list[Thought]:
    """In-memory filtering of candidates against a compound WHERE expression."""
    if isinstance(expr, ExistenceCondition):
        return [t for t in candidates if _check_existence(t, expr)]
    if isinstance(expr, WhereClause):
        return [t for t in candidates if _matches_clause(t, expr)]
    if isinstance(expr, WhereNot):
        excluded = _apply_filter(candidates, expr.operand)
        excluded_ids = {t.id for t in excluded}
        return [t for t in candidates if t.id not in excluded_ids]
    if isinstance(expr, WhereAnd):
        result = candidates
        for op in expr.operands:
            result = _apply_filter(result, op)
        return result
    if isinstance(expr, WhereXor):
        # Symmetric difference: in exactly one branch but not both
        branch_sets: list[set[str]] = []
        branch_thoughts: dict[str, Thought] = {}
        for op in expr.operands:
            matched = _apply_filter(candidates, op)
            branch_sets.append({t.id for t in matched})
            for t in matched:
                branch_thoughts[t.id] = t
        # XOR: present in exactly one branch
        all_ids = set.union(*branch_sets) if branch_sets else set()
        xor_ids: set[str] = set()
        for tid in all_ids:
            count = sum(1 for bs in branch_sets if tid in bs)
            if count == 1:
                xor_ids.add(tid)
        return [branch_thoughts[tid] for tid in xor_ids if tid in branch_thoughts]
    if isinstance(expr, WhereOr):
        seen: set[str] = set()
        result: list[Thought] = []
        for op in expr.operands:
            for t in _apply_filter(candidates, op):
                if t.id not in seen:
                    result.append(t)
                    seen.add(t.id)
        return result
    return candidates


async def _resolve_single_clause(
    api: TheBrainAPI, brain_id: str, clause: WhereClause,
) -> list[Thought]:
    """Resolve a single WHERE clause to thoughts via the API."""
    op = clause.operator
    val = clause.value
    if op == "=":
        return await _resolve_exact(api, brain_id, val)
    if op == "=~":
        return await _resolve_similar(api, brain_id, val)
    if op in ("CONTAINS", "STARTS WITH", "ENDS WITH"):
        candidates = await _resolve_by_search(api, brain_id, val)
        val_lower = val.lower()
        if op == "CONTAINS":
            return [t for t in candidates if val_lower in t.name.lower()]
        if op == "STARTS WITH":
            return [t for t in candidates if t.name.lower().startswith(val_lower)]
        if op == "ENDS WITH":
            return [t for t in candidates if t.name.lower().endswith(val_lower)]
    return []


def _has_positive_clause(expr: WhereExpression) -> bool:
    """Check whether an expression contains at least one positive (non-NOT) search-driving clause.

    ExistenceCondition is a filter (can't drive a search), so it returns False.
    """
    if isinstance(expr, WhereClause):
        return True
    if isinstance(expr, ExistenceCondition):
        return False  # filter only, can't drive a search
    if isinstance(expr, WhereNot):
        return False
    if isinstance(expr, (WhereAnd, WhereOr, WhereXor)):
        return any(_has_positive_clause(op) for op in expr.operands)
    return False


async def _evaluate_where(
    api: TheBrainAPI, brain_id: str, expr: WhereExpression,
) -> list[Thought]:
    """Recursively evaluate a compound WHERE expression against the API."""
    if isinstance(expr, WhereClause):
        return await _resolve_single_clause(api, brain_id, expr)
    if isinstance(expr, ExistenceCondition):
        # Existence checks can't drive a search on their own — they need
        # a candidate set from a chain traversal or a sibling positive clause.
        raise ValueError(
            "IS NULL / IS NOT NULL cannot be used as the sole constraint. "
            "Combine with a name condition (AND) or use on a traversal target."
        )
    if isinstance(expr, WhereNot):
        # NOT cannot drive a search on its own — it needs a candidate set
        # provided by a chain traversal or a sibling positive constraint.
        # If we reach here, it means NOT is the sole constraint for direct
        # resolution — reject it.
        raise ValueError(
            "NOT requires at least one positive constraint to filter against. "
            "Use AND with a positive condition, or place NOT on a traversal target."
        )
    if isinstance(expr, WhereOr):
        seen: set[str] = set()
        result: list[Thought] = []
        for op in expr.operands:
            for t in await _evaluate_where(api, brain_id, op):
                if t.id not in seen:
                    result.append(t)
                    seen.add(t.id)
        return result
    if isinstance(expr, WhereXor):
        # Symmetric difference: evaluate each branch, keep results in exactly one
        branch_sets: list[set[str]] = []
        branch_thoughts: dict[str, Thought] = {}
        for op in expr.operands:
            matched = await _evaluate_where(api, brain_id, op)
            branch_sets.append({t.id for t in matched})
            for t in matched:
                branch_thoughts[t.id] = t
        all_ids = set.union(*branch_sets) if branch_sets else set()
        xor_ids: set[str] = set()
        for tid in all_ids:
            count = sum(1 for bs in branch_sets if tid in bs)
            if count == 1:
                xor_ids.add(tid)
        return [branch_thoughts[tid] for tid in xor_ids if tid in branch_thoughts]
    if isinstance(expr, WhereAnd):
        # Separate positive operands (that can drive search) from NOT operands
        positive_ops = [op for op in expr.operands if _has_positive_clause(op)]
        not_ops = [op for op in expr.operands if not _has_positive_clause(op)]

        if not positive_ops:
            raise ValueError(
                "NOT requires at least one positive constraint to filter against. "
                "Add a positive condition with AND."
            )

        # Evaluate positive operands and intersect
        sets: list[list[Thought]] = []
        for op in positive_ops:
            sets.append(await _evaluate_where(api, brain_id, op))
        if not sets:
            return []
        common_ids = set.intersection(*(set(t.id for t in s) for s in sets))
        candidates = [t for t in sets[0] if t.id in common_ids]

        # Apply NOT operands as post-filters
        for not_op in not_ops:
            candidates = _apply_filter(candidates, not_op)

        return candidates
    return []


async def _resolve_node(
    api: TheBrainAPI,
    brain_id: str,
    node: NodePattern,
    var_where: WhereExpression | None,
    type_cache: _TypeCache,
) -> list[Thought]:
    """Resolve a node pattern to concrete thoughts.

    Dispatch by operator:
    - {name: "value"} or WHERE = → strict exact match (no fallback)
    - WHERE CONTAINS  → search + substring filter
    - WHERE STARTS WITH → search + prefix filter
    - WHERE ENDS WITH → search + suffix filter
    - WHERE =~ → similarity (exact → search → rank)
    - Type label only → resolve the type thought itself
    """
    name_exact = node.properties.get("name")
    candidates: list[Thought] = []

    if var_where:
        candidates = await _evaluate_where(api, brain_id, var_where)
    elif name_exact:
        # Inline property {name: "value"} → strict exact match
        candidates = await _resolve_exact(api, brain_id, name_exact)
    elif node.label:
        # Type-only query: return the type thought itself as anchor
        type_id = await type_cache.resolve(node.label)
        if type_id:
            try:
                type_thought = await api.get_thought(brain_id, type_id)
                return [type_thought]
            except TheBrainAPIError:
                pass
        return []

    if not candidates:
        return []

    # Lazy type filtering (only if candidates AND type label)
    if node.label and candidates:
        candidates = await _filter_by_type(api, brain_id, candidates, type_cache, node.label)

    return candidates


# ---------------------------------------------------------------------------
# Relationship traversal
# ---------------------------------------------------------------------------


async def _traverse_relationship(
    api: TheBrainAPI,
    brain_id: str,
    source_thoughts: list[Thought],
    rel: RelPattern,
) -> list[Thought]:
    """Traverse a relationship from resolved source thoughts."""
    attr = _GRAPH_RELATION_ATTR.get(rel.rel_type)
    if not attr:
        return []

    results: list[Thought] = []
    seen_ids: set[str] = set()

    for source in source_thoughts:
        try:
            graph = await api.get_thought_graph(brain_id, source.id)
            related = getattr(graph, attr, None) or []
            for t in related:
                if t.id not in seen_ids:
                    results.append(t)
                    seen_ids.add(t.id)
        except TheBrainAPIError:
            continue

    return results


async def _traverse_variable_length(
    api: TheBrainAPI,
    brain_id: str,
    source_thoughts: list[Thought],
    rel: RelPattern,
) -> list[Thought]:
    """Traverse a variable-length path using BFS with depth tracking.

    Expands from source_thoughts up to rel.max_hops levels deep.
    Returns thoughts reachable at depths between min_hops and max_hops.
    Deduplicates by thought ID to handle cycles.
    """
    attr = _GRAPH_RELATION_ATTR.get(rel.rel_type)
    if not attr:
        return []

    visited: set[str] = {t.id for t in source_thoughts}
    frontier: list[Thought] = list(source_thoughts)
    results: list[Thought] = []
    result_ids: set[str] = set()

    for depth in range(1, rel.max_hops + 1):
        next_frontier: list[Thought] = []
        for source in frontier:
            try:
                graph = await api.get_thought_graph(brain_id, source.id)
                related = getattr(graph, attr, None) or []
                for t in related:
                    if t.id not in visited:
                        visited.add(t.id)
                        next_frontier.append(t)
                        if depth >= rel.min_hops and t.id not in result_ids:
                            results.append(t)
                            result_ids.add(t.id)
            except TheBrainAPIError:
                continue
        frontier = next_frontier
        if not frontier:
            break

    return results


# ---------------------------------------------------------------------------
# Format results for output
# ---------------------------------------------------------------------------


def _thought_to_resolved(thought: Thought) -> ResolvedThought:
    return ResolvedThought(
        id=thought.id,
        name=thought.name,
        type_id=thought.type_id,
    )


def _format_return(
    return_fields: list[ReturnField],
    resolved: dict[str, list[ResolvedThought]],
) -> dict[str, list[ResolvedThought]]:
    """Filter resolved results to only include requested return variables."""
    if not return_fields:
        return resolved

    requested_vars = {rf.variable for rf in return_fields}
    return {var: thoughts for var, thoughts in resolved.items() if var in requested_vars}


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


async def execute(
    api: TheBrainAPI,
    brain_id: str,
    query: BrainQuery,
) -> QueryResult:
    """Execute a parsed BrainQuery against TheBrain API.

    Args:
        api: TheBrain API client
        brain_id: The brain to query
        query: Parsed BrainQuery IR

    Returns:
        QueryResult with resolved thoughts and/or created items
    """
    type_cache = _TypeCache(api, brain_id)
    resolved: dict[str, list[Thought]] = {}
    result = QueryResult(success=True, action=query.action)

    try:
        if query.action == "match":
            await _execute_match(api, brain_id, query, type_cache, resolved)
            if query.set_clause:
                await _execute_set(
                    api, brain_id, query.set_clause, type_cache, resolved, result
                )
        elif query.action == "create":
            await _execute_create(api, brain_id, query, type_cache, resolved, result)
        elif query.action == "match_create":
            await _execute_match(api, brain_id, query, type_cache, resolved)
            await _execute_create(api, brain_id, query, type_cache, resolved, result)
        elif query.action in ("merge", "match_merge"):
            await _execute_merge(api, brain_id, query, type_cache, resolved, result)
    except Exception as e:
        result.success = False
        result.errors.append(str(e))
        return result

    # Convert Thought objects to ResolvedThought for output
    resolved_output = {
        var: [_thought_to_resolved(t) for t in thoughts]
        for var, thoughts in resolved.items()
    }

    result.results = _format_return(query.return_fields, resolved_output)
    return result


async def _execute_match(
    api: TheBrainAPI,
    brain_id: str,
    query: BrainQuery,
    type_cache: _TypeCache,
    resolved: dict[str, list[Thought]],
) -> None:
    """Execute the MATCH portion of a query."""
    # Validate compound WHERE up front
    _validate_where_expr(query.where_expr)

    # Decompose WHERE into per-variable subtrees
    var_wheres = _where_for_variables(query.where_expr)

    # For match_create queries, only resolve MATCH-phase variables.
    # CREATE-only variables are handled by _execute_create.
    match_vars = query.match_variables if query.action in ("match_create", "match_merge") else None

    # Determine which target vars can be resolved via traversal vs need direct resolution.
    # A target var needs direct resolution if it has its own name/label/where constraints.
    target_vars = {r.target for r in query.relationships}
    has_own_criteria = set()
    for node in query.nodes:
        if node.properties or node.label:
            has_own_criteria.add(node.variable)
    # WHERE on non-target variables triggers direct resolution;
    # WHERE on target variables is applied as post-filter after traversal.
    for var in var_wheres:
        if var not in target_vars:
            has_own_criteria.add(var)

    # Traversal targets whose WHERE is purely negative (bare NOT) should NOT
    # force direct resolution — the chain provides the candidate set and NOT
    # is applied as a post-filter. Remove them from has_own_criteria so they
    # go through the traversal path instead.
    for var in list(has_own_criteria & target_vars):
        var_where = var_wheres.get(var)
        if var_where and not _has_positive_clause(var_where):
            node = next((n for n in query.nodes if n.variable == var), None)
            if node and not node.properties:
                has_own_criteria.discard(var)

    # Targets that have their own criteria get resolved directly, not via traversal
    skip_vars = target_vars - has_own_criteria

    for node in query.nodes:
        if match_vars is not None and node.variable not in match_vars:
            continue  # CREATE-only variable, skip in MATCH phase
        if node.variable in skip_vars:
            continue  # Will be resolved via relationship traversal
        if node.variable in resolved:
            continue  # Already resolved

        thoughts = await _resolve_node(
            api, brain_id, node, var_wheres.get(node.variable), type_cache
        )
        resolved[node.variable] = thoughts

    # Then traverse relationships (only if target isn't already resolved
    # and is a MATCH-phase variable)
    for rel in query.relationships:
        if rel.target in resolved:
            continue  # Target already resolved directly — don't overwrite
        if match_vars is not None and rel.target not in match_vars:
            continue  # CREATE-phase relationship, skip in MATCH

        source_thoughts = resolved.get(rel.source, [])
        if not source_thoughts:
            resolved[rel.target] = []
            continue

        # Find the target node pattern for type filtering
        target_node = next(
            (n for n in query.nodes if n.variable == rel.target), None
        )

        if rel.is_variable_length:
            traversed = await _traverse_variable_length(
                api, brain_id, source_thoughts, rel
            )
        else:
            traversed = await _traverse_relationship(
                api, brain_id, source_thoughts, rel
            )

        # Apply target node's type filter if present
        if target_node and target_node.label and traversed:
            traversed = await _filter_by_type(
                api, brain_id, traversed, type_cache, target_node.label
            )

        # Apply target node's name filter if present
        if target_node and target_node.properties.get("name") and traversed:
            name = target_node.properties["name"]
            traversed = [t for t in traversed if t.name == name]

        # Apply target's WHERE constraint if present
        target_where = var_wheres.get(rel.target)
        if target_where and traversed:
            traversed = _apply_filter(traversed, target_where)

        resolved[rel.target] = traversed


async def _execute_create(
    api: TheBrainAPI,
    brain_id: str,
    query: BrainQuery,
    type_cache: _TypeCache,
    resolved: dict[str, list[Thought]],
    result: QueryResult,
) -> None:
    """Execute the CREATE portion of a query."""
    for rel in query.relationships:
        source_thoughts = resolved.get(rel.source, [])
        target_node = next(
            (n for n in query.nodes if n.variable == rel.target), None
        )

        if not target_node:
            result.errors.append(f"No node pattern for variable '{rel.target}'.")
            result.success = False
            continue

        # Case 1: Both source and target already resolved — create link only
        target_thoughts = resolved.get(rel.target, [])
        if source_thoughts and target_thoughts:
            for src in source_thoughts:
                for tgt in target_thoughts:
                    relation = _RELATION_MAP.get(rel.rel_type, 1)
                    link_data = {
                        "thoughtIdA": src.id,
                        "thoughtIdB": tgt.id,
                        "relation": relation,
                    }
                    link_result = await api.create_link(brain_id, link_data)
                    result.created.append({
                        "type": "link",
                        "linkId": link_result.get("id"),
                        "from": src.name,
                        "to": tgt.name,
                        "relation": rel.rel_type,
                    })
            continue

        # Case 2: Source resolved, target needs creation
        if source_thoughts and not target_thoughts:
            name = target_node.properties.get("name")
            if not name:
                result.errors.append(
                    f"Cannot create thought for '{rel.target}': no name specified."
                )
                result.success = False
                continue

            # Resolve type if specified
            type_id = None
            if target_node.label:
                type_id = await type_cache.resolve(target_node.label)

            for src in source_thoughts:
                relation = _RELATION_MAP.get(rel.rel_type, 1)
                thought_data: dict[str, Any] = {
                    "name": name,
                    "kind": 1,
                    "acType": 0,
                    "sourceThoughtId": src.id,
                    "relation": relation,
                }
                if type_id:
                    thought_data["typeId"] = type_id

                created = await api.create_thought(brain_id, thought_data)
                thought_id = created.get("id")
                result.created.append({
                    "type": "thought",
                    "thoughtId": thought_id,
                    "name": name,
                    "parent": src.name,
                    "relation": rel.rel_type,
                    "typeId": type_id,
                })

                # Add to resolved so subsequent operations can reference it
                if thought_id:
                    new_thought = Thought.model_validate({
                        "id": thought_id,
                        "brainId": brain_id,
                        "name": name,
                        "kind": 1,
                        "acType": 0,
                        "typeId": type_id,
                    })
                    resolved.setdefault(rel.target, []).append(new_thought)
            continue

        # Case 3: No source resolved
        if not source_thoughts:
            result.errors.append(
                f"Could not resolve source '{rel.source}' — "
                f"try providing a thought ID or navigating from a known type."
            )
            result.success = False

    # Handle standalone creates (no relationship)
    if not query.relationships:
        for node in query.nodes:
            if node.variable in resolved:
                continue

            name = node.properties.get("name")
            if not name:
                result.errors.append(
                    f"Cannot create thought for '{node.variable}': no name specified."
                )
                result.success = False
                continue

            type_id = None
            if node.label:
                type_id = await type_cache.resolve(node.label)

            thought_data = {
                "name": name,
                "kind": 1,
                "acType": 0,
            }
            if type_id:
                thought_data["typeId"] = type_id

            created = await api.create_thought(brain_id, thought_data)
            thought_id = created.get("id")
            result.created.append({
                "type": "thought",
                "thoughtId": thought_id,
                "name": name,
                "typeId": type_id,
            })


async def _execute_set(
    api: TheBrainAPI,
    brain_id: str,
    set_clause: SetClause,
    type_cache: _TypeCache,
    resolved: dict[str, list[Thought]],
    result: QueryResult,
) -> None:
    """Execute the SET portion of a query — update matched thoughts."""
    result.action = "match_set"

    # Group assignments by variable
    var_assignments: dict[str, list[PropertyAssignment | TypeAssignment]] = {}
    for assignment in set_clause.assignments:
        var_assignments.setdefault(assignment.variable, []).append(assignment)

    for var, assignments in var_assignments.items():
        thoughts = resolved.get(var, [])
        if not thoughts:
            continue

        # Safety: bulk modification limit
        if len(thoughts) > MAX_SET_BATCH:
            raise ValueError(
                f"SET would affect {len(thoughts)} thoughts (max {MAX_SET_BATCH}). "
                f"Narrow the MATCH to reduce the target set."
            )

        for thought in thoughts:
            updates: dict[str, Any] = {}

            for assignment in assignments:
                if isinstance(assignment, PropertyAssignment):
                    api_field = SETTABLE_PROPERTIES.get(assignment.property)
                    if api_field:
                        updates[api_field] = assignment.value
                elif isinstance(assignment, TypeAssignment):
                    type_id = await type_cache.resolve(assignment.type_name)
                    if type_id is None:
                        raise ValueError(
                            f"Unknown type '{assignment.type_name}'. "
                            f"Check available types with get_types."
                        )
                    updates["typeId"] = type_id

            if updates:
                await api.update_thought(brain_id, thought.id, updates)

                # Update in-memory thought to reflect changes
                if "name" in updates and updates["name"] is not None:
                    thought.name = updates["name"]
                if "label" in updates:
                    thought.label = updates["label"]
                if "foregroundColor" in updates:
                    thought.foreground_color = updates["foregroundColor"]
                if "backgroundColor" in updates:
                    thought.background_color = updates["backgroundColor"]
                if "typeId" in updates:
                    thought.type_id = updates["typeId"]

                result.created.append({
                    "type": "update",
                    "thoughtId": thought.id,
                    "name": thought.name,
                    "updates": updates,
                })


async def _execute_merge(
    api: TheBrainAPI,
    brain_id: str,
    query: BrainQuery,
    type_cache: _TypeCache,
    resolved: dict[str, list[Thought]],
    result: QueryResult,
) -> None:
    """Execute MERGE — match or create with idempotent semantics."""
    result.action = "merge"

    # If match_merge, resolve MATCH variables first
    if query.action == "match_merge":
        await _execute_match(api, brain_id, query, type_cache, resolved)

    # Process each MERGE node
    for node in query.nodes:
        if node.variable not in query.merge_variables:
            continue
        if node.variable in resolved:
            continue  # Already resolved by MATCH phase

        name = node.properties.get("name")
        if not name:
            raise ValueError(
                f"MERGE requires a name constraint for '{node.variable}'. "
                f"Use MERGE (n {{name: \"value\"}})."
            )

        # Try to find existing thought
        existing = await _resolve_exact(api, brain_id, name)

        # Filter by type if specified
        if existing and node.label:
            existing = await _filter_by_type(
                api, brain_id, existing, type_cache, node.label
            )

        if existing:
            # MATCH path — thought exists
            resolved[node.variable] = existing
            if len(existing) > 1:
                result.errors.append(
                    f"MERGE matched {len(existing)} thoughts named '{name}'. "
                    f"Using the first match."
                )
            result.created.append({
                "type": "merge_match",
                "thoughtId": existing[0].id,
                "name": existing[0].name,
            })
            # Apply ON MATCH SET
            if query.on_match_set:
                await _execute_set(
                    api, brain_id, query.on_match_set, type_cache, resolved, result
                )
        else:
            # CREATE path — thought doesn't exist
            type_id = None
            if node.label:
                type_id = await type_cache.resolve(node.label)

            thought_data: dict[str, Any] = {
                "name": name,
                "kind": 1,
                "acType": 0,
            }
            if type_id:
                thought_data["typeId"] = type_id

            created = await api.create_thought(brain_id, thought_data)
            thought_id = created.get("id")
            new_thought = Thought.model_validate({
                "id": thought_id,
                "brainId": brain_id,
                "name": name,
                "kind": 1,
                "acType": 0,
                "typeId": type_id,
            })
            resolved[node.variable] = [new_thought]
            result.created.append({
                "type": "merge_create",
                "thoughtId": thought_id,
                "name": name,
            })
            # Apply ON CREATE SET
            if query.on_create_set:
                await _execute_set(
                    api, brain_id, query.on_create_set, type_cache, resolved, result
                )

    # Process MERGE relationships
    for rel in query.relationships:
        if rel.source not in query.merge_variables and rel.target not in query.merge_variables:
            continue

        source_thoughts = resolved.get(rel.source, [])
        target_thoughts = resolved.get(rel.target, [])

        if not source_thoughts or not target_thoughts:
            continue

        src = source_thoughts[0]
        tgt = target_thoughts[0]

        # Check if link already exists
        try:
            attr = _GRAPH_RELATION_ATTR.get(rel.rel_type)
            graph = await api.get_thought_graph(brain_id, src.id)
            existing_targets = getattr(graph, attr, None) or []
            link_exists = any(t.id == tgt.id for t in existing_targets)
        except TheBrainAPIError:
            link_exists = False

        if not link_exists:
            relation = _RELATION_MAP.get(rel.rel_type, 1)
            link_data = {
                "thoughtIdA": src.id,
                "thoughtIdB": tgt.id,
                "relation": relation,
            }
            link_result = await api.create_link(brain_id, link_data)
            result.created.append({
                "type": "merge_create_link",
                "linkId": link_result.get("id"),
                "from": src.name,
                "to": tgt.name,
                "relation": rel.rel_type,
            })
        else:
            result.created.append({
                "type": "merge_match_link",
                "from": src.name,
                "to": tgt.name,
                "relation": rel.rel_type,
            })
