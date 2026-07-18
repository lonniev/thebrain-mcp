"""Statistics and modification tools for TheBrain MCP server.

The ``/brains/{id}/modifications`` change-log is the API's authoritative,
*uncached* record of every operation (CREATED / DELETED / SET_TYPE / MOVED_LINK,
…). Unlike ``get_thought_graph`` and ``search`` — which are served through the
vendor's Azure response cache and lag updates/deletes by hours-to-days — the
change-log reflects writes promptly. That makes it the right basis for both
read-after-write **confirmation** and recent-activity **discovery**.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.api.models import Modification
from thebrain_mcp.utils.formatters import get_modification_type_name, get_source_type_name


def since_marker(skew_seconds: int = 5) -> str:
    """An ISO timestamp to hand a mutating call *before* it writes.

    Backdated a few seconds so a confirmation query can't miss the change on a
    boundary (the vendor's log timestamps are naive ISO, so we keep this naive
    UTC to compare like-with-like).
    """
    marker = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=skew_seconds)
    return marker.isoformat()


def _parse_naive(iso: str | None) -> datetime | None:
    """Best-effort parse of an ISO string to a naive datetime, or None."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _format_mod(mod: Modification) -> dict[str, Any]:
    """Render a Modification as the tool-facing dict (shared by both tools)."""
    return {
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
            mod.modification_date_time.isoformat() if mod.modification_date_time else None
        ),
        "extraAId": mod.extra_a_id,
        "extraBId": mod.extra_b_id,
    }


async def change_confirmed(
    api: TheBrainAPI,
    brain_id: str,
    source_id: str,
    mod_types: list[int],
    since: str,
    *,
    retries: int = 3,
    delay: float = 0.3,
    match_link_endpoints: bool = False,
) -> dict[str, Any]:
    """Confirm a mutation actually landed by finding it in the change-log.

    The cached graph endpoint lags updates/deletes, so read-after-write against
    it is unreliable. This scans ``/modifications`` (uncached) for an entry that
    (a) occurred at/after ``since``, (b) has a ``mod_type`` in ``mod_types``, and
    (c) references ``source_id`` — either as the entry's own ``source_id`` or, when
    ``match_link_endpoints`` is set (for link ops like MOVED_LINK), as one of the
    link's endpoints (``extra_a_id`` / ``extra_b_id``).

    A bounded retry absorbs any small feed lag and distinguishes "not yet
    visible" from "confirmed absent". This mirrors the verify-don't-trust posture
    of ``retype_persisted`` / ``delete_link_verified``.

    Returns ``{"confirmed": bool, "checked_via": "modifications", "entry": {...}|None}``
    (with an ``error`` key if the log itself could not be read).
    """
    wanted = set(mod_types)
    since_dt = _parse_naive(since)
    last_error: str | None = None

    for attempt in range(max(1, retries)):
        try:
            mods = await api.get_brain_modifications(brain_id, start_time=since)
        except TheBrainAPIError as e:
            last_error = str(e)
            mods = []

        for mod in mods:
            if mod.mod_type not in wanted:
                continue
            matches = mod.source_id == source_id
            if not matches and match_link_endpoints:
                matches = source_id in (mod.extra_a_id, mod.extra_b_id)
            if not matches:
                continue
            # Guard against matching an older same-type op on the same source.
            if since_dt and mod.creation_date_time and mod.creation_date_time < since_dt:
                continue
            return {"confirmed": True, "checked_via": "modifications", "entry": _format_mod(mod)}

        if attempt < retries - 1:
            await asyncio.sleep(delay)

    result: dict[str, Any] = {"confirmed": False, "checked_via": "modifications", "entry": None}
    if last_error:
        result["error"] = last_error
    return result


async def get_modifications_tool(
    api: TheBrainAPI,
    brain_id: str,
    max_logs: int = 100,
    start_time: str | None = None,
    end_time: str | None = None,
    source_id: str | None = None,
    source_type: int | None = None,
    mod_types: list[int] | None = None,
) -> dict[str, Any]:
    """Get modification history for a brain, with optional filtering.

    The vendor endpoint only supports time/maxLogs, so ``source_id`` /
    ``source_type`` / ``mod_types`` are applied client-side to the returned page.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        max_logs: Maximum number of logs to fetch from the API (pre-filter)
        start_time: Start time for logs (ISO format)
        end_time: End time for logs (ISO format)
        source_id: Only return entries whose sourceId matches (one thought/link)
        source_type: Only return entries of this SourceType (2=Thought, 3=Link, …)
        mod_types: Only return entries whose modType is in this list (ModificationType)

    Returns:
        Dictionary with success status and (filtered) modification history
    """
    try:
        modifications = await api.get_brain_modifications(
            brain_id, max_logs, start_time, end_time
        )
        wanted_types = set(mod_types) if mod_types else None
        rows = [
            _format_mod(mod)
            for mod in modifications
            if (source_id is None or mod.source_id == source_id)
            and (source_type is None or mod.source_type == source_type)
            and (wanted_types is None or mod.mod_type in wanted_types)
        ]
        return {"success": True, "count": len(rows), "modifications": rows}
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}
