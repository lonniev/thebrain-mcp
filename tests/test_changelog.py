"""The changelog must not be the reason two independent changes conflict.

`CHANGELOG.md` was the single most conflict-prone file in the fleet, and not
through carelessness: every pull request appended to the same
`### Added` / `### Fixed` anchors of the same `## [Unreleased]` section, so any
two concurrent PRs collided there even when their code touched nothing in
common. Six did in `beesknees-mcp` in one day.

If A and B are independent, it must not matter whether they land A-then-B or
B-then-A. These tests hold that as a property rather than as an intention.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("changelog", ROOT / "scripts" / "changelog.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cl = _module()


def _write(d: pathlib.Path, name: str, body: str) -> None:
    (d / name).write_text(body)


def test_the_order_two_changes_land_in_does_not_reach_the_output(tmp_path) -> None:
    """The property the whole change exists for.

    Two independent entries, folded in both possible orders, must produce the
    same section — otherwise the changelog still carries a fact about merge
    order that nobody needs and everybody has to resolve.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    for d in (first, second):
        d.mkdir()
    _write(first, "fixed-alpha.md", "- Alpha was broken and is not.\n")
    _write(first, "fixed-beta.md", "- Beta was broken and is not.\n")
    # The same two, created in the opposite order.
    _write(second, "fixed-beta.md", "- Beta was broken and is not.\n")
    _write(second, "fixed-alpha.md", "- Alpha was broken and is not.\n")

    a = cl.section("1.0.0", cl.read_fragments(first), "2026-01-01")
    b = cl.section("1.0.0", cl.read_fragments(second), "2026-01-01")
    assert a == b


def test_kinds_are_grouped_in_keep_a_changelog_order(tmp_path) -> None:
    _write(tmp_path, "fixed-one.md", "- A fix.\n")
    _write(tmp_path, "added-two.md", "- An addition.\n")
    _write(tmp_path, "notes-three.md", "- Some reasoning.\n")

    out = cl.section("2.1.0", cl.read_fragments(tmp_path), "2026-01-01")
    assert out.startswith("## [2.1.0] — 2026-01-01")
    order = [m.group(1) for m in re.finditer(r"^### (\w+)", out, re.MULTILINE)]
    assert order == ["Added", "Fixed", "Notes"], order
    # Nothing empty is left standing.
    assert "### Changed" not in out


def test_a_misnamed_fragment_is_refused_rather_than_dropped(tmp_path) -> None:
    """A changelog that quietly loses an entry is worse than one that refuses
    to build — the entry is somebody's account of what they did to the money."""
    _write(tmp_path, "fxied-typo.md", "- Something real.\n")
    with pytest.raises(SystemExit, match="unknown kind"):
        cl.read_fragments(tmp_path)


def test_the_new_section_goes_above_the_ones_already_there(tmp_path) -> None:
    existing = "# Changelog\n\nPreamble.\n\n## [0.9.0] — 2025-01-01\n\n### Fixed\n\n- Older.\n"
    out = cl.fold(existing, "## [1.0.0] — 2026-01-01\n\n### Added\n\n- Newer.\n")
    assert out.index("## [1.0.0]") < out.index("## [0.9.0]")
    assert "Preamble." in out and "- Older." in out


def test_a_release_cannot_ship_with_its_notes_still_unfolded() -> None:
    """The guard that survives `.claude/` not being tracked.

    `/release` is a local slash command living under `.claude/`, which no repo
    in this fleet tracks — so an instruction to fold the fragments would travel
    with nobody. This runs in CI, where it does travel: if the changelog claims
    the version in `pyproject.toml`, the fragments for it must already be in
    it.
    """
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip(
            "no pyproject.toml — this repo versions itself by git tag, so there is no "
            "file to compare the changelog against. The fold still runs at release; "
            "this particular guard cannot."
        )
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.MULTILINE)
    assert version, "pyproject.toml has no version"
    v = re.escape(version.group(1))

    published = re.search(rf"^## \[?{v}\]?([ ]|$)", (ROOT / "CHANGELOG.md").read_text(), re.MULTILINE)
    if not published:
        return  # this version has not been cut yet; fragments are expected

    left = [p.name for p in (ROOT / "changelog.d").glob("*.md") if p.name != "README.md"]
    assert not left, (
        f"CHANGELOG.md already has a section for {version.group(1)}, but "
        f"changelog.d still holds {left} — run scripts/changelog.py fold <version>"
    )
