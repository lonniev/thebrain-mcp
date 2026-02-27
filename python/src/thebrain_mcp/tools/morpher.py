"""Morpher tool: atomically reparent and/or retype a thought."""

import logging
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError

logger = logging.getLogger(__name__)


async def morpher_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    new_parent_id: str | None = None,
    new_type_id: str | None = None,
) -> dict[str, Any]:
    """Reparent and/or retype a thought in a single orchestrated operation.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The thought to morph
        new_parent_id: New parent thought ID (replaces all current parents)
        new_type_id: New type ID to assign

    Returns:
        Summary dict with old/new parents, old/new type, and links modified
    """
    if not new_parent_id and not new_type_id:
        return {
            "success": False,
            "error": "At least one of new_parent_id or new_type_id must be provided.",
        }

    try:
        graph = await api.get_thought_graph(brain_id, thought_id)
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}

    result: dict[str, Any] = {"success": True, "thought_id": thought_id}

    # --- Reparent ---
    if new_parent_id:
        old_parents = [
            {"id": p.id, "name": p.name} for p in (graph.parents or [])
        ]
        parent_ids = {p.id for p in (graph.parents or [])}

        # Find parent links: relation==1 (Child), thoughtIdA is a parent, thoughtIdB is our thought
        parent_links = [
            link for link in (graph.links or [])
            if link.relation == 1
            and link.thought_id_a in parent_ids
            and link.thought_id_b == thought_id
        ]

        deleted_link_ids = []
        try:
            for link in parent_links:
                try:
                    await api.delete_link(brain_id, link.id)
                except TheBrainAPIError as e:
                    if "400" in str(e):
                        # Stale graph cache: link already deleted server-side
                        logger.debug("Link %s already gone (stale cache): %s", link.id, e)
                    else:
                        raise
                deleted_link_ids.append(link.id)

            new_link = await api.create_link(brain_id, {
                "thoughtIdA": new_parent_id,
                "thoughtIdB": thought_id,
                "relation": 1,
            })
        except TheBrainAPIError as e:
            return {"success": False, "error": str(e)}

        result["reparent"] = {
            "old_parents": old_parents,
            "new_parent_id": new_parent_id,
            "deleted_links": deleted_link_ids,
            "created_link_id": new_link.get("id"),
        }

    # --- Retype ---
    if new_type_id:
        old_type_id = graph.active_thought.type_id
        try:
            await api.update_thought(brain_id, thought_id, {"typeId": new_type_id})
        except TheBrainAPIError as e:
            return {"success": False, "error": str(e)}

        result["retype"] = {
            "old_type_id": old_type_id,
            "new_type_id": new_type_id,
        }

    return result
