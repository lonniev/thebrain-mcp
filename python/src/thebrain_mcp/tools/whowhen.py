"""WhoWhen tool: create an Event linked to a Person and a Day in one action."""

import re
from typing import Any

from dateutil import parser as dateutil_parser

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.constants import RelationType, ThoughtKind


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _parse_date(date_str: str) -> tuple[int, str, int]:
    """Parse a flexible date string into (year, month_name, day).

    Raises ValueError on unparseable input.
    """
    dt = dateutil_parser.parse(date_str, fuzzy=True)
    return dt.year, dt.strftime("%B"), dt.day


async def _find_person_type_id(api: TheBrainAPI, brain_id: str) -> str | None:
    """Find the Person type ID from the brain's type list."""
    types = await api.get_types(brain_id)
    for t in types:
        if t.name.lower() == "person":
            return t.id
    return None


async def _resolve_person(
    api: TheBrainAPI,
    brain_id: str,
    person: str,
    person_type_id: str | None,
    home_id: str,
) -> tuple[str, str, bool]:
    """Resolve a person by UUID or name search.

    Returns (person_id, person_name, was_created).
    Raises ValueError for disambiguation.
    """
    # Direct UUID lookup
    if _UUID_RE.match(person):
        thought = await api.get_thought(brain_id, person)
        return thought.id, thought.name, False

    # Search by name
    results = await api.search_thoughts(
        brain_id, person, max_results=5, only_search_thought_names=True
    )

    # Filter for Person-typed thoughts if we know the type
    if person_type_id:
        typed = [
            r for r in results
            if r.source_thought and r.source_thought.type_id == person_type_id
        ]
        if typed:
            results = typed

    # Collect unique thoughts from results
    candidates = []
    seen_ids: set[str] = set()
    for r in results:
        if r.source_thought and r.source_thought.id not in seen_ids:
            seen_ids.add(r.source_thought.id)
            candidates.append(r.source_thought)

    if len(candidates) == 1:
        return candidates[0].id, candidates[0].name, False

    if len(candidates) > 1:
        raise ValueError({
            "disambiguation_needed": True,
            "candidates": [
                {"id": c.id, "name": c.name, "type_id": c.type_id}
                for c in candidates
            ],
        })

    # No matches — create new Person
    create_data: dict[str, Any] = {
        "name": person,
        "kind": ThoughtKind.NORMAL,
        "sourceThoughtId": home_id,
        "relation": 1,
    }
    if person_type_id:
        create_data["typeId"] = person_type_id

    result = await api.create_thought(brain_id, create_data)
    return result["id"], person, True


async def _resolve_day(
    api: TheBrainAPI,
    brain_id: str,
    year: int,
    month_name: str,
    day: int,
    home_id: str,
) -> tuple[str, dict[str, bool]]:
    """Find or create the Day thought in the calendar hierarchy.

    Calendar structure: "2026" → "February, 2026" → "24, February, 2026"

    Returns (day_thought_id, {"year": created, "month": created, "day": created}).
    """
    day_name = f"{day}, {month_name}, {year}"
    month_name_full = f"{month_name}, {year}"
    year_name = str(year)

    created = {"year": False, "month": False, "day": False}

    # Try to find the Day thought directly
    day_thought = await api.get_thought_by_name(brain_id, day_name)
    if day_thought:
        return day_thought.id, created

    # Day doesn't exist — find or create month
    month_thought = await api.get_thought_by_name(brain_id, month_name_full)
    if not month_thought:
        # Month doesn't exist — find or create year
        year_thought = await api.get_thought_by_name(brain_id, year_name)
        if not year_thought:
            # Create year under home
            yr_result = await api.create_thought(brain_id, {
                "name": year_name,
                "kind": ThoughtKind.NORMAL,
                "sourceThoughtId": home_id,
                "relation": 1,
            })
            year_id = yr_result["id"]
            created["year"] = True
        else:
            year_id = year_thought.id

        # Create month under year
        mo_result = await api.create_thought(brain_id, {
            "name": month_name_full,
            "kind": ThoughtKind.NORMAL,
            "sourceThoughtId": year_id,
            "relation": 1,
        })
        month_id = mo_result["id"]
        created["month"] = True
    else:
        month_id = month_thought.id

    # Create day under month
    day_result = await api.create_thought(brain_id, {
        "name": day_name,
        "kind": ThoughtKind.NORMAL,
        "sourceThoughtId": month_id,
        "relation": 1,
    })
    created["day"] = True
    return day_result["id"], created


async def event_for_person_tool(
    api: TheBrainAPI,
    brain_id: str,
    date: str,
    person: str,
    event_name: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create an Event thought linked to a Person and a Day.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        date: Flexible date string (ISO, natural language, etc.)
        person: Full name or thought UUID
        event_name: Custom event name (auto-generated if omitted)
        notes: Optional markdown note for the Event

    Returns:
        Summary dict with event, person, and day details
    """
    # Step 1 — Parse date
    try:
        year, month_name, day = _parse_date(date)
    except (ValueError, OverflowError) as e:
        return {"success": False, "error": f"Could not parse date: {e}"}

    # Get brain info for home thought
    try:
        brain = await api.get_brain(brain_id)
        home_id = brain.home_thought_id
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}

    # Step 2 — Resolve Person
    try:
        person_type_id = await _find_person_type_id(api, brain_id)
    except TheBrainAPIError as e:
        return {"success": False, "error": f"Failed to fetch types: {e}"}

    try:
        person_id, person_name, person_created = await _resolve_person(
            api, brain_id, person, person_type_id, home_id
        )
    except ValueError as disambiguation:
        return {"success": False, **disambiguation.args[0]}
    except TheBrainAPIError as e:
        return {"success": False, "error": f"Person resolution failed: {e}"}

    # Step 3 — Resolve Day
    try:
        day_id, calendar_created = await _resolve_day(
            api, brain_id, year, month_name, day, home_id
        )
    except TheBrainAPIError as e:
        return {"success": False, "error": f"Calendar resolution failed: {e}"}

    # Step 4 — Create Event
    resolved_event_name = event_name or f"Event with {person_name}"
    structured_name = f"{year},{month_name},{day:02d}, {resolved_event_name}, {person_name}"

    try:
        event_result = await api.create_thought(brain_id, {
            "name": structured_name,
            "kind": ThoughtKind.EVENT,
        })
        event_id = event_result["id"]
    except TheBrainAPIError as e:
        return {"success": False, "error": f"Event creation failed: {e}"}

    # Step 5 — Create jump-links
    try:
        await api.create_link(brain_id, {
            "thoughtIdA": event_id,
            "thoughtIdB": person_id,
            "relation": RelationType.JUMP,
        })
        await api.create_link(brain_id, {
            "thoughtIdA": event_id,
            "thoughtIdB": day_id,
            "relation": RelationType.JUMP,
        })
    except TheBrainAPIError as e:
        return {"success": False, "error": f"Link creation failed: {e}"}

    # Step 6 — Optional notes
    if notes:
        try:
            await api.create_or_update_note(brain_id, event_id, notes)
        except TheBrainAPIError as e:
            return {"success": False, "error": f"Note creation failed: {e}"}

    # Step 7 — Return summary
    return {
        "success": True,
        "event_id": event_id,
        "event_name": structured_name,
        "person_id": person_id,
        "person_name": person_name,
        "person_created": person_created,
        "day_id": day_id,
        "day_name": f"{day}, {month_name}, {year}",
        "calendar_created": calendar_created,
    }
