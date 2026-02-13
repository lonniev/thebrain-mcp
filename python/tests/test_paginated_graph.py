"""Tests for paginated graph traversal."""

from datetime import datetime, timezone

import pytest

from thebrain_mcp.tools.thoughts import (
    _collect_related_thoughts,
    _count_relations,
    _parse_cursor,
    paginate_graph,
)


# ---------------------------------------------------------------------------
# Helpers to build mock graph objects
# ---------------------------------------------------------------------------


class MockThought:
    """Minimal mock matching the attributes used by _collect_related_thoughts."""

    def __init__(self, id: str, name: str, mod_dt: datetime | None = None):
        self.id = id
        self.name = name
        self.label = None
        self.kind = 1
        self.modification_date_time = mod_dt
        self.foreground_color = None
        self.background_color = None


class MockGraph:
    """Minimal mock of ThoughtGraph."""

    def __init__(
        self,
        active_id: str = "root",
        active_name: str = "Root",
        children: list | None = None,
        parents: list | None = None,
        jumps: list | None = None,
        siblings: list | None = None,
    ):
        self.active_thought = MockThought(active_id, active_name)
        self.children = children or []
        self.parents = parents or []
        self.jumps = jumps or []
        self.siblings = siblings or []


def _dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_items(count: int = 12) -> list[dict]:
    """Create a deterministic set of items across relation types."""
    graph = MockGraph(
        children=[
            MockThought("c1", "Child 1", _dt(2026, 2, 13, 10)),
            MockThought("c2", "Child 2", _dt(2026, 2, 13, 8)),
            MockThought("c3", "Child 3", _dt(2026, 2, 12)),
            MockThought("c4", "Child 4", _dt(2026, 2, 11)),
            MockThought("c5", "Child 5", _dt(2026, 2, 10)),
        ],
        parents=[
            MockThought("p1", "Parent 1", _dt(2026, 2, 13, 12)),
            MockThought("p2", "Parent 2", _dt(2026, 2, 1)),
        ],
        jumps=[
            MockThought("j1", "Jump 1", _dt(2026, 2, 13, 9)),
            MockThought("j2", "Jump 2", _dt(2026, 2, 5)),
        ],
        siblings=[
            MockThought("s1", "Sibling 1", _dt(2026, 2, 13, 11)),
            MockThought("s2", "Sibling 2", _dt(2026, 2, 7)),
            MockThought("s3", "Sibling 3", _dt(2026, 2, 3)),
        ],
    )
    return _collect_related_thoughts(graph, relation_filter=None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCollectRelatedThoughts:
    def test_collects_all_relations(self) -> None:
        items = _make_items()
        assert len(items) == 12
        relations = {i["relation"] for i in items}
        assert relations == {"child", "parent", "jump", "sibling"}

    def test_empty_graph(self) -> None:
        graph = MockGraph()
        items = _collect_related_thoughts(graph, relation_filter=None)
        assert items == []

    def test_preserves_modification_datetime(self) -> None:
        graph = MockGraph(children=[MockThought("c1", "C", _dt(2026, 1, 1))])
        items = _collect_related_thoughts(graph, relation_filter=None)
        assert items[0]["modificationDateTime"] == "2026-01-01T00:00:00+00:00"

    def test_none_modification_datetime(self) -> None:
        graph = MockGraph(children=[MockThought("c1", "C", None)])
        items = _collect_related_thoughts(graph, relation_filter=None)
        assert items[0]["modificationDateTime"] is None


class TestCountRelations:
    def test_counts(self) -> None:
        items = _make_items()
        counts = _count_relations(items)
        assert counts == {"children": 5, "parents": 2, "jumps": 2, "siblings": 3}

    def test_empty(self) -> None:
        counts = _count_relations([])
        assert counts == {"children": 0, "parents": 0, "jumps": 0, "siblings": 0}


class TestParseCursor:
    def test_full_cursor(self) -> None:
        dt, tid = _parse_cursor("2026-02-13T10:00:00+00:00|c1")
        assert dt == _dt(2026, 2, 13, 10)
        assert tid == "c1"

    def test_cursor_without_id(self) -> None:
        dt, tid = _parse_cursor("2026-02-13T10:00:00+00:00")
        assert dt == _dt(2026, 2, 13, 10)
        assert tid == ""


class TestPaginateGraph:
    def test_first_page_older(self) -> None:
        items = _make_items()
        result = paginate_graph(items, page_size=3, cursor=None, direction="older", relation_filter=None)
        assert result["has_more"] is True
        assert len(result["page"]) == 3
        assert result["total_count"] == 12
        assert result["direction"] == "older"
        # Newest first: p1 (12h), s1 (11h), c1 (10h)
        assert result["page"][0]["id"] == "p1"
        assert result["page"][1]["id"] == "s1"
        assert result["page"][2]["id"] == "c1"
        assert result["next_cursor"] is not None

    def test_second_page_using_cursor(self) -> None:
        items = _make_items()
        first = paginate_graph(items, page_size=3, cursor=None, direction="older", relation_filter=None)
        # Refetch items (simulating a new API call)
        items2 = _make_items()
        second = paginate_graph(items2, page_size=3, cursor=first["next_cursor"], direction="older", relation_filter=None)
        assert len(second["page"]) == 3
        # After c1 (Feb 13 10h): j1 (Feb 13 9h), c2 (Feb 13 8h), c3 (Feb 12)
        assert second["page"][0]["id"] == "j1"
        assert second["page"][1]["id"] == "c2"
        assert second["page"][2]["id"] == "c3"

    def test_last_page(self) -> None:
        items = _make_items()
        # Page through all 12 items in pages of 5
        first = paginate_graph(items, page_size=5, cursor=None, direction="older", relation_filter=None)
        items2 = _make_items()
        second = paginate_graph(items2, page_size=5, cursor=first["next_cursor"], direction="older", relation_filter=None)
        items3 = _make_items()
        third = paginate_graph(items3, page_size=5, cursor=second["next_cursor"], direction="older", relation_filter=None)
        assert third["has_more"] is False
        assert len(third["page"]) == 2  # 12 - 5 - 5 = 2
        assert third["next_cursor"] is None

    def test_full_traversal_no_duplicates_no_skips(self) -> None:
        items = _make_items()
        all_ids: list[str] = []
        cursor = None
        for _ in range(20):  # safety limit
            batch = _make_items()
            result = paginate_graph(batch, page_size=4, cursor=cursor, direction="older", relation_filter=None)
            all_ids.extend(item["id"] for item in result["page"])
            if not result["has_more"]:
                break
            cursor = result["next_cursor"]
        assert len(all_ids) == 12
        assert len(set(all_ids)) == 12  # no duplicates

    def test_page_size_one(self) -> None:
        items = _make_items()
        all_ids: list[str] = []
        cursor = None
        for _ in range(20):
            batch = _make_items()
            result = paginate_graph(batch, page_size=1, cursor=cursor, direction="older", relation_filter=None)
            all_ids.extend(item["id"] for item in result["page"])
            if not result["has_more"]:
                break
            cursor = result["next_cursor"]
        assert len(all_ids) == 12
        assert len(set(all_ids)) == 12

    def test_empty_result(self) -> None:
        result = paginate_graph([], page_size=10, cursor=None, direction="older", relation_filter=None)
        assert result["page"] == []
        assert result["total_count"] == 0
        assert result["has_more"] is False
        assert result["next_cursor"] is None

    def test_newer_direction(self) -> None:
        items = _make_items()
        result = paginate_graph(items, page_size=3, cursor=None, direction="newer", relation_filter=None)
        # Oldest first: p2 (Feb 1), s3 (Feb 3), j2 (Feb 5)
        assert result["page"][0]["id"] == "p2"
        assert result["page"][1]["id"] == "s3"
        assert result["page"][2]["id"] == "j2"

    def test_direction_reversal(self) -> None:
        """Traverse older, then switch to newer from same cursor."""
        items = _make_items()
        older = paginate_graph(items, page_size=6, cursor=None, direction="older", relation_filter=None)
        cursor = older["next_cursor"]
        # The cursor points to the last item of the older page, which gets
        # excluded from both the next "older" page and a "newer" reversal.
        # So "newer" from cursor returns items strictly newer than the cursor.
        last_older_id = older["page"][-1]["id"]

        items2 = _make_items()
        newer = paginate_graph(items2, page_size=20, cursor=cursor, direction="newer", relation_filter=None)
        newer_ids = {i["id"] for i in newer["page"]}
        older_ids = {i["id"] for i in older["page"]}
        # Newer should return all older-page items except the cursor item itself
        assert newer_ids == older_ids - {last_older_id}

    def test_relation_filter_child(self) -> None:
        items = _make_items()
        result = paginate_graph(items, page_size=10, cursor=None, direction="older", relation_filter="child")
        assert result["total_count"] == 5
        assert all(i["relation"] == "child" for i in result["page"])
        # relation_counts should still be global
        assert result["relation_counts"]["children"] == 5
        assert result["relation_counts"]["parents"] == 2

    def test_relation_filter_jump(self) -> None:
        items = _make_items()
        result = paginate_graph(items, page_size=10, cursor=None, direction="older", relation_filter="jump")
        assert result["total_count"] == 2
        assert all(i["relation"] == "jump" for i in result["page"])

    def test_relation_filter_accepts_plural(self) -> None:
        items = _make_items()
        result = paginate_graph(items, page_size=10, cursor=None, direction="older", relation_filter="siblings")
        assert result["total_count"] == 3

    def test_relation_filter_with_pagination(self) -> None:
        items = _make_items()
        result = paginate_graph(items, page_size=2, cursor=None, direction="older", relation_filter="child")
        assert len(result["page"]) == 2
        assert result["has_more"] is True
        # Second page
        items2 = _make_items()
        result2 = paginate_graph(items2, page_size=2, cursor=result["next_cursor"], direction="older", relation_filter="child")
        assert len(result2["page"]) == 2
        assert result2["has_more"] is True
        # Third page (last child)
        items3 = _make_items()
        result3 = paginate_graph(items3, page_size=2, cursor=result2["next_cursor"], direction="older", relation_filter="child")
        assert len(result3["page"]) == 1
        assert result3["has_more"] is False

    def test_no_sort_key_in_output(self) -> None:
        items = _make_items()
        result = paginate_graph(items, page_size=3, cursor=None, direction="older", relation_filter=None)
        for item in result["page"]:
            assert "_sort_dt" not in item

    def test_none_modification_dates_sort_last_in_older(self) -> None:
        """Thoughts without dates should appear at the end when sorting newest-first."""
        graph = MockGraph(
            children=[
                MockThought("c1", "Has date", _dt(2026, 2, 13)),
                MockThought("c2", "No date", None),
            ]
        )
        items = _collect_related_thoughts(graph, relation_filter=None)
        result = paginate_graph(items, page_size=10, cursor=None, direction="older", relation_filter=None)
        assert result["page"][0]["id"] == "c1"
        assert result["page"][1]["id"] == "c2"
