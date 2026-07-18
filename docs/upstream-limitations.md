# Upstream (TheBrain API) limitations & our mitigations

TheBrain's cloud REST API (`api.bra.in`) has two behaviours that shape how this server
must read and write. They are **vendor-side** — not bugs in this MCP — and are tracked on
TheBrain's own tracker. This note records what they are, how we verified them, and the
stance our tools take so we don't re-litigate them.

## 1. The graph endpoint is a cached projection, stale for recent writes

`GET /thoughts/{brainId}/{thoughtId}/graph` is fronted by an Azure App Service response
cache. It reflects **creates** but lags **updates and deletes by hours-to-days** — it will
return renamed/retyped thoughts with their old values, and even serve thoughts that have
already been deleted.

- Upstream: [TheBrainTech/thebrain-api-quickstart-python#2](https://github.com/TheBrainTech/thebrain-api-quickstart-python/issues/2)
- Verified live 2026-07-18: after `PATCH name`/`typeId` and `DELETE`, `GET /thoughts/{id}`
  (command store) returned the correct new state / 404, while the graph endpoint still
  returned the deleted thought under its pre-rename name — on a parent-graph URL not
  previously requested that session.

### Authoritative vs cached — the read-after-write rule

| Purpose | Use | Why |
|---|---|---|
| Verify a mutation you just made | `get_thought` (by ID), the write tool's own response, or `get_modifications` | Command store / change-log — fresh, authoritative |
| Confirm a delete or a type/link change | `get_modifications` (change-log) | The only place these land visibly; the graph hides them |
| Fast traversal / find older IDs / established structure | `get_thought_graph(_paginated)` | Convenient, but cached — **never** trust for recent writes |

**Rule:** never confirm a write by reading `get_thought_graph`. Confirm by ID with
`get_thought`, or via the change-log `get_modifications`. (`morph_thought`'s retype
read-back already does this.)

### The change-log — a third, uncached endpoint

`GET /brains/{brainId}/modifications` is an append-only, **uncached** audit feed that records
every operation (`CREATED` 101, `DELETED` 102, `CHANGED_NAME` 103, `SET_TYPE` 203,
`MOVED_LINK` 402, …) with old→new values and timestamps. It is the closest thing the API has
to the desktop "sync" and reflects writes promptly, so we use it two ways:

- **Write-confirmation** — the `change_confirmed()` helper (`tools/stats.py`) scans it for the
  op just made; `delete_thought`, `morph_thought`, and `update_thought` accept `confirm=True`
  to attach a `confirmation` block. It's *stronger* than `get_thought`-by-ID for **deletes**
  (logged with the old name vs. a bare 404) and **type/link** changes the cached graph hides.
- **Activity / peer-work discovery** — `get_modifications` (with `source_id` / `source_type` /
  `mod_types` filters) answers "what changed since T," so an agent can pick up peer work.

**Attribution caveat:** every entry carries one **account-level `userId`** (the TheBrain API-key
owner). It distinguishes human-desktop vs API activity, but **not one DPYC agent from another** —
all agents share the operator's key. Peer discovery is therefore by **time + content**, not by
author. True per-agent attribution would require *us* to stamp the acting agent's npub into a
label / note / link-name convention on every write (deferred — see below).

## 2. The search / name index is incomplete on large brains

`GET /search/{brainId}` and the `nameExact` parameter return empty/404 for the majority of
thoughts in a large brain, even though those thoughts are reachable by ID and by graph
traversal.

- Upstream: [TheBrainTech/thebrain-api-quickstart-python#1](https://github.com/TheBrainTech/thebrain-api-quickstart-python/issues/1)
- Affects `get_thought_by_name`, `search_thoughts`, wikilink name-resolution, and BQL
  name-based matching (all inherit the index).

**Rule:** a name hit is real, but a **miss is not proof of absence**. Never create a
duplicate node because a name lookup came back empty — verify by ID or by traversing from a
known neighbour first. (This false-negative is what caused a duplicate-stub creation in
issue #188.)

## 3. Desktop-synced links cannot be deleted via the API (a hard write limit)

Links that originated in the TheBrain desktop app are refused by `DELETE /links/...`.
Because a thought's parent and **type** are expressed as links, this makes programmatic
**reparent** and **relink-retype** of desktop-origin thoughts impossible — the old link
cannot be removed, so the move cannot persist.

- `morph_thought` handles this honestly (issue #186 / PR #189): it detects the undeletable
  link, rolls back atomically, and returns `success: false` naming the link — rather than
  reporting a false success.
- Note the interaction with §1: a PATCH to the scalar `typeId` *does* land in the command
  store, but the visible/graph type is governed by the type-**link**, so a desktop-origin
  thought's type will not change via PATCH regardless.

## Reliable-change tactic (for agents mutating the graph)

Prefer **create-new + link-in-place + retire-old**, expressing the desired parent/type as
**creation-time links** (they cannot be PATCHed in afterward). Verify each step by ID with
`get_thought` or via the `get_modifications` change-log, not the graph. For desktop-origin
thoughts, retirement via delete may itself be refused — treat those as effectively immutable
and build alongside them.

**Do not create throwaway test nodes in a *synced* brain.** The stale graph cache (§1) can be
re-materialized by a desktop sync: on 2026-07-18 a thought deleted via the API (`GET` → 404)
came back as a *new persistent node* grafted onto an unrelated real thought after a routine
desktop sync. Only a desktop-side delete removed it. Use a scratch/unsynced brain for
lifecycle probing. Reported upstream on quickstart#2.

## Deferred: per-agent provenance

The change-log's `userId` is account-level, so it cannot attribute a change to a specific DPYC
agent (all share the operator's TheBrain key). If per-agent peer attribution becomes necessary,
have each write stamp the acting agent's npub into a label / note / link-name convention that
`get_modifications` consumers can read back. Not built yet — flagged so we don't assume the
vendor log provides it.

## Related closed issues

- #186 — reparent honest-abort (mitigated, PR #189)
- #187 — retype persistence (mitigated; write is real, graph lag is §1)
- #188 — name lookup false-negative (mitigated; §2)
