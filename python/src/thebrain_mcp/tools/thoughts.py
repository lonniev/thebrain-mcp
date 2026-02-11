"""Thought operation tools for TheBrain MCP server."""

from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.formatters import (
    get_access_type_name,
    get_kind_name,
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
        result = await api.get_thought_by_name(brain_id, name_exact)
        if result is None:
            return {"success": False, "error": f"No thought found with exact name: {name_exact}"}
        # Pass through debug info if API returned unexpected data
        if isinstance(result, dict) and result.get("_debug"):
            return {"success": False, "debug": result}
        thought = result
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
