#!/usr/bin/env python3
"""Fold the unreleased fragments into CHANGELOG.md.

Canonical copy: `dpyc-community/scripts/changelog-fragments/changelog.py`,
fanned out by `scripts/sync-changelog-fragments.sh`. Fix it THERE.

`CHANGELOG.md` is what the release workflow reads — it publishes the body of
the `## [X.Y.Z]` section as the GitHub Release notes — so the fragments have to
become that section before the tag is pushed. This is the step that does it.

Run by `/release`. Safe to run twice: with no fragments it changes nothing and
says so.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRAGMENTS = ROOT / "changelog.d"
CHANGELOG = ROOT / "CHANGELOG.md"

#: Keep a Changelog's own order, plus `notes` — for the reasoning behind a
#: change, which this fleet writes down and which belongs last because it is
#: the part a reader consults rather than scans.
#:
#: A fragment whose kind is not one of these is a typo in a filename, and is
#: reported rather than silently dropped: a changelog that quietly loses an
#: entry is worse than one that refuses to build.
KINDS = ("added", "changed", "deprecated", "removed", "fixed", "security", "notes")


def read_fragments(directory: pathlib.Path) -> dict[str, list[str]]:
    """Every fragment, grouped by kind, in filename order.

    Filename order rather than mtime or git order, deliberately: the sequence
    two independent changes happened to land in is not information a reader
    needs, and sorting by it would make the output depend on merge order —
    which is the whole thing this was built to stop mattering.
    """
    out: dict[str, list[str]] = {k: [] for k in KINDS}
    unknown: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        kind = path.name.split("-", 1)[0].lower()
        if kind not in out:
            unknown.append(path.name)
            continue
        body = path.read_text().strip()
        if body:
            out[kind].append(body)
    if unknown:
        raise SystemExit(
            f"changelog.d: unknown kind in {', '.join(unknown)} — "
            f"a fragment must be named <kind>-<slug>.md, kind one of {', '.join(KINDS)}"
        )
    return out


def section(version: str, groups: dict[str, list[str]], today: str) -> str:
    """One `## [version]` section. Empty kinds are omitted, not left blank."""
    lines = [f"## [{version}] — {today}", ""]
    for kind in KINDS:
        entries = groups.get(kind) or []
        if not entries:
            continue
        lines.append(f"### {kind.capitalize()}")
        lines.append("")
        for entry in entries:
            lines.append(entry)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def fold(text: str, new_section: str) -> str:
    """Put the new section above the first existing one, or at the end.

    Anchored on the first `## ` heading rather than a line number, so a longer
    or shorter preamble cannot push the insertion point into the middle of a
    sentence.
    """
    m = re.search(r"^## ", text, re.MULTILINE)
    if not m:
        return text.rstrip() + "\n\n" + new_section
    return text[: m.start()] + new_section + "\n" + text[m.start() :]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: changelog.py fold <version>", file=sys.stderr)
        return 2
    version = argv[1]

    groups = read_fragments(FRAGMENTS)
    if not any(groups.values()):
        print("changelog.d is empty — nothing to fold.")
        return 0

    # Timezone-aware: a release cut near midnight should carry the date the
    # person cutting it would write down, not the runner's idea of one.
    today = dt.datetime.now(tz=dt.UTC).astimezone().date().isoformat()
    CHANGELOG.write_text(fold(CHANGELOG.read_text(), section(version, groups, today)))

    kept = 0
    for path in sorted(FRAGMENTS.glob("*.md")):
        if path.name == "README.md":
            kept += 1
            continue
        path.unlink()
    print(f"folded {sum(len(v) for v in groups.values())} fragment(s) into {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] if sys.argv[1:2] == ["fold"] else sys.argv))
