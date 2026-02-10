"""Statistics and modification tools for TheBrain MCP server."""

from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.formatters import get_modification_type_name, get_source_type_name


async def get_modifications_tool(
    api: TheBrainAPI,
    brain_id: str,
    max_logs: int = 100,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Get modification history for a brain.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        max_logs: Maximum number of logs to return
        start_time: Start time for logs (ISO format)
        end_time: End time for logs (ISO format)

    Returns:
        Dictionary with success status and modification history
    """
    try:
        modifications = await api.get_brain_modifications(
            brain_id, max_logs, start_time, end_time
        )

        return {
            "success": True,
            "count": len(modifications),
            "modifications": [
                {
                    "sourceId": mod.source_id,
                    "sourceType": mod.source_type,
                    "sourceTypeName": get_source_type_name(mod.source_type),
                    "modType": mod.mod_type,
                    "modTypeName": get_modification_type_name(mod.mod_type),
                    "oldValue": mod.old_value,
                    "newValue": mod.new_value,
                    "userId": mod.user_id,
                    "creationDateTime": (
                        mod.creation_date_time.isoformat() if mod.creation_date_time else None
                    ),
                    "modificationDateTime": (
                        mod.modification_date_time.isoformat()
                        if mod.modification_date_time
                        else None
                    ),
                    "extraAId": mod.extra_a_id,
                    "extraBId": mod.extra_b_id,
                }
                for mod in modifications
            ],
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}
