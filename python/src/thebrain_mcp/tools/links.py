"""Link operation tools for TheBrain MCP server."""

from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.formatters import (
    get_direction_info,
    get_link_kind_name,
    get_link_meaning_name,
    get_relation_name,
)


async def create_link_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id_a: str,
    thought_id_b: str,
    relation: int,
    name: str | None = None,
    color: str | None = None,
    thickness: int | None = None,
    direction: int | None = None,
    type_id: str | None = None,
) -> dict[str, Any]:
    """Create a link between two thoughts with visual properties.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id_a: ID of the first thought
        thought_id_b: ID of the second thought
        relation: Relation type (1=Child, 2=Parent, 3=Jump, 4=Sibling)
        name: Label for the link
        color: Link color in hex format (e.g., "#6fbf6f")
        thickness: Link thickness (1-10)
        direction: Direction flags (0=Undirected, 1=Directed, etc.)
        type_id: ID of link type

    Returns:
        Dictionary with success status and link details
    """
    try:
        # Create the basic link
        link_data: dict[str, Any] = {
            "thoughtIdA": thought_id_a,
            "thoughtIdB": thought_id_b,
            "relation": relation,
        }

        if name:
            link_data["name"] = name

        result = await api.create_link(brain_id, link_data)
        link_id = result.get("id")

        if not link_id:
            raise Exception("Failed to create link - no ID returned")

        # Apply visual properties if provided
        if color or thickness is not None or direction is not None or type_id:
            updates = {}
            if color:
                updates["color"] = color
            if thickness is not None:
                updates["thickness"] = thickness
            if direction is not None:
                updates["direction"] = direction
            if type_id:
                updates["typeId"] = type_id

            await api.update_link(brain_id, link_id, updates)

        return {
            "success": True,
            "link": {
                "id": link_id,
                "brainId": brain_id,
                "thoughtIdA": thought_id_a,
                "thoughtIdB": thought_id_b,
                "relation": relation,
                "relationName": get_relation_name(relation),
                "name": name,
                "color": color,
                "thickness": thickness,
                "direction": direction,
                "directionInfo": get_direction_info(direction),
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def update_link_tool(
    api: TheBrainAPI,
    brain_id: str,
    link_id: str,
    name: str | None = None,
    color: str | None = None,
    thickness: int | None = None,
    direction: int | None = None,
    relation: int | None = None,
) -> dict[str, Any]:
    """Update link properties including visual formatting.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        link_id: The ID of the link to update
        name: New label for the link
        color: New link color in hex format
        thickness: New link thickness (1-10)
        direction: New direction flags
        relation: New relation type

    Returns:
        Dictionary with success status and update details
    """
    try:
        updates = {}

        # Build update object with only provided fields
        if name is not None:
            updates["name"] = name
        if color is not None:
            updates["color"] = color
        if thickness is not None:
            updates["thickness"] = thickness
        if direction is not None:
            updates["direction"] = direction
        if relation is not None:
            updates["relation"] = relation

        await api.update_link(brain_id, link_id, updates)

        result: dict[str, Any] = {
            "success": True,
            "message": f"Link {link_id} updated successfully",
            "updates": {**updates},
        }

        if relation is not None:
            result["updates"]["relationName"] = get_relation_name(relation)
        if direction is not None:
            result["updates"]["directionInfo"] = get_direction_info(direction)

        return result
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_link_tool(api: TheBrainAPI, brain_id: str, link_id: str) -> dict[str, Any]:
    """Get details about a specific link.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        link_id: The ID of the link

    Returns:
        Dictionary with success status and link details
    """
    try:
        link = await api.get_link(brain_id, link_id)
        return {
            "success": True,
            "link": {
                "id": link.id,
                "brainId": link.brain_id,
                "thoughtIdA": link.thought_id_a,
                "thoughtIdB": link.thought_id_b,
                "name": link.name,
                "color": link.color,
                "thickness": link.thickness,
                "relation": link.relation,
                "relationName": get_relation_name(link.relation),
                "direction": link.direction,
                "directionInfo": get_direction_info(link.direction),
                "meaning": link.meaning,
                "meaningName": get_link_meaning_name(link.meaning) if link.meaning else None,
                "kind": link.kind,
                "kindName": get_link_kind_name(link.kind) if link.kind else None,
                "typeId": link.type_id,
                "creationDateTime": (
                    link.creation_date_time.isoformat() if link.creation_date_time else None
                ),
                "modificationDateTime": (
                    link.modification_date_time.isoformat()
                    if link.modification_date_time
                    else None
                ),
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def delete_link_tool(api: TheBrainAPI, brain_id: str, link_id: str) -> dict[str, Any]:
    """Delete a link.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        link_id: The ID of the link

    Returns:
        Dictionary with success status and message
    """
    try:
        await api.delete_link(brain_id, link_id)
        return {
            "success": True,
            "message": f"Link {link_id} deleted successfully",
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}
