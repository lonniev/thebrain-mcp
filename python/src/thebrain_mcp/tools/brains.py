"""Brain management tools for TheBrain MCP server."""

from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.formatters import format_bytes


async def list_brains_tool(api: TheBrainAPI) -> dict[str, Any]:
    """List all available brains for the user.

    Args:
        api: TheBrain API client

    Returns:
        Dictionary with success status and list of brains
    """
    try:
        brains = await api.list_brains()
        return {
            "success": True,
            "brains": [
                {
                    "id": brain.id,
                    "name": brain.name,
                    "homeThoughtId": brain.home_thought_id,
                }
                for brain in brains
            ],
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_brain_tool(api: TheBrainAPI, brain_id: str) -> dict[str, Any]:
    """Get details about a specific brain.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain

    Returns:
        Dictionary with success status and brain details
    """
    try:
        brain = await api.get_brain(brain_id)
        return {
            "success": True,
            "brain": {
                "id": brain.id,
                "name": brain.name,
                "homeThoughtId": brain.home_thought_id,
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def set_active_brain_tool(api: TheBrainAPI, brain_id: str) -> dict[str, Any]:
    """Set the active brain for subsequent operations.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain to set as active

    Returns:
        Dictionary with success status and message
    """
    try:
        # Verify brain exists
        await api.get_brain(brain_id)
        return {
            "success": True,
            "message": f"Active brain set to {brain_id}",
            "brainId": brain_id,
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": f"Failed to set active brain: {str(e)}"}


async def get_brain_stats_tool(api: TheBrainAPI, brain_id: str) -> dict[str, Any]:
    """Get statistics about a brain.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain

    Returns:
        Dictionary with success status and brain statistics
    """
    try:
        stats = await api.get_brain_stats(brain_id)
        return {
            "success": True,
            "stats": {
                "brainName": stats.brain_name,
                "brainId": stats.brain_id,
                "dateGenerated": stats.date_generated.isoformat() if stats.date_generated else None,
                "thoughts": stats.thoughts,
                "forgottenThoughts": stats.forgotten_thoughts,
                "links": stats.links,
                "linksPerThought": stats.links_per_thought,
                "thoughtTypes": stats.thought_types,
                "linkTypes": stats.link_types,
                "tags": stats.tags,
                "notes": stats.notes,
                "attachments": {
                    "internalFiles": stats.internal_files,
                    "internalFolders": stats.internal_folders,
                    "externalFiles": stats.external_files,
                    "externalFolders": stats.external_folders,
                    "webLinks": stats.web_links,
                    "totalInternalSize": format_bytes(stats.internal_files_size),
                    "totalIconSize": format_bytes(stats.icons_files_size),
                },
                "visual": {
                    "assignedIcons": stats.assigned_icons,
                },
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}
