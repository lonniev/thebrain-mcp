"""Thought operation tools for TheBrain MCP server."""

from datetime import datetime, timezone
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.formatters import (
    get_access_type_name,
    get_kind_name,
    get_relation_name,
    get_search_result_type_name,
)


async def create_thought_tool(
    api: TheBrainAPI,
    brain_id: str,
    name: str,
    kind: int = 1,
    label: str | None = None,
    foreground_color: str | None = None,
    background_color: str | None = None,
    type_id: str | None = None,
    source_thought_id: str | None = None,
    relation: int | None = None,
    ac_type: int = 0,
) -> dict[str, Any]:
    """Create a new thought with optional visual properties.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        name: The name of the thought
        kind: Kind of thought (1=Normal, 2=Type, 3=Event, 4=Tag, 5=System)
        label: Optional label for the thought
        foreground_color: Foreground color in hex format (e.g., "#ff0000")
        background_color: Background color in hex format (e.g., "#0000ff")
        type_id: ID of the thought type to assign
        source_thought_id: ID of the source thought to link from
        relation: Relation type if linking (1=Child, 2=Parent, 3=Jump, 4=Sibling)
        ac_type: Access type (0=Public, 1=Private)

    Returns:
        Dictionary with success status and thought details
    """
    try:
        thought_data: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "acType": ac_type,
        }

        # Add optional properties
        if label:
            thought_data["label"] = label
        if type_id:
            thought_data["typeId"] = type_id
        if source_thought_id:
            thought_data["sourceThoughtId"] = source_thought_id
            thought_data["relation"] = relation or 1  # Default to Child

        # Create the thought
        result = await api.create_thought(brain_id, thought_data)
        thought_id = result.get("id")

        if not thought_id:
            raise Exception("Failed to create thought - no ID returned")

        # Apply visual properties if provided
        if foreground_color or background_color:
            updates = {}
            if foreground_color:
                updates["foregroundColor"] = foreground_color
            if background_color:
                updates["backgroundColor"] = background_color

            await api.update_thought(brain_id, thought_id, updates)

        return {
            "success": True,
            "thought": {
                "id": thought_id,
                "name": name,
                "brainId": brain_id,
                "kind": kind,
                "kindName": get_kind_name(kind),
                "label": label,
                "foregroundColor": foreground_color,
                "backgroundColor": background_color,
                "typeId": type_id,
                "acType": ac_type,
                "acTypeName": get_access_type_name(ac_type),
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_thought_by_name_tool(
    api: TheBrainAPI, brain_id: str, name_exact: str
) -> dict[str, Any]:
    """Find a thought by its exact name.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        name_exact: The exact name to match (case-sensitive)

    Returns:
        Dictionary with success status and thought details, or not-found message
    """
    try:
        thought = await api.get_thought_by_name(brain_id, name_exact)
        if thought is None:
            return {"success": False, "error": f"No thought found with exact name: {name_exact}"}
        return {
            "success": True,
            "thought": {
                "id": thought.id,
                "brainId": thought.brain_id,
                "name": thought.name,
                "label": thought.label,
                "kind": thought.kind,
                "kindName": get_kind_name(thought.kind),
                "typeId": thought.type_id,
                "foregroundColor": thought.foreground_color,
                "backgroundColor": thought.background_color,
                "acType": thought.ac_type,
                "acTypeName": get_access_type_name(thought.ac_type),
                "creationDateTime": (
                    thought.creation_date_time.isoformat() if thought.creation_date_time else None
                ),
                "modificationDateTime": (
                    thought.modification_date_time.isoformat()
                    if thought.modification_date_time
                    else None
                ),
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_thought_tool(api: TheBrainAPI, brain_id: str, thought_id: str) -> dict[str, Any]:
    """Get details about a specific thought.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought

    Returns:
        Dictionary with success status and thought details
    """
    try:
        thought = await api.get_thought(brain_id, thought_id)
        return {
            "success": True,
            "thought": {
                "id": thought.id,
                "brainId": thought.brain_id,
                "name": thought.name,
                "label": thought.label,
                "kind": thought.kind,
                "kindName": get_kind_name(thought.kind),
                "typeId": thought.type_id,
                "foregroundColor": thought.foreground_color,
                "backgroundColor": thought.background_color,
                "acType": thought.ac_type,
                "acTypeName": get_access_type_name(thought.ac_type),
                "creationDateTime": (
                    thought.creation_date_time.isoformat() if thought.creation_date_time else None
                ),
                "modificationDateTime": (
                    thought.modification_date_time.isoformat()
                    if thought.modification_date_time
                    else None
                ),
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def update_thought_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    name: str | None = None,
    label: str | None = None,
    foreground_color: str | None = None,
    background_color: str | None = None,
    kind: int | None = None,
    ac_type: int | None = None,
    type_id: str | None = None,
) -> dict[str, Any]:
    """Update a thought including its visual properties.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought to update
        name: New name for the thought
        label: New label for the thought
        foreground_color: New foreground color in hex format
        background_color: New background color in hex format
        kind: New kind
        ac_type: New access type
        type_id: New type ID to assign

    Returns:
        Dictionary with success status and update details
    """
    try:
        updates = {}

        # Build update object with only provided fields
        if name is not None:
            updates["name"] = name
        if label is not None:
            updates["label"] = label
        if foreground_color is not None:
            updates["foregroundColor"] = foreground_color
        if background_color is not None:
            updates["backgroundColor"] = background_color
        if kind is not None:
            updates["kind"] = kind
        if ac_type is not None:
            updates["acType"] = ac_type
        if type_id is not None:
            updates["typeId"] = type_id

        await api.update_thought(brain_id, thought_id, updates)

        return {
            "success": True,
            "message": f"Thought {thought_id} updated successfully",
            "updates": updates,
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def delete_thought_tool(
    api: TheBrainAPI, brain_id: str, thought_id: str
) -> dict[str, Any]:
    """Delete a thought.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought

    Returns:
        Dictionary with success status and message
    """
    try:
        await api.delete_thought(brain_id, thought_id)
        return {
            "success": True,
            "message": f"Thought {thought_id} deleted successfully",
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def search_thoughts_tool(
    api: TheBrainAPI,
    brain_id: str,
    query_text: str,
    max_results: int = 30,
    only_search_thought_names: bool = False,
) -> dict[str, Any]:
    """Search for thoughts in a brain.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        query_text: Search query text
        max_results: Maximum number of results
        only_search_thought_names: Only search in thought names (not content)

    Returns:
        Dictionary with success status and search results
    """
    try:
        results = await api.search_thoughts(
            brain_id, query_text, max_results, only_search_thought_names
        )

        return {
            "success": True,
            "count": len(results),
            "results": [
                {
                    "thoughtId": result.source_thought.id if result.source_thought else None,
                    "name": result.name or (result.source_thought.name if result.source_thought else None),
                    "matchType": get_search_result_type_name(result.search_result_type),
                    "attachmentId": result.attachment_id,
                    "linkId": result.source_link.id if result.source_link else None,
                }
                for result in results
            ],
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_thought_graph_tool(
    api: TheBrainAPI, brain_id: str, thought_id: str, include_siblings: bool = False
) -> dict[str, Any]:
    """Get a thought with all its connections and attachments.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought
        include_siblings: Include sibling thoughts in the graph

    Returns:
        Dictionary with success status and thought graph
    """
    try:
        graph = await api.get_thought_graph(brain_id, thought_id, include_siblings)

        def format_thought(thought: Any) -> dict[str, Any]:
            """Format thought for output."""
            return {
                "id": thought.id,
                "name": thought.name,
                "label": thought.label,
                "kind": thought.kind,
                "kindName": get_kind_name(thought.kind),
                "foregroundColor": thought.foreground_color,
                "backgroundColor": thought.background_color,
            }

        def format_link(link: Any) -> dict[str, Any]:
            """Format link for output."""
            return {
                "id": link.id,
                "thoughtIdA": link.thought_id_a,
                "thoughtIdB": link.thought_id_b,
                "name": link.name,
                "color": link.color,
                "thickness": link.thickness,
                "relation": link.relation,
                "direction": link.direction,
            }

        def format_attachment(att: Any) -> dict[str, Any]:
            """Format attachment for output."""
            return {
                "id": att.id,
                "name": att.name,
                "type": att.type,
                "location": att.location,
                "dataLength": att.data_length,
            }

        return {
            "success": True,
            "graph": {
                "activeThought": format_thought(graph.active_thought),
                "parents": [format_thought(t) for t in graph.parents] if graph.parents else [],
                "children": [format_thought(t) for t in graph.children] if graph.children else [],
                "jumps": [format_thought(t) for t in graph.jumps] if graph.jumps else [],
                "siblings": [format_thought(t) for t in graph.siblings] if graph.siblings else [],
                "tags": [format_thought(t) for t in graph.tags] if graph.tags else [],
                "type": format_thought(graph.type) if graph.type else None,
                "links": [format_link(link) for link in graph.links] if graph.links else [],
                "attachments": [format_attachment(att) for att in graph.attachments]
                if graph.attachments
                else [],
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_types_tool(api: TheBrainAPI, brain_id: str) -> dict[str, Any]:
    """Get all thought types in a brain.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain

    Returns:
        Dictionary with success status and list of types
    """
    try:
        types = await api.get_types(brain_id)

        return {
            "success": True,
            "types": [
                {
                    "id": t.id,
                    "name": t.name,
                    "label": t.label,
                    "kind": t.kind,
                    "kindName": get_kind_name(t.kind),
                    "foregroundColor": t.foreground_color,
                    "backgroundColor": t.background_color,
                }
                for t in types
            ],
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_tags_tool(api: TheBrainAPI, brain_id: str) -> dict[str, Any]:
    """Get all tags in a brain.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain

    Returns:
        Dictionary with success status and list of tags
    """
    try:
        tags = await api.get_tags(brain_id)

        return {
            "success": True,
            "tags": [
                {
                    "id": t.id,
                    "name": t.name,
                    "label": t.label,
                    "kind": t.kind,
                    "kindName": get_kind_name(t.kind),
                    "foregroundColor": t.foreground_color,
                    "backgroundColor": t.background_color,
                }
                for t in tags
            ],
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Paginated graph traversal
# ---------------------------------------------------------------------------

_RELATION_FILTER_MAP = {
    "child": "children",
    "children": "children",
    "parent": "parents",
    "parents": "parents",
    "jump": "jumps",
    "jumps": "jumps",
    "sibling": "siblings",
    "siblings": "siblings",
}


def _collect_related_thoughts(graph: Any, relation_filter: str | None) -> list[dict[str, Any]]:
    """Flatten graph relations into a list of dicts with relation labels.

    Each entry includes the thought data and which relation bucket it came from.
    """
    buckets: dict[str, str] = {
        "children": "child",
        "parents": "parent",
        "jumps": "jump",
        "siblings": "sibling",
    }

    items: list[dict[str, Any]] = []
    for attr, relation_label in buckets.items():
        thoughts = getattr(graph, attr, None) or []
        for t in thoughts:
            items.append({
                "id": t.id,
                "name": t.name,
                "label": t.label,
                "kind": t.kind,
                "kindName": get_kind_name(t.kind),
                "relation": relation_label,
                "modificationDateTime": (
                    t.modification_date_time.isoformat()
                    if t.modification_date_time
                    else None
                ),
                "_sort_dt": t.modification_date_time,
            })

    return items


def _count_relations(all_items: list[dict[str, Any]]) -> dict[str, int]:
    """Count items per relation type (always computed from full unfiltered set)."""
    counts: dict[str, int] = {"children": 0, "parents": 0, "jumps": 0, "siblings": 0}
    relation_to_bucket = {"child": "children", "parent": "parents", "jump": "jumps", "sibling": "siblings"}
    for item in all_items:
        bucket = relation_to_bucket.get(item["relation"], "")
        if bucket in counts:
            counts[bucket] += 1
    return counts


def _parse_cursor(cursor: str) -> tuple[datetime, str]:
    """Parse a composite cursor 'ISO_TIMESTAMP|THOUGHT_ID' into its parts."""
    parts = cursor.split("|", 1)
    cursor_dt = datetime.fromisoformat(parts[0])
    cursor_id = parts[1] if len(parts) > 1 else ""
    return cursor_dt, cursor_id


def paginate_graph(
    all_items: list[dict[str, Any]],
    page_size: int,
    cursor: str | None,
    direction: str,
    relation_filter: str | None,
) -> dict[str, Any]:
    """Sort, filter, and paginate a flat list of related thoughts.

    Args:
        all_items: Full list from _collect_related_thoughts
        page_size: Number of items per page
        cursor: Composite cursor 'ISO_TIMESTAMP|THOUGHT_ID' (None for first page)
        direction: "older" or "newer"
        relation_filter: Optional relation type to filter by

    Returns:
        Dict with page, next_cursor, total_count, relation_counts, has_more
    """
    # Global counts before filtering
    relation_counts = _count_relations(all_items)

    # Apply relation filter
    if relation_filter:
        normalized = _RELATION_FILTER_MAP.get(relation_filter.lower())
        if normalized:
            bucket_to_label = {"children": "child", "parents": "parent", "jumps": "jump", "siblings": "sibling"}
            target_label = bucket_to_label[normalized]
            filtered = [i for i in all_items if i["relation"] == target_label]
        else:
            filtered = all_items
    else:
        filtered = all_items

    total_count = len(filtered)

    # Sentinel for thoughts without modification dates
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
        return (item["_sort_dt"] or epoch, item["id"])

    # Sort: newest first for "older", oldest first for "newer"
    descending = direction != "newer"
    filtered.sort(key=sort_key, reverse=descending)

    # Apply cursor — exclude items at or before the cursor position
    if cursor:
        cursor_dt, cursor_id = _parse_cursor(cursor)
        cursor_key = (cursor_dt, cursor_id)
        if descending:
            # "older": items are sorted newest→oldest, skip everything >= cursor
            filtered = [i for i in filtered if sort_key(i) < cursor_key]
        else:
            # "newer": items are sorted oldest→newest, skip everything <= cursor
            filtered = [i for i in filtered if sort_key(i) > cursor_key]

    # Slice page
    page = filtered[:page_size]
    has_more = len(filtered) > page_size

    # Build next cursor from last item in page
    next_cursor = None
    if has_more and page:
        last = page[-1]
        last_dt = last["_sort_dt"] or epoch
        next_cursor = f"{last_dt.isoformat()}|{last['id']}"

    # Strip internal sort key from output
    clean_page = [{k: v for k, v in item.items() if k != "_sort_dt"} for item in page]

    return {
        "page": clean_page,
        "next_cursor": next_cursor,
        "total_count": total_count,
        "relation_counts": relation_counts,
        "page_size": page_size,
        "direction": direction,
        "has_more": has_more,
    }


async def get_thought_graph_paginated_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    page_size: int = 10,
    cursor: str | None = None,
    direction: str = "older",
    relation_filter: str | None = None,
) -> dict[str, Any]:
    """Get a thought's connections with cursor-based pagination.

    Fetches the full graph from TheBrain on each call, sorts by
    modificationDateTime (desc for "older", asc for "newer"), and returns
    a page slice with cursor for the next page.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought
        page_size: Number of results per page (default 10)
        cursor: Pagination cursor from a previous response (None for first page)
        direction: "older" (newest first, default) or "newer" (oldest first)
        relation_filter: Filter by relation type: "child", "parent", "jump", "sibling", or None for all

    Returns:
        Dictionary with paginated results, cursor, counts, and has_more flag
    """
    try:
        graph = await api.get_thought_graph(brain_id, thought_id, include_siblings=True)

        # Collect all related thoughts with relation labels
        all_items = _collect_related_thoughts(graph, relation_filter=None)

        # Paginate
        result = paginate_graph(all_items, page_size, cursor, direction, relation_filter)

        # Add the active thought info
        result["thought"] = {
            "id": graph.active_thought.id,
            "name": graph.active_thought.name,
        }
        result["success"] = True

        return result

    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}
