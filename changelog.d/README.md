# Unreleased changes live here, one file each

`CHANGELOG.md` was the single most conflict-prone file in the fleet, and not
because anybody was careless. Every pull request appended to the same
`### Added` / `### Changed` / `### Fixed` anchors of the same `## [Unreleased]`
section, so **any two concurrent PRs collided there even when their code did
not touch a single file in common**. Six of them did in `beesknees-mcp` in one
day, which is what finally cost enough to fix.

That is a property of the format, not of the changes. If A and B are
independent, it must not matter whether they land A-then-B or B-then-A — and a
changelog that forces a merge either way is the thing that is wrong.

## The convention

One file per change, named `<kind>-<slug>.md`:

    changelog.d/fixed-the-chooser-is-not-a-board.md
    changelog.d/added-a-first-timer-is-shown-the-way.md

`<kind>` is `added`, `changed`, `fixed`, `removed`, `security` or `deprecated`
— the Keep a Changelog headings. `<slug>` is whatever names the change; the
branch name is a good default.

The file holds the bullets, and nothing else. No heading, no blank framing:

    - The Play chooser gets the meadow and the wandering bees. `/play` was
      excluded from the app-wide scenery to keep loose bees away from a board —
      but the route is a CHOICE before it is a board.

Two PRs never touch the same file, so git never has an opinion about them.

## What happens at release

`scripts/changelog.py fold X.Y.Z` gathers every fragment, groups it under the
right heading in Keep a Changelog order, writes one `## [X.Y.Z] — <date>`
section at the top of `CHANGELOG.md`, and deletes the fragments. `/release`
runs it; nobody has to remember.

Fragments are folded in filename order, which is stable and says nothing about
when they were written — because the order two independent changes landed in is
not information anybody needs.

## Where this comes from

This convention is shared, not local. Its canonical copy lives in
`dpyc-community/scripts/changelog-fragments/`, and
`scripts/sync-changelog-fragments.sh` fans it out. Improve it THERE — a fix
made in one repo helps one repo.
