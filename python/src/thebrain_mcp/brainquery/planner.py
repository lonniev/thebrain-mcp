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
    BrainQuery,
    NodePattern,
    RelPattern,
    ReturnField,
    WhereClause,
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


async def _resolve_node(
    api: TheBrainAPI,
    brain_id: str,
    node: NodePattern,
    where_clauses: list[WhereClause],
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
    # Gather constraints for this node
    name_exact = node.properties.get("name")
    where_clause: WhereClause | None = None
    for w in where_clauses:
        if w.variable == node.variable and w.field == "name":
            where_clause = w
            break

    # Step 1: Resolve candidates by operator
    candidates: list[Thought] = []

    if where_clause:
        op = where_clause.operator
        val = where_clause.value

        if op == "=":
            # WHERE = is strict exact match, same as inline property
            candidates = await _resolve_exact(api, brain_id, val)
        elif op == "=~":
            candidates = await _resolve_similar(api, brain_id, val)
        elif op in ("CONTAINS", "STARTS WITH", "ENDS WITH"):
            candidates = await _resolve_by_search(api, brain_id, val)
            # Post-filter by the specific string operation
            val_lower = val.lower()
            if op == "CONTAINS":
                candidates = [t for t in candidates if val_lower in t.name.lower()]
            elif op == "STARTS WITH":
                candidates = [t for t in candidates if t.name.lower().startswith(val_lower)]
            elif op == "ENDS WITH":
                candidates = [t for t in candidates if t.name.lower().endswith(val_lower)]
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

    # Step 2: Lazy type filtering (only if candidates AND type label)
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
        elif query.action == "create":
            await _execute_create(api, brain_id, query, type_cache, resolved, result)
        elif query.action == "match_create":
            await _execute_match(api, brain_id, query, type_cache, resolved)
            await _execute_create(api, brain_id, query, type_cache, resolved, result)
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
    # For match_create queries, only resolve MATCH-phase variables.
    # CREATE-only variables are handled by _execute_create.
    match_vars = query.match_variables if query.action == "match_create" else None

    # Determine which target vars can be resolved via traversal vs need direct resolution.
    # A target var needs direct resolution if it has its own name/label/where constraints.
    target_vars = {r.target for r in query.relationships}
    has_own_criteria = set()
    for node in query.nodes:
        if node.properties or node.label:
            has_own_criteria.add(node.variable)
    for w in query.where_clauses:
        has_own_criteria.add(w.variable)

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
            api, brain_id, node, query.where_clauses, type_cache
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
