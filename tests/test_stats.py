"""Tests for the modifications change-log helpers: confirmation + discovery."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from thebrain_mcp.api.client import TheBrainAPIError
from thebrain_mcp.api.models import Modification
from thebrain_mcp.tools.morpher import morpher_tool
from thebrain_mcp.tools.stats import (
    change_confirmed,
    get_modifications_tool,
    since_marker,
)
from thebrain_mcp.tools.thoughts import delete_thought_tool
from thebrain_mcp.utils.constants import ModificationType

BRAIN = "brain-00000000-0000-0000-0000-000000000000"
THOUGHT = "11111111-1111-1111-1111-111111111111"


def _mod(
    source_id: str,
    mod_type: int,
    *,
    source_type: int = 2,
    creation: str | None = None,
    old: str | None = None,
    new: str | None = None,
    extra_a: str | None = None,
    extra_b: str | None = None,
) -> Modification:
    return Modification.model_validate({
        "sourceId": source_id,
        "sourceType": source_type,
        "modType": mod_type,
        "oldValue": old,
        "newValue": new,
        "userId": "acct-1",
        "creationDateTime": creation,
        "extraAId": extra_a or "00000000-0000-0000-0000-000000000000",
        "extraBId": extra_b or "00000000-0000-0000-0000-000000000000",
    })


# --------------------------------------------------------------------------- #
# change_confirmed
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_change_confirmed_match():
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(
        return_value=[_mod(THOUGHT, ModificationType.DELETED, old="Gone")]
    )
    out = await change_confirmed(api, BRAIN, THOUGHT, [ModificationType.DELETED], since_marker())
    assert out["confirmed"] is True
    assert out["entry"]["modType"] == ModificationType.DELETED
    assert out["entry"]["oldValue"] == "Gone"


@pytest.mark.asyncio
async def test_change_confirmed_absent():
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(return_value=[
        _mod("other-id", ModificationType.DELETED),
        _mod(THOUGHT, ModificationType.CREATED),  # wrong mod_type
    ])
    out = await change_confirmed(
        api, BRAIN, THOUGHT, [ModificationType.DELETED], since_marker(), retries=1
    )
    assert out["confirmed"] is False
    assert out["entry"] is None


@pytest.mark.asyncio
async def test_change_confirmed_retry_then_found():
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(side_effect=[
        [],  # first poll: not visible yet
        [_mod(THOUGHT, ModificationType.SET_TYPE, new="Done Task")],  # second poll
    ])
    out = await change_confirmed(
        api, BRAIN, THOUGHT, [ModificationType.SET_TYPE], since_marker(),
        retries=2, delay=0.0,
    )
    assert out["confirmed"] is True
    assert api.get_brain_modifications.await_count == 2


@pytest.mark.asyncio
async def test_change_confirmed_link_endpoints():
    # A MOVED_LINK's sourceId is the link; the thought is an endpoint.
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(return_value=[
        _mod("link-9", ModificationType.MOVED_LINK, source_type=3,
             extra_a="new-parent", extra_b=THOUGHT),
    ])
    out = await change_confirmed(
        api, BRAIN, THOUGHT,
        [ModificationType.MOVED_LINK], since_marker(),
        retries=1, match_link_endpoints=True,
    )
    assert out["confirmed"] is True


@pytest.mark.asyncio
async def test_change_confirmed_ignores_older_same_type():
    # An entry that predates `since` must not count as confirmation.
    old_ts = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)).isoformat()
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(
        return_value=[_mod(THOUGHT, ModificationType.SET_TYPE, creation=old_ts)]
    )
    since = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    out = await change_confirmed(
        api, BRAIN, THOUGHT, [ModificationType.SET_TYPE], since, retries=1
    )
    assert out["confirmed"] is False


@pytest.mark.asyncio
async def test_change_confirmed_log_error_surfaced():
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(side_effect=TheBrainAPIError("HTTP 500"))
    out = await change_confirmed(
        api, BRAIN, THOUGHT, [ModificationType.DELETED], since_marker(), retries=1
    )
    assert out["confirmed"] is False
    assert "500" in out["error"]


# --------------------------------------------------------------------------- #
# get_modifications_tool filters
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_modifications_filters():
    mods = [
        _mod(THOUGHT, ModificationType.CREATED, source_type=2),
        _mod(THOUGHT, ModificationType.DELETED, source_type=2),
        _mod("link-1", ModificationType.MOVED_LINK, source_type=3),
        _mod("other", ModificationType.CREATED, source_type=2),
    ]
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(return_value=mods)

    # by source_id
    out = await get_modifications_tool(api, BRAIN, source_id=THOUGHT)
    assert out["count"] == 2
    assert {m["modType"] for m in out["modifications"]} == {101, 102}

    # by source_type (links only)
    out = await get_modifications_tool(api, BRAIN, source_type=3)
    assert out["count"] == 1 and out["modifications"][0]["sourceId"] == "link-1"

    # by mod_types
    out = await get_modifications_tool(api, BRAIN, mod_types=[ModificationType.CREATED])
    assert out["count"] == 2
    assert all(m["modType"] == 101 for m in out["modifications"])


@pytest.mark.asyncio
async def test_get_modifications_error():
    api = AsyncMock()
    api.get_brain_modifications = AsyncMock(side_effect=TheBrainAPIError("boom"))
    out = await get_modifications_tool(api, BRAIN)
    assert out["success"] is False and "boom" in out["error"]


# --------------------------------------------------------------------------- #
# confirm=True wiring on the mutating tools
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_thought_confirm_true_attaches_confirmation():
    api = AsyncMock()
    api.delete_thought = AsyncMock(return_value={"success": True})
    api.get_brain_modifications = AsyncMock(
        return_value=[_mod(THOUGHT, ModificationType.DELETED, old="Gone")]
    )
    out = await delete_thought_tool(api, BRAIN, THOUGHT, confirm=True)
    assert out["success"] is True
    assert out["confirmation"]["confirmed"] is True
    api.get_brain_modifications.assert_awaited()


@pytest.mark.asyncio
async def test_delete_thought_confirm_false_skips_log():
    api = AsyncMock()
    api.delete_thought = AsyncMock(return_value={"success": True})
    api.get_brain_modifications = AsyncMock(return_value=[])
    out = await delete_thought_tool(api, BRAIN, THOUGHT, confirm=False)
    assert "confirmation" not in out
    api.get_brain_modifications.assert_not_awaited()


@pytest.mark.asyncio
async def test_morph_retype_confirm_true():
    from thebrain_mcp.api.models import Thought, ThoughtGraph

    graph = ThoughtGraph.model_validate({
        "activeThought": {"id": THOUGHT, "brainId": BRAIN, "name": "N", "kind": 1,
                          "acType": 0, "typeId": None},
        "parents": [], "children": [], "links": [],
    })
    api = AsyncMock()
    api.get_thought_graph = AsyncMock(return_value=graph)
    api.update_thought = AsyncMock(return_value={})
    api.get_thought = AsyncMock(return_value=Thought.model_validate({
        "id": THOUGHT, "brainId": BRAIN, "name": "N", "kind": 1, "acType": 0,
        "typeId": "type-done",
    }))
    api.get_brain_modifications = AsyncMock(
        return_value=[_mod(THOUGHT, ModificationType.SET_TYPE, new="Done Task")]
    )
    out = await morpher_tool(api, BRAIN, THOUGHT, new_type_id="type-done", confirm=True)
    assert out["success"] is True
    assert out["confirmation"]["retype"]["confirmed"] is True
