"""Orphanage tool: find and rescue unreachable thoughts with zero connections."""

from datetime import date, timezone
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.constants import (
    ModificationType,
    SourceType,
    ThoughtKind,
)

# Well-known IDs from the brain
COLLECTION_TYPE_ID = "abc1a94c-b822-53d4-b46e-be9c205db3e2"
TODO_TAG_ID = "065c5285-d785-5244-9b64-1d50d026282a"

MAX_BATCH_SIZE = 100


async def _build_census(
    api: TheBrainAPI,
    brain_id: str,
) -> set[str]:
    """Enumerate all living thought IDs via modification history.

    Walks year-windows from 2000 to the current year, collecting CREATED
    thought events and subtracting DELETED ones.
    """
    created: set[str] = set()
    deleted: set[str] = set()

    current_year = date.today().year

    for year in range(2000, current_year + 1):
        mods = await api.get_brain_modifications(
            brain_id,
            max_logs=100_000,
            start_time=f"{year}-01-01T00:00:00Z",
            end_time=f"{year + 1}-01-01T00:00:00Z",
        )
        for mod in mods:
            if mod.source_type == SourceType.THOUGHT:
                if mod.mod_type == ModificationType.CREATED:
                    created.add(mod.source_id)
                elif mod.mod_type == ModificationType.DELETED:
                    deleted.add(mod.source_id)

    return created - deleted


def _is_orphan(graph: Any, home_thought_id: str) -> bool:
    """Check whether a thought graph represents an orphan.

    An orphan is a normal (kind=1) thought with zero connections
    (no parents, children, jumps, siblings, or tags) and is not
    the home thought.
    """
    t = graph.active_thought

    # Skip non-normal thoughts (Types, Tags, Events, System)
    if t.kind != ThoughtKind.NORMAL:
        return False

    # Skip the home thought
    if t.id == home_thought_id:
        return False

    return (
        not graph.parents
        and not graph.children
        and not graph.jumps
        and not graph.siblings
        and not graph.tags
    )


async def scan_orphans_tool(
    api: TheBrainAPI,
    brain_id: str,
    dry_run: bool = True,
    batch_size: int = 50,
    orphanage_name: str = "Orphanage",
) -> dict[str, Any]:
    """Scan for orphaned thoughts and optionally rescue them.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        dry_run: If True, report orphans only; if False, adopt them
        batch_size: How many thoughts to check per batch (capped at 100)
        orphanage_name: Name of the collection thought to parent orphans under

    Returns:
        Summary dict with census size, orphans found, and adoption details
    """
    batch_size = min(batch_size, MAX_BATCH_SIZE)

    try:
        brain = await api.get_brain(brain_id)
        home_thought_id = brain.home_thought_id
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}

    # Phase 1: Census
    try:
        census = await _build_census(api, brain_id)
    except TheBrainAPIError as e:
        return {"success": False, "error": f"Census failed: {e}"}

    if not census:
        return {
            "success": True,
            "census_size": 0,
            "scanned": 0,
            "orphans_found": 0,
            "orphans": [],
            "adopted": 0,
            "orphanage_id": None,
            "dry_run": dry_run,
        }

    # Phase 2: Scan
    orphans: list[dict[str, Any]] = []
    scanned = 0
    census_list = list(census)

    for i in range(0, len(census_list), batch_size):
        batch = census_list[i : i + batch_size]
        for thought_id in batch:
            try:
                graph = await api.get_thought_graph(brain_id, thought_id)
            except TheBrainAPIError:
                # 404 or other error — thought deleted between census and scan
                continue

            scanned += 1

            if _is_orphan(graph, home_thought_id):
                t = graph.active_thought
                orphans.append({
                    "id": t.id,
                    "name": t.name,
                    "kind": t.kind,
                    "created": (
                        t.creation_date_time.isoformat()
                        if t.creation_date_time
                        else None
                    ),
                })

    # Phase 3: Adopt (if not dry_run)
    adopted = 0
    orphanage_id = None

    if not dry_run and orphans:
        try:
            orphanage_id = await _find_or_create_orphanage(
                api, brain_id, home_thought_id, orphanage_name
            )

            today = date.today().isoformat()
            for orphan in orphans:
                # Parent orphan under Orphanage
                await api.create_link(brain_id, {
                    "thoughtIdA": orphanage_id,
                    "thoughtIdB": orphan["id"],
                    "relation": 1,
                })
                # Tag with @todo
                await api.create_link(brain_id, {
                    "thoughtIdA": TODO_TAG_ID,
                    "thoughtIdB": orphan["id"],
                    "relation": 1,
                })
                # Label for audit trail
                await api.update_thought(
                    brain_id, orphan["id"], {"label": f"Orphaned: {today}"}
                )
                adopted += 1
        except TheBrainAPIError as e:
            return {
                "success": False,
                "error": f"Adoption failed: {e}",
                "census_size": len(census),
                "scanned": scanned,
                "orphans_found": len(orphans),
                "orphans": orphans,
                "adopted": adopted,
                "orphanage_id": orphanage_id,
                "dry_run": dry_run,
            }

    return {
        "success": True,
        "census_size": len(census),
        "scanned": scanned,
        "orphans_found": len(orphans),
        "orphans": orphans,
        "adopted": adopted,
        "orphanage_id": orphanage_id,
        "dry_run": dry_run,
    }


async def _find_or_create_orphanage(
    api: TheBrainAPI,
    brain_id: str,
    home_thought_id: str,
    orphanage_name: str,
) -> str:
    """Find an existing Orphanage thought or create one under the home thought."""
    # Try to find existing
    existing = await api.get_thought_by_name(brain_id, orphanage_name)
    if existing:
        return existing.id

    # Create as child of home thought with Collection type
    result = await api.create_thought(brain_id, {
        "name": orphanage_name,
        "kind": ThoughtKind.NORMAL,
        "typeId": COLLECTION_TYPE_ID,
        "sourceThoughtId": home_thought_id,
        "relation": 1,
    })
    orphanage_id = result["id"]

    # Add explanatory note
    await api.create_or_update_note(
        brain_id,
        orphanage_id,
        "Orphaned thoughts rescued by scan_orphans. "
        "Review each and re-home or delete.",
    )

    return orphanage_id
