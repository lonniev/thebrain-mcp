"""Wikilink resolution for note-write tools.

Rewrites ``[[Thought Name]]`` tokens into compact ``brain://`` in-plex links at
write time so agents never hand-author ``brain://`` URLs or paste raw GUIDs (the
hyphenated GUID the API speaks does *not* resolve in TheBrain — it leaves a dead
raw-URL link).

Supported syntax:
    [[Thought Name]]            -> link text is the thought name
    [[Thought Name|Display]]    -> link text is Display, target is Thought Name
    [[#<thoughtId>]]            -> pin an exact target by id (hyphenated or compact)
    [[<thoughtId>|Display]]     -> same, with explicit display text

Resolution leaves misses and ambiguous tokens literal and reports them in the
``unresolved`` list — a write is never failed because a token didn't resolve.
"""

import base64
import re
import uuid
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError

# [[target]] or [[target|display]]. Target may not contain [, ], or |;
# display may not contain [ or ].
WIKILINK = re.compile(r"\[\[([^\[\]|]+?)(?:\|([^\[\]]+?))?\]\]")

# Regions whose contents must never be rewritten: fenced code blocks and inline
# code spans. Fences are matched first; inline spans cover the rest.
_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def guid_to_compact(guid_str: str) -> str:
    """Hyphenated .NET GUID -> TheBrain compact base64url id (padding stripped)."""
    return base64.urlsafe_b64encode(uuid.UUID(guid_str).bytes_le).decode().rstrip("=")


def compact_to_guid(compact: str) -> str:
    """Inverse of :func:`guid_to_compact`: compact base64url id -> hyphenated GUID."""
    raw = base64.urlsafe_b64decode(compact + "=" * (-len(compact) % 4))
    return str(uuid.UUID(bytes_le=raw))


def is_compact_id(s: str) -> bool:
    """True if ``s`` is a 22-char compact id that decodes to a valid GUID."""
    try:
        compact_to_guid(s)
        return len(s) == 22
    except Exception:
        return False


def is_guid_or_compact(s: str) -> bool:
    """True if ``s`` is a hyphenated GUID or a compact id."""
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return is_compact_id(s)


def _link(label: str, compact_brain: str, thought_guid: str) -> str:
    """Build the bare two-segment in-plex link (no name slug, no ?name= query)."""
    return (
        f"[{label}](brain://api.thebrain.com/"
        f"{compact_brain}/{guid_to_compact(thought_guid)})"
    )


async def _resolve_one(
    api: TheBrainAPI,
    brain_id: str,
    compact_brain: str,
    token: str,
    target: str,
    display: str,
    unresolved: list[dict[str, Any]],
) -> str:
    """Resolve a single wikilink token to a link, or return it unchanged.

    Appends a structured entry to ``unresolved`` when the token cannot be
    resolved (missed, ambiguous, or an upstream lookup failure).
    """
    # --- Id path: explicit '#' prefix, or a bare GUID / compact id ---
    if target.startswith("#") or is_guid_or_compact(target):
        raw = target.lstrip("#").strip()
        if not is_guid_or_compact(raw):
            unresolved.append({"token": token, "reason": "id_not_found"})
            return token
        guid = compact_to_guid(raw) if is_compact_id(raw) else str(uuid.UUID(raw))
        try:
            thought = await api.get_thought(brain_id, guid)
        except (TheBrainAPIError, ValueError):
            unresolved.append({"token": token, "reason": "id_not_found"})
            return token
        if thought is None:
            unresolved.append({"token": token, "reason": "id_not_found"})
            return token
        label = display or thought.name
        return _link(label, compact_brain, thought.id)

    # --- Name path: exact, case-sensitive match against the active brain ---
    try:
        candidates = await api.get_thoughts_by_name(brain_id, target)
    except TheBrainAPIError:
        unresolved.append({"token": token, "reason": "lookup_failed"})
        return token

    # Enforce case-sensitive equality regardless of how the upstream nameExact
    # endpoint matches, so ambiguity/miss semantics follow the spec exactly.
    matches = [t for t in candidates if t.name == target]
    if len(matches) == 0:
        unresolved.append({"token": token, "reason": "not_found"})
        return token
    if len(matches) > 1:
        unresolved.append(
            {
                "token": token,
                "reason": "ambiguous",
                "candidates": [t.id for t in matches],
            }
        )
        return token

    ref = matches[0]
    label = display or target
    return _link(label, compact_brain, ref.id)


async def resolve_wikilinks(
    api: TheBrainAPI, brain_id: str, markdown: str
) -> tuple[str, list[dict[str, Any]]]:
    """Rewrite wikilink tokens in ``markdown`` into compact ``brain://`` links.

    Tokens inside fenced/inline code, and tokens already preceded by ``]`` (part
    of an existing markdown link), are left untouched. Already-resolved
    ``brain://`` / ``https://`` links contain no ``[[...]]`` and so are no-ops on
    re-run (idempotent).

    Args:
        api: TheBrain API client.
        brain_id: The active brain id (hyphenated GUID).
        markdown: The markdown to resolve.

    Returns:
        ``(resolved_markdown, unresolved)`` — ``unresolved`` is a list of
        ``{"token", "reason", ...}`` dicts for every token left literal.
    """
    compact_brain = guid_to_compact(brain_id)
    unresolved: list[dict[str, Any]] = []

    code_spans = [m.span() for m in _FENCE.finditer(markdown)]
    code_spans += [m.span() for m in _INLINE_CODE.finditer(markdown)]

    def in_code(pos: int) -> bool:
        return any(start <= pos < end for start, end in code_spans)

    # Eligible token occurrences (left to right).
    tokens = [
        m
        for m in WIKILINK.finditer(markdown)
        if not in_code(m.start())
        and not (m.start() > 0 and markdown[m.start() - 1] == "]")
    ]

    # Resolve each distinct token once.
    resolutions: dict[str, str] = {}
    for m in tokens:
        if m.group(0) in resolutions:
            continue
        resolutions[m.group(0)] = await _resolve_one(
            api,
            brain_id,
            compact_brain,
            m.group(0),
            m.group(1).strip(),
            (m.group(2) or "").strip(),
            unresolved,
        )

    # Rebuild, replacing only eligible occurrences.
    out: list[str] = []
    last = 0
    for m in tokens:
        out.append(markdown[last : m.start()])
        out.append(resolutions[m.group(0)])
        last = m.end()
    out.append(markdown[last:])
    return "".join(out), unresolved
