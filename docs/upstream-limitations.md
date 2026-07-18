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
| Verify a mutation you just made | `get_thought` (by ID), or the write tool's own response | Reads the command store — fresh, authoritative |
| Fast traversal / find older IDs / established structure | `get_thought_graph(_paginated)` | Convenient, but cached — **never** trust for recent writes |

**Rule:** never confirm a write by reading `get_thought_graph`. Confirm by ID with
`get_thought`. (`morph_thought`'s retype read-back already does this.)

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
`get_thought`, not the graph. For desktop-origin thoughts, retirement via delete may itself
be refused — treat those as effectively immutable and build alongside them.

## Related closed issues

- #186 — reparent honest-abort (mitigated, PR #189)
- #187 — retype persistence (mitigated; write is real, graph lag is §1)
- #188 — name lookup false-negative (mitigated; §2)
