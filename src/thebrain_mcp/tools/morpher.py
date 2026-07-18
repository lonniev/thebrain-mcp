"""Morpher tool: atomically reparent and/or retype a thought.

The reparent link-surgery is exposed as :func:`reparent_thought` so other
tools (notably ``update_thought``) can reuse the exact same logic instead of
duplicating it.
"""

import logging
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.tools.stats import change_confirmed, since_marker
from thebrain_mcp.utils.constants import ModificationType

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
        ``deleted_links``, and ``created_link_id``.

    Raises:
        TheBrainAPIError: if any existing parent link cannot be deleted, or
            if the new parent link cannot be created. Reparenting is atomic:
            when an old parent link is undeletable the new link is never
            created and any already-deleted links are restored, so the
            thought is left with its original parent rather than in a
            half-moved state that reads back as unchanged.
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

    # Phase 1 — try to delete every old parent link, tracking which genuinely
    # deleted (candidates for rollback), which were ghosts (already gone), and
    # which the API refuses to delete (desktop-synced links).
    deleted_link_ids = []
    deleted_links = []  # real deletions only, kept for rollback
    undeletable_link_ids = []
    for link in parent_links:
        try:
            outcome = await api.delete_link_verified(brain_id, link.id)
        except TheBrainAPIError as e:
            # Link exists but API won't delete it — not a ghost
            logger.warning("Cannot delete link %s: %s", link.id, e)
            undeletable_link_ids.append(link.id)
            continue
        deleted_link_ids.append(link.id)
        if not outcome.get("ghost"):
            deleted_links.append(link)

    # Phase 2 — if any old parent link is undeletable the move cannot persist
    # (the read path would still resolve the surviving parent). Roll back the
    # deletions we did make and fail loudly rather than reporting a success
    # that silently reverts.
    if undeletable_link_ids:
        for link in deleted_links:
            try:
                await api.create_link(brain_id, {
                    "thoughtIdA": link.thought_id_a,
                    "thoughtIdB": link.thought_id_b,
                    "relation": link.relation,
                })
            except TheBrainAPIError as restore_error:
                logger.error(
                    "Rollback failed: could not restore parent link %s: %s",
                    link.id, restore_error,
                )
        raise TheBrainAPIError(
            "Reparent aborted: TheBrain API refused to delete existing parent "
            f"link(s) {undeletable_link_ids}, so the move cannot persist. "
            "These are typically links synced from the desktop app; delete them "
            "from the TheBrain desktop application, then retry."
        )

    # Phase 3 — old parents cleared; attach the new one.
    new_link = await api.create_link(brain_id, {
        "thoughtIdA": new_parent_id,
        "thoughtIdB": thought_id,
        "relation": 1,
    })

    return {
        "old_parents": old_parents,
        "new_parent_id": new_parent_id,
        "deleted_links": deleted_link_ids,
        "created_link_id": new_link.get("id"),
    }


async def retype_persisted(
    api: TheBrainAPI, brain_id: str, thought_id: str, expected_type_id: str
) -> bool:
    """Read the thought back and confirm its type actually changed.

    TheBrain's PATCH endpoint accepts a ``typeId`` change and returns success
    even when it silently declines to persist it (issue #187). Callers must
    therefore verify the write rather than trust the 2xx response.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The thought that was retyped
        expected_type_id: The type ID that should now be set

    Returns:
        True if the thought's type is now ``expected_type_id``, else False.

    Raises:
        TheBrainAPIError: if the read-back request itself fails.
    """
    thought = await api.get_thought(brain_id, thought_id)
    return thought.type_id == expected_type_id


async def morpher_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    new_parent_id: str | None = None,
    new_type_id: str | None = None,
    confirm: bool = False,
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

    # Marker for an optional change-log confirmation, captured before any write.
    since = since_marker() if confirm else None

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
            persisted = await retype_persisted(api, brain_id, thought_id, new_type_id)
        except TheBrainAPIError as e:
            return {"success": False, "error": str(e)}

        result["retype"] = {
            "old_type_id": old_type_id,
            "new_type_id": new_type_id,
            "persisted": persisted,
        }
        if not persisted:
            result["success"] = False
            result["error"] = (
                f"Retype did not persist: thought {thought_id} still has type "
                f"{old_type_id!r} after a request to set {new_type_id!r}. TheBrain "
                "accepted the request but did not apply the type change."
            )

    # Optional: prove the link/type surgery against the authoritative change-log
    # (the cached graph would hide these ops for hours-to-days).
    if confirm and since is not None:
        confirmation: dict[str, Any] = {}
        if new_parent_id:
            confirmation["reparent"] = await change_confirmed(
                api, brain_id, thought_id,
                [ModificationType.MOVED_LINK, ModificationType.CREATED,
                 ModificationType.DELETED],
                since, match_link_endpoints=True,
            )
        if new_type_id:
            confirmation["retype"] = await change_confirmed(
                api, brain_id, thought_id, [ModificationType.SET_TYPE], since
            )
        if confirmation:
            result["confirmation"] = confirmation

    return result
