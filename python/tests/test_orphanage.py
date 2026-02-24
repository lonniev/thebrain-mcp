"""Tests for the orphanage tool (scan and rescue orphaned thoughts)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from thebrain_mcp.api.client import TheBrainAPIError
from thebrain_mcp.api.models import Brain, Link, Modification, Thought, ThoughtGraph
from thebrain_mcp.tools.orphanage import (
    MAX_BATCH_SIZE,
    MAX_CONCURRENCY,
    _build_census,
    _is_orphan,
    scan_orphans_tool,
)

BRAIN = "brain-00000000-0000-0000-0000-000000000000"
HOME_ID = "home-00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Mock helpers (adapted from test_morpher.py)
# ---------------------------------------------------------------------------


def _thought(
    id: str,
    name: str,
    kind: int = 1,
    type_id: str | None = None,
    creation_dt: str | None = None,
) -> Thought:
    data = {
        "id": id,
        "brainId": BRAIN,
        "name": name,
        "kind": kind,
        "acType": 0,
        "typeId": type_id,
    }
    if creation_dt:
        data["creationDateTime"] = creation_dt
    return Thought.model_validate(data)


def _link(id: str, a: str, b: str, relation: int = 1) -> Link:
    return Link.model_validate({
        "id": id,
        "brainId": BRAIN,
        "thoughtIdA": a,
        "thoughtIdB": b,
        "relation": relation,
    })


def _graph(
    active: Thought,
    parents: list[Thought] | None = None,
    children: list[Thought] | None = None,
    jumps: list[Thought] | None = None,
    siblings: list[Thought] | None = None,
    tags: list[Thought] | None = None,
    links: list[Link] | None = None,
) -> ThoughtGraph:
    def to_dict(t: Thought) -> dict:
        d = {
            "id": t.id,
            "brainId": t.brain_id,
            "name": t.name,
            "kind": t.kind,
            "acType": t.ac_type,
            "typeId": t.type_id,
        }
        if t.creation_date_time:
            d["creationDateTime"] = t.creation_date_time.isoformat()
        return d

    def link_dict(lk: Link) -> dict:
        return {
            "id": lk.id,
            "brainId": lk.brain_id,
            "thoughtIdA": lk.thought_id_a,
            "thoughtIdB": lk.thought_id_b,
            "relation": lk.relation,
        }

    data: dict = {
        "activeThought": to_dict(active),
        "parents": [to_dict(p) for p in (parents or [])],
        "children": [to_dict(c) for c in (children or [])],
        "links": [link_dict(lk) for lk in (links or [])],
    }
    if jumps is not None:
        data["jumps"] = [to_dict(j) for j in jumps]
    if siblings is not None:
        data["siblings"] = [to_dict(s) for s in siblings]
    if tags is not None:
        data["tags"] = [to_dict(t) for t in tags]
    return ThoughtGraph.model_validate(data)


def _mod(source_id: str, source_type: int, mod_type: int) -> Modification:
    return Modification.model_validate({
        "sourceId": source_id,
        "sourceType": source_type,
        "modType": mod_type,
    })


def _brain() -> Brain:
    return Brain.model_validate({
        "id": BRAIN,
        "name": "Test Brain",
        "homeThoughtId": HOME_ID,
    })


def _mock_api(
    graphs: dict[str, ThoughtGraph] | None = None,
    mods: list[Modification] | None = None,
) -> AsyncMock:
    api = AsyncMock()
    api.get_brain = AsyncMock(return_value=_brain())

    if mods is not None:
        api.get_brain_modifications = AsyncMock(return_value=mods)
    else:
        api.get_brain_modifications = AsyncMock(return_value=[])

    if graphs:
        async def get_graph(brain_id, thought_id, **kwargs):
            if thought_id in graphs:
                return graphs[thought_id]
            raise TheBrainAPIError("HTTP 404: Not Found")

        api.get_thought_graph = AsyncMock(side_effect=get_graph)
    else:
        api.get_thought_graph = AsyncMock(
            side_effect=TheBrainAPIError("HTTP 404: Not Found")
        )

    api.get_thought_by_name = AsyncMock(return_value=None)
    api.create_thought = AsyncMock(return_value={"id": "orphanage-id"})
    api.create_link = AsyncMock(return_value={"id": "new-link-id"})
    api.update_thought = AsyncMock(return_value={})
    api.create_or_update_note = AsyncMock(return_value={})
    return api


# ---------------------------------------------------------------------------
# Census tests
# ---------------------------------------------------------------------------


class TestCensus:
    @pytest.mark.asyncio
    async def test_census_collects_created_thoughts(self):
        mods = [
            _mod("t1", 2, 101),  # THOUGHT CREATED
            _mod("t2", 2, 101),
            _mod("link-1", 3, 101),  # LINK CREATED — should be ignored
        ]
        api = _mock_api(mods=mods)
        result = await _build_census(api, BRAIN)
        assert result == {"t1", "t2"}

    @pytest.mark.asyncio
    async def test_census_subtracts_deleted_thoughts(self):
        mods = [
            _mod("t1", 2, 101),  # CREATED
            _mod("t2", 2, 101),  # CREATED
            _mod("t1", 2, 102),  # DELETED
        ]
        api = _mock_api(mods=mods)
        result = await _build_census(api, BRAIN)
        assert result == {"t2"}


# ---------------------------------------------------------------------------
# Orphan detection tests
# ---------------------------------------------------------------------------


class TestOrphanDetection:
    def test_orphan_detection_zero_connections(self):
        t = _thought("t1", "Lonely Thought")
        g = _graph(t)
        assert _is_orphan(g, HOME_ID) is True

    def test_non_orphan_with_parent(self):
        t = _thought("t1", "Child Thought")
        parent = _thought("p1", "Parent")
        g = _graph(t, parents=[parent])
        assert _is_orphan(g, HOME_ID) is False

    def test_non_orphan_with_child(self):
        t = _thought("t1", "Parent Thought")
        child = _thought("c1", "Child")
        g = _graph(t, children=[child])
        assert _is_orphan(g, HOME_ID) is False

    def test_non_orphan_with_jump(self):
        t = _thought("t1", "Jumped Thought")
        jump = _thought("j1", "Jump Target")
        g = _graph(t, jumps=[jump])
        assert _is_orphan(g, HOME_ID) is False

    def test_non_orphan_with_tag(self):
        t = _thought("t1", "Tagged Thought")
        tag = _thought("tag1", "My Tag", kind=4)
        g = _graph(t, tags=[tag])
        assert _is_orphan(g, HOME_ID) is False

    def test_non_orphan_with_sibling(self):
        t = _thought("t1", "Sibling Thought")
        sib = _thought("s1", "Sibling")
        g = _graph(t, siblings=[sib])
        assert _is_orphan(g, HOME_ID) is False

    def test_skip_type_thoughts(self):
        t = _thought("t1", "Person Type", kind=2)
        g = _graph(t)
        assert _is_orphan(g, HOME_ID) is False

    def test_skip_tag_thoughts(self):
        t = _thought("t1", "@todo", kind=4)
        g = _graph(t)
        assert _is_orphan(g, HOME_ID) is False

    def test_skip_event_thoughts(self):
        t = _thought("t1", "Birthday", kind=3)
        g = _graph(t)
        assert _is_orphan(g, HOME_ID) is False

    def test_skip_system_thoughts(self):
        t = _thought("t1", "System Thing", kind=5)
        g = _graph(t)
        assert _is_orphan(g, HOME_ID) is False

    def test_skip_home_thought(self):
        t = _thought(HOME_ID, "Home")
        g = _graph(t)
        assert _is_orphan(g, HOME_ID) is False


# ---------------------------------------------------------------------------
# Full scan_orphans_tool tests
# ---------------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_no_adoption(self):
        orphan = _thought("orphan-1", "Lost Note")
        graphs = {"orphan-1": _graph(orphan)}
        mods = [_mod("orphan-1", 2, 101)]

        api = _mock_api(graphs=graphs, mods=mods)
        result = await scan_orphans_tool(api, BRAIN, dry_run=True)

        assert result["success"] is True
        assert result["orphans_found"] == 1
        assert result["adopted"] == 0
        assert result["orphanage_id"] is None
        assert result["dry_run"] is True
        api.create_link.assert_not_called()
        api.create_thought.assert_not_called()


class TestAdoption:
    @pytest.mark.asyncio
    async def test_adopt_creates_orphanage_and_links(self):
        orphan = _thought("orphan-1", "Lost Note")
        graphs = {"orphan-1": _graph(orphan)}
        mods = [_mod("orphan-1", 2, 101)]

        api = _mock_api(graphs=graphs, mods=mods)
        result = await scan_orphans_tool(api, BRAIN, dry_run=False)

        assert result["success"] is True
        assert result["adopted"] == 1
        assert result["orphanage_id"] == "orphanage-id"
        assert result["dry_run"] is False

        # Should have created Orphanage thought
        api.create_thought.assert_called_once()
        create_args = api.create_thought.call_args
        assert create_args[0][1]["name"] == "Orphanage"
        assert create_args[0][1]["sourceThoughtId"] == HOME_ID

    @pytest.mark.asyncio
    async def test_adopt_tags_orphans_with_todo(self):
        orphan = _thought("orphan-1", "Lost Note")
        graphs = {"orphan-1": _graph(orphan)}
        mods = [_mod("orphan-1", 2, 101)]

        api = _mock_api(graphs=graphs, mods=mods)
        await scan_orphans_tool(api, BRAIN, dry_run=False)

        # Check that @todo tag link was created
        tag_calls = [
            c for c in api.create_link.call_args_list
            if c[0][1]["thoughtIdA"] == "065c5285-d785-5244-9b64-1d50d026282a"
        ]
        assert len(tag_calls) == 1
        assert tag_calls[0][0][1]["thoughtIdB"] == "orphan-1"

    @pytest.mark.asyncio
    async def test_adopt_labels_orphans(self):
        orphan = _thought("orphan-1", "Lost Note")
        graphs = {"orphan-1": _graph(orphan)}
        mods = [_mod("orphan-1", 2, 101)]

        api = _mock_api(graphs=graphs, mods=mods)
        await scan_orphans_tool(api, BRAIN, dry_run=False)

        api.update_thought.assert_called_once()
        update_args = api.update_thought.call_args
        assert update_args[0][1] == "orphan-1"
        label = update_args[0][2]["label"]
        assert label.startswith("Orphaned: ")

    @pytest.mark.asyncio
    async def test_adopt_adds_orphanage_note(self):
        orphan = _thought("orphan-1", "Lost Note")
        graphs = {"orphan-1": _graph(orphan)}
        mods = [_mod("orphan-1", 2, 101)]

        api = _mock_api(graphs=graphs, mods=mods)
        await scan_orphans_tool(api, BRAIN, dry_run=False)

        api.create_or_update_note.assert_called_once()
        note_args = api.create_or_update_note.call_args
        assert note_args[0][1] == "orphanage-id"
        assert "orphaned" in note_args[0][2].lower()

    @pytest.mark.asyncio
    async def test_adopt_reuses_existing_orphanage(self):
        orphan = _thought("orphan-1", "Lost Note")
        existing_orphanage = _thought("existing-orphanage-id", "Orphanage")
        graphs = {"orphan-1": _graph(orphan)}
        mods = [_mod("orphan-1", 2, 101)]

        api = _mock_api(graphs=graphs, mods=mods)
        api.get_thought_by_name = AsyncMock(return_value=existing_orphanage)

        result = await scan_orphans_tool(api, BRAIN, dry_run=False)

        assert result["orphanage_id"] == "existing-orphanage-id"
        api.create_thought.assert_not_called()
        api.create_or_update_note.assert_not_called()

    @pytest.mark.asyncio
    async def test_adopt_multiple_orphans(self):
        o1 = _thought("orphan-1", "Lost Note 1")
        o2 = _thought("orphan-2", "Lost Note 2")
        graphs = {
            "orphan-1": _graph(o1),
            "orphan-2": _graph(o2),
        }
        mods = [
            _mod("orphan-1", 2, 101),
            _mod("orphan-2", 2, 101),
        ]

        api = _mock_api(graphs=graphs, mods=mods)
        result = await scan_orphans_tool(api, BRAIN, dry_run=False)

        assert result["adopted"] == 2
        # 2 parent links + 2 tag links = 4 total
        assert api.create_link.call_count == 4
        assert api.update_thought.call_count == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_404_during_scan_skipped(self):
        """Thought deleted between census and scan should be silently skipped."""
        mods = [_mod("deleted-thought", 2, 101)]
        api = _mock_api(mods=mods)
        # get_thought_graph raises 404 (default behavior when no graphs dict)

        result = await scan_orphans_tool(api, BRAIN)

        assert result["success"] is True
        assert result["scanned"] == 0
        assert result["orphans_found"] == 0

    @pytest.mark.asyncio
    async def test_batch_size_capped(self):
        """batch_size > 100 should be clamped to 100."""
        mods = [_mod("t1", 2, 101)]
        t = _thought("t1", "Normal")
        parent = _thought("p1", "Parent")
        graphs = {"t1": _graph(t, parents=[parent])}
        api = _mock_api(graphs=graphs, mods=mods)

        # Pass batch_size > MAX_BATCH_SIZE
        result = await scan_orphans_tool(api, BRAIN, batch_size=500)

        assert result["success"] is True
        # The scan should still work (batch_size was clamped internally)
        assert result["scanned"] == 1

    @pytest.mark.asyncio
    async def test_empty_brain(self):
        """Zero modifications should yield empty result with no errors."""
        api = _mock_api(mods=[])
        result = await scan_orphans_tool(api, BRAIN)

        assert result["success"] is True
        assert result["census_size"] == 0
        assert result["orphans_found"] == 0
        assert result["orphans"] == []

    @pytest.mark.asyncio
    async def test_api_error_propagated(self):
        """TheBrainAPIError during brain fetch should return error dict."""
        api = _mock_api()
        api.get_brain = AsyncMock(side_effect=TheBrainAPIError("Connection refused"))

        result = await scan_orphans_tool(api, BRAIN)

        assert result["success"] is False
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_census_error_propagated(self):
        """TheBrainAPIError during census should return error dict."""
        api = _mock_api()
        api.get_brain_modifications = AsyncMock(
            side_effect=TheBrainAPIError("Timeout")
        )

        result = await scan_orphans_tool(api, BRAIN)

        assert result["success"] is False
        assert "Census failed" in result["error"]

    @pytest.mark.asyncio
    async def test_mixed_orphans_and_connected(self):
        """Only truly orphaned thoughts should be reported."""
        orphan = _thought("orphan-1", "Lonely")
        connected = _thought("connected-1", "Has Parent")
        parent = _thought("parent-1", "Parent")
        graphs = {
            "orphan-1": _graph(orphan),
            "connected-1": _graph(connected, parents=[parent]),
        }
        mods = [
            _mod("orphan-1", 2, 101),
            _mod("connected-1", 2, 101),
        ]

        api = _mock_api(graphs=graphs, mods=mods)
        result = await scan_orphans_tool(api, BRAIN)

        assert result["orphans_found"] == 1
        assert result["scanned"] == 2
        assert result["orphans"][0]["id"] == "orphan-1"

    @pytest.mark.asyncio
    async def test_home_thought_not_flagged_as_orphan(self):
        """Home thought should never be flagged even with zero connections."""
        home = _thought(HOME_ID, "Home")
        graphs = {HOME_ID: _graph(home)}
        mods = [_mod(HOME_ID, 2, 101)]

        api = _mock_api(graphs=graphs, mods=mods)
        result = await scan_orphans_tool(api, BRAIN)

        assert result["orphans_found"] == 0


# ---------------------------------------------------------------------------
# Concurrency tests
# ---------------------------------------------------------------------------


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_census_fetches_all_years_concurrently(self):
        """Census should call get_brain_modifications for every year 2000..current."""
        from datetime import date

        api = _mock_api(mods=[])
        await _build_census(api, BRAIN)

        expected_years = date.today().year - 2000 + 1
        assert api.get_brain_modifications.call_count == expected_years

    @pytest.mark.asyncio
    async def test_concurrent_scan_mixed_404s(self):
        """Thoughts that 404 during scan should be skipped; valid ones scanned."""
        orphan = _thought("orphan-1", "Lonely")
        connected = _thought("connected-1", "Has Parent")
        parent = _thought("parent-1", "Parent")
        graphs = {
            "orphan-1": _graph(orphan),
            "connected-1": _graph(connected, parents=[parent]),
            # "deleted-1" not in graphs → will 404
        }
        mods = [
            _mod("orphan-1", 2, 101),
            _mod("connected-1", 2, 101),
            _mod("deleted-1", 2, 101),
        ]

        api = _mock_api(graphs=graphs, mods=mods)
        result = await scan_orphans_tool(api, BRAIN)

        assert result["success"] is True
        assert result["census_size"] == 3
        assert result["scanned"] == 2  # deleted-1 skipped
        assert result["orphans_found"] == 1
        assert result["orphans"][0]["id"] == "orphan-1"

    @pytest.mark.asyncio
    async def test_large_batch_completes(self):
        """Batch larger than MAX_CONCURRENCY should still complete."""
        count = MAX_CONCURRENCY + 5
        graphs = {}
        mods = []
        for i in range(count):
            tid = f"thought-{i}"
            t = _thought(tid, f"Thought {i}")
            graphs[tid] = _graph(t)  # all orphans
            mods.append(_mod(tid, 2, 101))

        api = _mock_api(graphs=graphs, mods=mods)
        result = await scan_orphans_tool(api, BRAIN, batch_size=count)

        assert result["success"] is True
        assert result["scanned"] == count
        assert result["orphans_found"] == count

    @pytest.mark.asyncio
    async def test_all_thoughts_404_yields_zero_scanned(self):
        """If every thought 404s during scan, scanned should be 0."""
        mods = [
            _mod("gone-1", 2, 101),
            _mod("gone-2", 2, 101),
            _mod("gone-3", 2, 101),
        ]
        api = _mock_api(mods=mods)  # no graphs → all 404

        result = await scan_orphans_tool(api, BRAIN)

        assert result["success"] is True
        assert result["census_size"] == 3
        assert result["scanned"] == 0
        assert result["orphans_found"] == 0
