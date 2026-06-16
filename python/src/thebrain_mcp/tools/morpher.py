"""Morpher tool: atomically reparent and/or retype a thought.

The reparent link-surgery is exposed as :func:`reparent_thought` so other
tools (notably ``update_thought``) can reuse the exact same logic instead of
duplicating it.
"""

import logging
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError

logger = logging.getLogger(__name__)


async def reparent_thought(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    new_parent_id: str,
    graph: Any,
) -> dict[str, Any]:
    """Replace a thought's parent link(s) with a single new parent.

    Deletes every existing parent child-link (relation==1) and creates one
    new child-link from ``new_parent_id``. This *replaces* the parent — it
    does not add an additional one.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The thought to reparent
        new_parent_id: The new parent thought ID
        graph: The thought's already-fetched graph (parents + links)

    Returns:
        Reparent-info dict: ``old_parents``, ``new_parent_id``,
        ``deleted_links``, ``created_link_id``, and ``undeletable_links``
        (only present when some links could not be deleted).

    Raises:
        TheBrainAPIError: if the new parent link cannot be created.
    """
    old_parents = [{"id": p.id, "name": p.name} for p in (graph.parents or [])]
    parent_ids = {p.id for p in (graph.parents or [])}

    # Find parent links: relation==1 (Child), thoughtIdA is a parent, thoughtIdB is our thought
    parent_links = [
        link for link in (graph.links or [])
        if link.relation == 1
        and link.thought_id_a in parent_ids
        and link.thought_id_b == thought_id
    ]

    deleted_link_ids = []
    undeletable_link_ids = []
    for link in parent_links:
        try:
            await api.delete_link_verified(brain_id, link.id)
        except TheBrainAPIError as e:
            # Link exists but API won't delete it — not a ghost
            logger.warning("Cannot delete link %s: %s", link.id, e)
            undeletable_link_ids.append(link.id)
            continue
        deleted_link_ids.append(link.id)

    new_link = await api.create_link(brain_id, {
        "thoughtIdA": new_parent_id,
        "thoughtIdB": thought_id,
        "relation": 1,
    })

    reparent_info: dict[str, Any] = {
        "old_parents": old_parents,
        "new_parent_id": new_parent_id,
        "deleted_links": deleted_link_ids,
        "created_link_id": new_link.get("id"),
    }
    if undeletable_link_ids:
        reparent_info["undeletable_links"] = undeletable_link_ids
    return reparent_info


async def morpher_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    new_parent_id: str | None = None,
    new_type_id: str | None = None,
) -> dict[str, Any]:
    """Reparent and/or retype a thought in a single orchestrated operation.

    Reparenting *replaces* the thought's existing parent link (the old parent
    child-link is deleted and a new one created); it does not add an
    additional parent.

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
        try:
            result["reparent"] = await reparent_thought(
                api, brain_id, thought_id, new_parent_id, graph
            )
        except TheBrainAPIError as e:
            return {"success": False, "error": str(e)}

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
