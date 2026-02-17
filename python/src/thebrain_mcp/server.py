"""TheBrain MCP server using FastMCP."""

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from thebrain_mcp.api.client import TheBrainAPI
from thebrain_mcp.btcpay_client import BTCPayClient
from thebrain_mcp.config import get_settings
from thebrain_mcp.ledger_cache import LedgerCache
from thebrain_mcp.tools import attachments, brains, credits, links, notes, stats, thoughts
from thebrain_mcp.utils.constants import TOOL_COSTS
from thebrain_mcp.vault import (
    CredentialNotFoundError,
    CredentialVault,
    CredentialValidationError,
    DecryptionError,
    VaultNotConfiguredError,
    decrypt_credentials,
    encrypt_credentials,
    get_session,
    set_session,
)

# Initialize FastMCP server (don't load settings yet - wait until runtime)
mcp = FastMCP(
    "thebrain-mcp",
    instructions=(
        "TheBrain MCP Server — Tool Selection Guide\n\n"
        "This server provides both a high-level query language (BrainQuery/BQL via brain_query) "
        "and low-level tools for direct API access. Use them together:\n\n"
        "1. brain_query (BQL) — primary tool for pattern-based CRUD. Handles searching by "
        "name/type, graph traversal, multi-hop chains, creating thoughts in context. "
        "Start here for most operations.\n\n"
        "2. If BQL returns empty or you need finer control:\n"
        "   - get_thought_by_name — fast exact-name lookup\n"
        "   - search_thoughts — full-text keyword search across names and content\n"
        "   - get_types → get_thought_graph — traverse from a known type\n\n"
        "3. get_thought_graph / get_thought_graph_paginated — use when you have a thought ID "
        "and need to explore its connections, or for operations BQL doesn't cover yet "
        "(attachments, link metadata, full thought details).\n\n"
        "4. create_or_update_note, append_to_note, list_attachments, add_file_attachment, "
        "add_url_attachment — note and attachment operations not covered by BQL.\n\n"
        "5. create_thought, create_link, update_thought, update_link, delete_thought, "
        "delete_link — direct CRUD when you need precise control or BQL doesn't support "
        "the operation yet.\n\n"
        "## Low-Balance Warning\n\n"
        "Any paid tool response may include a `low_balance_warning` key when the user's "
        "credit balance is running low. When you see this field, proactively inform the "
        "user (or relay to an agent-to-agent partner) that their balance is getting low "
        "and suggest they purchase a new credit bundle soon. Include the "
        "`purchase_command` hint from the warning so they can act immediately. Do not "
        "suppress or ignore this warning — it is the user's only advance notice before "
        "tool calls start being rejected for insufficient balance."
    ),
)

# Global API client and active brain state (initialized at runtime)
_operator_api_client: TheBrainAPI | None = None
active_brain_id: str | None = None
_settings_loaded = False


def _ensure_settings_loaded() -> None:
    """Ensure settings are loaded (called at runtime, not import time)."""
    global active_brain_id, _settings_loaded
    if not _settings_loaded:
        try:
            settings = get_settings()
            active_brain_id = settings.thebrain_default_brain_id
            _settings_loaded = True
        except Exception as e:
            print(f"Error: Failed to load settings: {e}", file=sys.stderr)
            print("Please ensure THEBRAIN_API_KEY is set in environment or .env file", file=sys.stderr)
            sys.exit(1)


def _get_current_user_id() -> str | None:
    """Extract FastMCP Cloud user ID from request headers.

    Returns None in STDIO mode (local dev) or when no auth headers present.
    """
    try:
        headers = get_http_headers(include_all=True)
        return headers.get("fastmcp-cloud-user")
    except Exception:
        return None


def _get_operator_api() -> TheBrainAPI:
    """Get or create the operator's API client (singleton)."""
    global _operator_api_client
    _ensure_settings_loaded()
    if _operator_api_client is None:
        settings = get_settings()
        _operator_api_client = TheBrainAPI(settings.thebrain_api_key, settings.thebrain_api_url)
    return _operator_api_client


def get_api() -> TheBrainAPI:
    """Get API client — per-user if session active, operator's for STDIO mode.

    Raises ValueError for FastMCP Cloud users without an active session.
    """
    _ensure_settings_loaded()

    user_id = _get_current_user_id()
    if user_id:
        # FastMCP Cloud: require per-user session
        session = get_session(user_id)
        if session:
            return session.api_client
        raise ValueError(
            "No active session. Call register_credentials (first time) "
            "or activate_session (returning user) to use your own TheBrain credentials."
        )

    # STDIO mode (local dev): use operator's client
    return _get_operator_api()


def get_brain_id(brain_id: str | None = None) -> str:
    """Get brain ID: explicit arg > per-user session > operator default (STDIO only)."""
    _ensure_settings_loaded()
    if brain_id:
        return brain_id

    # Try per-user session
    user_id = _get_current_user_id()
    if user_id:
        session = get_session(user_id)
        if session and session.active_brain_id:
            return session.active_brain_id

    # STDIO fallback
    if active_brain_id:
        return active_brain_id
    raise ValueError("Brain ID is required. Use set_active_brain first or provide brainId.")


# Authentication Diagnostics


@mcp.tool()
async def whoami() -> dict[str, Any]:
    """Return the authenticated user's identity and token claims.

    This is a diagnostic tool to inspect what OAuth claims are available
    from the FastMCP Cloud authentication layer.
    """
    import base64
    import json

    result: dict[str, Any] = {}

    # FastMCP Cloud custom headers (injected by proxy)
    headers = get_http_headers(include_all=True)
    result["fastmcp_cloud"] = {
        k: v for k, v in headers.items() if k.startswith("fastmcp-")
    } or None

    # Decode JWT from authorization header (without verification)
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        raw_jwt = auth_header[len("Bearer "):]
        try:
            parts = raw_jwt.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1]
                payload_b64 += "=" * (4 - len(payload_b64) % 4)
                result["jwt_claims"] = json.loads(base64.urlsafe_b64decode(payload_b64))
            else:
                result["jwt_claims"] = {"error": f"Malformed JWT: {len(parts)} parts"}
        except Exception as e:
            result["jwt_claims"] = {"error": f"JWT decode failed: {e}"}
    else:
        result["jwt_claims"] = None

    return result


# Brain Management Tools


@mcp.tool()
async def list_brains() -> dict[str, Any]:
    """List all available brains for the user."""
    return await brains.list_brains_tool(get_api())


@mcp.tool()
async def get_brain(brain_id: str) -> dict[str, Any]:
    """Get details about a specific brain.

    Args:
        brain_id: The ID of the brain
    """
    gate = await _debit_or_error("get_brain")
    if gate:
        return gate
    try:
        return await _with_warning(await brains.get_brain_tool(get_api(), brain_id))
    except Exception:
        await _rollback_debit("get_brain")
        raise


@mcp.tool()
async def set_active_brain(brain_id: str) -> dict[str, Any]:
    """Set the active brain for subsequent operations.

    Args:
        brain_id: The ID of the brain to set as active
    """
    gate = await _debit_or_error("set_active_brain")
    if gate:
        return gate
    global active_brain_id
    try:
        result = await brains.set_active_brain_tool(get_api(), brain_id)
    except Exception:
        await _rollback_debit("set_active_brain")
        raise
    if result.get("success"):
        user_id = _get_current_user_id()
        if user_id:
            session = get_session(user_id)
            if session:
                session.active_brain_id = brain_id
                return await _with_warning(result)
        active_brain_id = brain_id
    return await _with_warning(result)


@mcp.tool()
async def get_brain_stats(brain_id: str | None = None) -> dict[str, Any]:
    """Get statistics about a brain.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_brain_stats")
    if gate:
        return gate
    try:
        return await _with_warning(await brains.get_brain_stats_tool(get_api(), get_brain_id(brain_id)))
    except Exception:
        await _rollback_debit("get_brain_stats")
        raise


# Thought Operations


@mcp.tool()
async def create_thought(
    name: str,
    brain_id: str | None = None,
    kind: int = 1,
    label: str | None = None,
    foreground_color: str | None = None,
    background_color: str | None = None,
    type_id: str | None = None,
    source_thought_id: str | None = None,
    relation: int | None = None,
    ac_type: int = 0,
) -> dict[str, Any]:
    """Create a new thought with optional type, color, label, and parent link.

    Prefer brain_query CREATE syntax when creating in graph context (e.g., as
    child of a thought found by name). Use directly when you need properties BQL
    doesn't support yet (kind, access control) or when you already have the
    source thought ID.

    Args:
        name: The name of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        kind: Kind of thought (1=Normal, 2=Type, 3=Event, 4=Tag, 5=System)
        label: Optional label for the thought
        foreground_color: Foreground color in hex format (e.g., "#ff0000")
        background_color: Background color in hex format (e.g., "#0000ff")
        type_id: ID of the thought type to assign
        source_thought_id: ID of the source thought to link from
        relation: Relation type if linking (1=Child, 2=Parent, 3=Jump, 4=Sibling)
        ac_type: Access type (0=Public, 1=Private)
    """
    gate = await _debit_or_error("create_thought")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.create_thought_tool(
            get_api(),
            get_brain_id(brain_id),
            name,
            kind,
            label,
            foreground_color,
            background_color,
            type_id,
            source_thought_id,
            relation,
            ac_type,
        ))
    except Exception:
        await _rollback_debit("create_thought")
        raise


@mcp.tool()
async def get_thought(thought_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Get details about a specific thought.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_thought")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.get_thought_tool(get_api(), get_brain_id(brain_id), thought_id))
    except Exception:
        await _rollback_debit("get_thought")
        raise


@mcp.tool()
async def get_thought_by_name(
    name_exact: str, brain_id: str | None = None
) -> dict[str, Any]:
    """Exact name lookup — returns the first thought matching the name exactly (case-sensitive).

    Use when you know the precise thought name and need a quick ID lookup.
    Prefer brain_query with {name: "exact"} syntax when you also need type
    filtering or graph context.

    Depends on TheBrain's cloud search index — may return not-found for
    thoughts that exist but aren't indexed. Use get_thought_graph for
    reliable traversal.

    Args:
        name_exact: The exact name to match (case-sensitive)
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_thought_by_name")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.get_thought_by_name_tool(
            get_api(), get_brain_id(brain_id), name_exact
        ))
    except Exception:
        await _rollback_debit("get_thought_by_name")
        raise


@mcp.tool()
async def update_thought(
    thought_id: str,
    brain_id: str | None = None,
    name: str | None = None,
    label: str | None = None,
    foreground_color: str | None = None,
    background_color: str | None = None,
    kind: int | None = None,
    ac_type: int | None = None,
    type_id: str | None = None,
) -> dict[str, Any]:
    """Update a thought's properties: name, label, colors, kind, type assignment.

    Use when you have a thought ID and need to modify properties. Once BQL
    supports SET, prefer brain_query for match-then-modify workflows.

    Args:
        thought_id: The ID of the thought to update
        brain_id: The ID of the brain (uses active brain if not specified)
        name: New name for the thought
        label: New label for the thought
        foreground_color: New foreground color in hex format
        background_color: New background color in hex format
        kind: New kind
        ac_type: New access type
        type_id: New type ID to assign
    """
    gate = await _debit_or_error("update_thought")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.update_thought_tool(
            get_api(),
            get_brain_id(brain_id),
            thought_id,
            name,
            label,
            foreground_color,
            background_color,
            kind,
            ac_type,
            type_id,
        ))
    except Exception:
        await _rollback_debit("update_thought")
        raise


@mcp.tool()
async def delete_thought(thought_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Permanently delete a thought by ID. Cannot be undone.

    Once BQL supports DELETE, prefer brain_query for match-then-delete with
    safety guardrails (preview mode, batch limits). Use directly only with a
    specific ID and user confirmation.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("delete_thought")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.delete_thought_tool(get_api(), get_brain_id(brain_id), thought_id))
    except Exception:
        await _rollback_debit("delete_thought")
        raise


@mcp.tool()
async def search_thoughts(
    query_text: str,
    brain_id: str | None = None,
    max_results: int = 30,
    only_search_thought_names: bool = False,
) -> dict[str, Any]:
    """Full-text search across thought names and content. Returns matching thoughts with IDs.

    Use as a complement to brain_query for broad keyword searches that don't
    fit a graph pattern, or when you want to search note content (not just
    thought names). Tip: keep queries short (1-3 words) for best results.

    Depends on TheBrain's cloud index, which may not cover all thoughts. For
    reliable lookup, use get_thought_graph to traverse connections.

    Args:
        query_text: Search query text
        brain_id: The ID of the brain (uses active brain if not specified)
        max_results: Maximum number of results
        only_search_thought_names: Only search in thought names (not content)
    """
    gate = await _debit_or_error("search_thoughts")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.search_thoughts_tool(
            get_api(), get_brain_id(brain_id), query_text, max_results, only_search_thought_names
        ))
    except Exception:
        await _rollback_debit("search_thoughts")
        raise


@mcp.tool()
async def get_thought_graph(
    thought_id: str, brain_id: str | None = None, include_siblings: bool = False
) -> dict[str, Any]:
    """Get a thought's full connection graph: parents, children, jumps, siblings,
    links, tags, type info, and attachments. Always works given a valid thought
    ID — the most reliable traversal method.

    Use when you have a thought ID and need to explore its neighborhood, you
    need full thought metadata (colors, labels, kind), or you need attachment
    or link details.

    For thoughts with many connections (>50), consider
    get_thought_graph_paginated instead.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        include_siblings: Include sibling thoughts in the graph
    """
    gate = await _debit_or_error("get_thought_graph")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.get_thought_graph_tool(
            get_api(), get_brain_id(brain_id), thought_id, include_siblings
        ))
    except Exception:
        await _rollback_debit("get_thought_graph")
        raise


@mcp.tool()
async def get_thought_graph_paginated(
    thought_id: str,
    page_size: int = 10,
    cursor: str | None = None,
    direction: str = "older",
    relation_filter: str | None = None,
    brain_id: str | None = None,
) -> dict[str, Any]:
    """Cursor-based paginated traversal of a thought's connections. Returns a page
    of results sorted by modification date, with a cursor for fetching the next page.

    Use instead of get_thought_graph when a thought has many connections (types,
    hub nodes with 50+ children).

    Pagination uses a time-based cursor (modificationDateTime + thoughtId tiebreaker):
    - First call: omit cursor, set page_size (default 10)
    - Subsequent calls: pass the cursor from the previous response
    - Direction: "older" (newest first, default) or "newer" (oldest first)
    - Filter by relation: "child", "parent", "jump", "sibling", or omit for all

    The cursor is stateless — no server-side session. You can change page_size
    or direction between calls.

    Args:
        thought_id: The ID of the thought
        page_size: Number of results per page (default 10)
        cursor: Pagination cursor from a previous response (omit for first page)
        direction: "older" (newest first, default) or "newer" (oldest first)
        relation_filter: Filter by relation: "child", "parent", "jump", "sibling", or omit for all
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_thought_graph_paginated")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.get_thought_graph_paginated_tool(
            get_api(), get_brain_id(brain_id), thought_id,
            page_size, cursor, direction, relation_filter,
        ))
    except Exception:
        await _rollback_debit("get_thought_graph_paginated")
        raise


@mcp.tool()
async def get_types(brain_id: str | None = None) -> dict[str, Any]:
    """List all thought types defined in the brain (e.g., Person, Geographical, Organization).

    Use for discovering available types before writing typed BQL queries,
    resolving type names to IDs, or as step 1 of type-based traversal
    (get_types -> get_thought_graph on a type -> filter results).

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_types")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.get_types_tool(get_api(), get_brain_id(brain_id)))
    except Exception:
        await _rollback_debit("get_types")
        raise


@mcp.tool()
async def get_tags(brain_id: str | None = None) -> dict[str, Any]:
    """Get all tags in a brain.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_tags")
    if gate:
        return gate
    try:
        return await _with_warning(await thoughts.get_tags_tool(get_api(), get_brain_id(brain_id)))
    except Exception:
        await _rollback_debit("get_tags")
        raise


# Link Operations


@mcp.tool()
async def create_link(
    thought_id_a: str,
    thought_id_b: str,
    relation: int,
    brain_id: str | None = None,
    name: str | None = None,
    color: str | None = None,
    thickness: int | None = None,
    direction: int | None = None,
    type_id: str | None = None,
) -> dict[str, Any]:
    """Create a relationship between two thoughts by ID.

    Relation types: 1=Child, 2=Parent, 3=Jump, 4=Sibling.
    Supports optional label, color (hex), thickness (1-10), and direction flags.

    Prefer brain_query CREATE for links in graph context. Use directly when you
    need visual link properties (color, thickness, labels) that BQL doesn't
    support yet.

    Args:
        thought_id_a: ID of the first thought
        thought_id_b: ID of the second thought
        relation: Relation type (1=Child, 2=Parent, 3=Jump, 4=Sibling)
        brain_id: The ID of the brain (uses active brain if not specified)
        name: Label for the link
        color: Link color in hex format (e.g., "#6fbf6f")
        thickness: Link thickness (1-10)
        direction: Direction flags (0=Undirected, 1=Directed, etc.)
        type_id: ID of link type
    """
    gate = await _debit_or_error("create_link")
    if gate:
        return gate
    try:
        return await _with_warning(await links.create_link_tool(
            get_api(),
            get_brain_id(brain_id),
            thought_id_a,
            thought_id_b,
            relation,
            name,
            color,
            thickness,
            direction,
            type_id,
        ))
    except Exception:
        await _rollback_debit("create_link")
        raise


@mcp.tool()
async def update_link(
    link_id: str,
    brain_id: str | None = None,
    name: str | None = None,
    color: str | None = None,
    thickness: int | None = None,
    direction: int | None = None,
    relation: int | None = None,
) -> dict[str, Any]:
    """Update link properties including visual formatting.

    Args:
        link_id: The ID of the link to update
        brain_id: The ID of the brain (uses active brain if not specified)
        name: New label for the link
        color: New link color in hex format
        thickness: New link thickness (1-10)
        direction: New direction flags
        relation: New relation type
    """
    gate = await _debit_or_error("update_link")
    if gate:
        return gate
    try:
        return await _with_warning(await links.update_link_tool(
            get_api(), get_brain_id(brain_id), link_id, name, color, thickness, direction, relation
        ))
    except Exception:
        await _rollback_debit("update_link")
        raise


@mcp.tool()
async def get_link(link_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Get details about a specific link.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_link")
    if gate:
        return gate
    try:
        return await _with_warning(await links.get_link_tool(get_api(), get_brain_id(brain_id), link_id))
    except Exception:
        await _rollback_debit("get_link")
        raise


@mcp.tool()
async def delete_link(link_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Permanently delete a link by ID. Cannot be undone.

    Once BQL supports DELETE, prefer brain_query for match-then-delete with
    safety guardrails. Use directly only with a specific link ID.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("delete_link")
    if gate:
        return gate
    try:
        return await _with_warning(await links.delete_link_tool(get_api(), get_brain_id(brain_id), link_id))
    except Exception:
        await _rollback_debit("delete_link")
        raise


# Attachment Operations


@mcp.tool()
async def add_file_attachment(
    thought_id: str,
    file_path: str,
    brain_id: str | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Add a file attachment (including images) to a thought.

    Args:
        thought_id: The ID of the thought
        file_path: Path to the file to attach
        brain_id: The ID of the brain (uses active brain if not specified)
        file_name: Name for the attachment (optional, uses filename if not provided)
    """
    gate = await _debit_or_error("add_file_attachment")
    if gate:
        return gate
    try:
        return await _with_warning(await attachments.add_file_attachment_tool(
            get_api(), get_brain_id(brain_id), thought_id, file_path, file_name
        ))
    except Exception:
        await _rollback_debit("add_file_attachment")
        raise


@mcp.tool()
async def add_url_attachment(
    thought_id: str, url: str, brain_id: str | None = None, name: str | None = None
) -> dict[str, Any]:
    """Add a URL attachment to a thought.

    Args:
        thought_id: The ID of the thought
        url: The URL to attach
        brain_id: The ID of the brain (uses active brain if not specified)
        name: Name for the URL attachment (auto-fetched from page title if not provided)
    """
    gate = await _debit_or_error("add_url_attachment")
    if gate:
        return gate
    try:
        return await _with_warning(await attachments.add_url_attachment_tool(
            get_api(), get_brain_id(brain_id), thought_id, url, name
        ))
    except Exception:
        await _rollback_debit("add_url_attachment")
        raise


@mcp.tool()
async def get_attachment(attachment_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Get metadata about an attachment.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("get_attachment")
    if gate:
        return gate
    try:
        return await _with_warning(await attachments.get_attachment_tool(get_api(), get_brain_id(brain_id), attachment_id))
    except Exception:
        await _rollback_debit("get_attachment")
        raise


@mcp.tool()
async def get_attachment_content(
    attachment_id: str, brain_id: str | None = None, save_to_path: str | None = None
) -> dict[str, Any]:
    """Get the binary content of an attachment (e.g., download an image).

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
        save_to_path: Optional path to save the file locally
    """
    gate = await _debit_or_error("get_attachment_content")
    if gate:
        return gate
    try:
        return await _with_warning(await attachments.get_attachment_content_tool(
            get_api(), get_brain_id(brain_id), attachment_id, save_to_path
        ))
    except Exception:
        await _rollback_debit("get_attachment_content")
        raise


@mcp.tool()
async def delete_attachment(attachment_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Delete an attachment.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("delete_attachment")
    if gate:
        return gate
    try:
        return await _with_warning(await attachments.delete_attachment_tool(
            get_api(), get_brain_id(brain_id), attachment_id
        ))
    except Exception:
        await _rollback_debit("delete_attachment")
        raise


@mcp.tool()
async def list_attachments(thought_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """List all attachments for a thought.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("list_attachments")
    if gate:
        return gate
    try:
        return await _with_warning(await attachments.list_attachments_tool(
            get_api(), get_brain_id(brain_id), thought_id
        ))
    except Exception:
        await _rollback_debit("list_attachments")
        raise


# Note Operations


@mcp.tool()
async def get_note(
    thought_id: str, brain_id: str | None = None, format: str = "markdown"
) -> dict[str, Any]:
    """Get the note content for a thought.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        format: Output format (markdown, html, or text)
    """
    gate = await _debit_or_error("get_note")
    if gate:
        return gate
    try:
        return await _with_warning(await notes.get_note_tool(get_api(), get_brain_id(brain_id), thought_id, format))
    except Exception:
        await _rollback_debit("get_note")
        raise


@mcp.tool()
async def create_or_update_note(
    thought_id: str, markdown: str, brain_id: str | None = None
) -> dict[str, Any]:
    """Create or update a note with markdown content.

    Args:
        thought_id: The ID of the thought
        markdown: Markdown content for the note
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("create_or_update_note")
    if gate:
        return gate
    try:
        return await _with_warning(await notes.create_or_update_note_tool(
            get_api(), get_brain_id(brain_id), thought_id, markdown
        ))
    except Exception:
        await _rollback_debit("create_or_update_note")
        raise


@mcp.tool()
async def append_to_note(
    thought_id: str, markdown: str, brain_id: str | None = None
) -> dict[str, Any]:
    """Append content to an existing note.

    Args:
        thought_id: The ID of the thought
        markdown: Markdown content to append
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("append_to_note")
    if gate:
        return gate
    try:
        return await _with_warning(await notes.append_to_note_tool(
            get_api(), get_brain_id(brain_id), thought_id, markdown
        ))
    except Exception:
        await _rollback_debit("append_to_note")
        raise


# Advanced Operations


@mcp.tool()
async def get_modifications(
    brain_id: str | None = None,
    max_logs: int = 100,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Get modification history for a brain.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        max_logs: Maximum number of logs to return
        start_time: Start time for logs (ISO format)
        end_time: End time for logs (ISO format)
    """
    gate = await _debit_or_error("get_modifications")
    if gate:
        return gate
    try:
        return await _with_warning(await stats.get_modifications_tool(
            get_api(), get_brain_id(brain_id), max_logs, start_time, end_time
        ))
    except Exception:
        await _rollback_debit("get_modifications")
        raise


# BrainQuery Tool


@mcp.tool()
async def brain_query(
    query: str,
    brain_id: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Primary tool for pattern-based operations on TheBrain. Accepts BrainQuery
    (BQL) — a Cypher subset supporting MATCH, WHERE, CREATE, SET, MERGE, DELETE,
    and RETURN.

    Use for: searching by name (exact, similarity, prefix, suffix, substring),
    filtering by type, traversing relationships (CHILD, PARENT, JUMP, SIBLING),
    multi-hop chains, variable-length paths (*1..N), creating thoughts/links,
    updating properties, upserting, and deleting thoughts/links.

    Operators: =, =~ (similarity), CONTAINS, STARTS WITH, ENDS WITH.
    Logical: AND, OR, NOT, XOR (with parenthesized grouping).
    Relations: CHILD, PARENT, JUMP, SIBLING.
    Path syntax: (a)-[:CHILD*1..3]->(b) for variable-length,
                 (a)-[:R]->(b)-[:R]->(c) for chains.

    DELETE is two-phase: first call returns a preview (dry-run), then call
    again with confirm=true to execute the deletion.

    Path Scoping: Generic names (e.g., "In-Progress", "TASKS", "Done") may
    exist in multiple sub-graphs. Always anchor queries from a unique ancestor
    and traverse down rather than matching a generic name directly.

    BAD:  MATCH (p {name: "In-Progress"})-[:CHILD]->(t) RETURN t
    GOOD: MATCH (proj {name: "thebrain-mcp"})-[:CHILD*2..3]->(ip)
          WHERE ip.name = "In-Progress" RETURN ip

    Examples:
        MATCH (p:Person) WHERE p.name =~ "Lonnie" RETURN p
        MATCH (a {name: "My Thoughts"})-[:CHILD*1..2]->(b) RETURN b
        MATCH (p {name: "Ideas"}) CREATE (p)-[:CHILD]->(n {name: "New Idea"})
        MATCH (a {name: "A"}), (b {name: "B"}) CREATE (a)-[:JUMP]->(b)
        MATCH (n) WHERE n.name CONTAINS "MCP" AND NOT n.name ENDS WITH "Old" RETURN n
        MATCH (n {name: "Old Note"}) DELETE n
        MATCH (a)-[r:JUMP]->(b {name: "Bob"}) DELETE r
        MATCH (proj {name: "thebrain-mcp"})-[:CHILD]->(tasks {name: "TASKS"})-[:CHILD]->(col)-[:CHILD]->(t) RETURN t
        MATCH (root {name: "Claude Thoughts"})-[:CHILD*1..3]->(d) WHERE d.name CONTAINS "MCP" RETURN d

    If results are unexpectedly empty, retry with get_thought_by_name or
    search_thoughts.

    Args:
        query: A BrainQuery string (Cypher subset). See examples above.
        brain_id: The ID of the brain (uses active brain if not specified)
        confirm: Set to true to confirm and execute a DELETE operation.
                 Without this, DELETE returns a preview of what would be deleted.
    """
    gate = await _debit_or_error("brain_query")
    if gate:
        return gate

    from thebrain_mcp.brainquery import BrainQuerySyntaxError, execute, parse

    try:
        parsed = parse(query)
    except BrainQuerySyntaxError as e:
        await _rollback_debit("brain_query")
        return {"success": False, "error": str(e)}

    if parsed.action == "match_delete":
        parsed.confirm_delete = confirm

    api = get_api()
    bid = get_brain_id(brain_id)

    try:
        result = await execute(api, bid, parsed)
        return await _with_warning(result.to_dict())
    except Exception:
        await _rollback_debit("brain_query")
        raise


# Credential Vault Tools


@mcp.tool()
async def register_credentials(
    thebrain_api_key: str,
    brain_id: str,
    passphrase: str,
) -> dict[str, Any]:
    """Register your TheBrain credentials for multi-tenant access.

    First-time setup: encrypts your API key with your passphrase and stores
    the encrypted blob in the operator's credential vault. The passphrase is
    never stored — you will need it each session to activate access.

    Args:
        thebrain_api_key: Your personal TheBrain API key
        brain_id: The ID of your TheBrain brain
        passphrase: A passphrase to encrypt your credentials (remember this!)
    """
    try:
        user_id = _require_user_id()
        vault = _get_vault()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    # Validate the provided API key by attempting to access the brain
    test_api = TheBrainAPI(thebrain_api_key)
    try:
        await test_api.get_brain(brain_id)
    except Exception:
        return {"success": False, "error": "Invalid API key or brain ID."}
    finally:
        await test_api.close()

    # Encrypt and store
    blob = encrypt_credentials(thebrain_api_key, brain_id, passphrase)
    thought_id = await vault.store(user_id, blob)

    # Activate session immediately
    set_session(user_id, thebrain_api_key, brain_id)

    # Seed starter balance for new users (idempotent via sentinel)
    seed_sats = get_settings().seed_balance_sats
    seed_applied = False
    if seed_sats > 0:
        try:
            cache = _get_ledger_cache()
            ledger = await cache.get(user_id)
            sentinel = "seed_balance_v1"
            if sentinel not in ledger.credited_invoices:
                ledger.credit_deposit(seed_sats, sentinel)
                cache.mark_dirty(user_id)
                await cache.flush_user(user_id)
                seed_applied = True
        except Exception:
            pass  # Seed failure never blocks registration

    result: dict[str, Any] = {
        "success": True,
        "message": "Credentials registered and session activated.",
        "userId": user_id,
        "brainId": brain_id,
        "vaultThoughtId": thought_id,
    }
    if seed_applied:
        result["seed_applied"] = True
        result["seed_balance_api_sats"] = seed_sats
    return result


@mcp.tool()
async def activate_session(passphrase: str) -> dict[str, Any]:
    """Activate your personal TheBrain session by decrypting stored credentials.

    Call this at the start of each session. Provide the same passphrase you
    used during register_credentials.

    Args:
        passphrase: The passphrase you used when registering credentials
    """
    try:
        user_id = _require_user_id()
        vault = _get_vault()
        blob = await vault.fetch(user_id)
        creds = decrypt_credentials(blob, passphrase)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except VaultNotConfiguredError as e:
        return {"success": False, "error": str(e)}
    except CredentialNotFoundError as e:
        return {"success": False, "error": str(e)}
    except DecryptionError as e:
        return {"success": False, "error": str(e)}

    set_session(user_id, creds["api_key"], creds["brain_id"])

    return {
        "success": True,
        "message": "Session activated. All tools now use your personal credentials.",
        "brainId": creds["brain_id"],
    }


@mcp.tool()
async def session_status() -> dict[str, Any]:
    """Check the status of your current session.

    Shows whether you have an active personal session or are using
    the operator's default credentials.
    """
    user_id = _get_current_user_id()

    result: dict[str, Any] = {
        "userId": user_id,
        "mode": "single-tenant (operator default, STDIO)",
        "hasPersonalSession": False,
    }

    if user_id:
        session = get_session(user_id)
        if session:
            result["mode"] = "multi-tenant (personal credentials)"
            result["hasPersonalSession"] = True
            result["brainId"] = session.active_brain_id
            result["sessionAge"] = f"{session.age_seconds}s"
        else:
            result["mode"] = "not activated"
            result["message"] = (
                "Call register_credentials (first time) "
                "or activate_session (returning user)."
            )

    return result


# Operator Admin Tools


async def _refresh_config_impl() -> dict[str, Any]:
    """Core logic for hot-reloading server configuration.

    Extracted so tests can call it directly (the @mcp.tool wrapper
    produces a FunctionTool, not a plain coroutine).
    """
    global _operator_api_client, _btcpay_client, _ledger_cache
    global active_brain_id, _settings_loaded

    refreshed: list[str] = []

    # 0. Snapshot all cached ledgers before teardown
    if _ledger_cache is not None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        snapped = await _ledger_cache.snapshot_all(ts)
        refreshed.append(f"ledger snapshots created ({snapped})")

    # 1. Flush dirty ledger entries so no credits are lost
    if _ledger_cache is not None:
        flushed = await _ledger_cache.flush_all()
        await _ledger_cache.stop()
        refreshed.append(f"ledger_cache flushed ({flushed} dirty entries)")
        _ledger_cache = None

    # 2. Close BTCPay HTTP client
    if _btcpay_client is not None:
        await _btcpay_client.close()
        refreshed.append("btcpay_client closed")
        _btcpay_client = None

    # 3. Close operator API HTTP client
    if _operator_api_client is not None:
        await _operator_api_client.close()
        refreshed.append("operator_api_client closed")
        _operator_api_client = None

    # 4. Reset settings-loaded flag so env vars are re-read
    _settings_loaded = False
    active_brain_id = None
    refreshed.append("settings_loaded reset")

    # 5. Re-load settings from environment
    _ensure_settings_loaded()
    settings = get_settings()

    btcpay_configured = bool(
        settings.btcpay_host and settings.btcpay_store_id and settings.btcpay_api_key
    )
    tier_config_present = bool(settings.btcpay_tier_config)

    return {
        "success": True,
        "refreshed": refreshed,
        "config_summary": {
            "active_brain_id": active_brain_id,
            "btcpay_configured": btcpay_configured,
            "tier_config_present": tier_config_present,
            "vault_brain_id": settings.thebrain_vault_brain_id or None,
        },
    }


@mcp.tool()
async def refresh_config() -> dict[str, Any]:
    """Hot-reload server configuration from environment variables.

    Flushes any dirty ledger entries to vault, tears down cached clients
    (BTCPay, operator API), and re-reads all env vars so that Horizon
    config changes take effect without a full redeploy.

    Operator-only — no user credentials are affected.
    """
    return await _refresh_config_impl()


_VAULT_HOME_THOUGHT_ID = "529bd3cb-59cb-42b9-b360-f0963f1b1c0f"

# BTCPay / credit singletons (lazy-initialized)
_btcpay_client: BTCPayClient | None = None
_ledger_cache: LedgerCache | None = None


def _require_user_id() -> str:
    """Get the current user ID, raising ValueError if not available."""
    user_id = _get_current_user_id()
    if not user_id:
        raise ValueError(
            "Cannot identify user. This tool requires FastMCP Cloud authentication."
        )
    return user_id


def _get_vault() -> CredentialVault:
    """Get a configured CredentialVault instance.

    Raises VaultNotConfiguredError if the operator hasn't set THEBRAIN_VAULT_BRAIN_ID.
    """
    settings = get_settings()
    vault_brain_id = settings.thebrain_vault_brain_id
    if not vault_brain_id:
        raise VaultNotConfiguredError(
            "Vault brain not configured. Operator must set THEBRAIN_VAULT_BRAIN_ID."
        )
    return CredentialVault(
        vault_api=_get_operator_api(),
        vault_brain_id=vault_brain_id,
        home_thought_id=_VAULT_HOME_THOUGHT_ID,
    )


def _get_btcpay() -> BTCPayClient:
    """Get or create the BTCPay client singleton.

    Raises ValueError if BTCPay is not configured.
    """
    global _btcpay_client
    if _btcpay_client is not None:
        return _btcpay_client
    settings = get_settings()
    if not settings.btcpay_host or not settings.btcpay_store_id or not settings.btcpay_api_key:
        raise ValueError(
            "BTCPay not configured. Operator must set "
            "BTCPAY_HOST, BTCPAY_STORE_ID, and BTCPAY_API_KEY."
        )
    _btcpay_client = BTCPayClient(
        settings.btcpay_host, settings.btcpay_api_key, settings.btcpay_store_id
    )
    return _btcpay_client


def _get_ledger_cache() -> LedgerCache:
    """Get or create the ledger cache singleton.

    Starts the background flush task on first creation so dirty
    entries are periodically written to vault (safety net for debits).
    Also registers SIGTERM/SIGINT handlers for graceful shutdown.
    """
    global _ledger_cache
    if _ledger_cache is not None:
        return _ledger_cache
    vault = _get_vault()
    _ledger_cache = LedgerCache(vault)
    # Start background flush — schedule as a fire-and-forget coroutine.
    # This runs inside the event loop that FastMCP/asyncio already provides.
    import asyncio
    try:
        asyncio.ensure_future(_ledger_cache.start_background_flush())
    except RuntimeError:
        # No running event loop yet (e.g. during test setup) — skip
        pass
    _register_shutdown_handlers()
    return _ledger_cache


_shutdown_triggered = False


async def _graceful_shutdown() -> None:
    """Flush all dirty ledger entries to vault before process exit."""
    global _shutdown_triggered, _ledger_cache
    if _shutdown_triggered:
        return
    _shutdown_triggered = True

    if _ledger_cache is not None:
        dirty = _ledger_cache.dirty_count
        logger.info("Graceful shutdown: flushing %d dirty ledger entries...", dirty)
        flushed = await _ledger_cache.flush_all()
        await _ledger_cache.stop()
        logger.info("Graceful shutdown complete: flushed %d entries.", flushed)


def _register_shutdown_handlers() -> None:
    """Register SIGTERM/SIGINT handlers for graceful ledger flush.

    Called once when the ledger cache is first created. On signal receipt,
    schedules an async flush before the process exits.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.ensure_future(_graceful_shutdown()),
            )
        logger.info("Registered SIGTERM/SIGINT handlers for graceful ledger flush.")
    except (NotImplementedError, RuntimeError):
        # Windows doesn't support add_signal_handler; no loop during tests
        pass


# Tool Gating Middleware


async def _with_warning(result: dict[str, Any]) -> dict[str, Any]:
    """Attach a low-balance warning to a paid tool result if balance is low.

    Decorative only — exceptions never block the tool response.
    """
    try:
        user_id = _get_current_user_id()
        if not user_id:
            return result
        cache = _get_ledger_cache()
        ledger = await cache.get(user_id)
        settings = get_settings()
        warning = credits.compute_low_balance_warning(
            ledger, settings.seed_balance_sats,
        )
        if warning:
            result = dict(result)
            result["low_balance_warning"] = warning
    except Exception:
        pass
    return result


async def _debit_or_error(tool_name: str) -> dict[str, Any] | None:
    """Check balance and debit credits for a paid tool call.

    Returns None if the tool is free or STDIO mode (proceed with execution).
    Returns an error dict if the user has insufficient balance.
    """
    cost = TOOL_COSTS.get(tool_name, 0)
    if cost == 0:
        return None

    user_id = _get_current_user_id()
    if not user_id:
        # STDIO mode (local dev) — no gating
        return None

    try:
        cache = _get_ledger_cache()
        ledger = await cache.get(user_id)
    except Exception:
        # Vault not configured — skip gating
        return None

    if not ledger.debit(tool_name, cost):
        return {
            "success": False,
            "error": f"Insufficient balance ({ledger.balance_api_sats} api_sats) "
                     f"for {tool_name} ({cost} api_sats). "
                     f"Use purchase_credits to add funds.",
        }

    cache.mark_dirty(user_id)
    return None


async def _rollback_debit(tool_name: str) -> None:
    """Undo a debit when the downstream API call fails."""
    cost = TOOL_COSTS.get(tool_name, 0)
    if cost == 0:
        return

    user_id = _get_current_user_id()
    if not user_id:
        return

    try:
        cache = _get_ledger_cache()
        ledger = await cache.get(user_id)
    except Exception:
        return

    ledger.rollback_debit(tool_name, cost)
    cache.mark_dirty(user_id)


# Credit Management Tools


@mcp.tool()
async def purchase_credits(amount_sats: int) -> dict[str, Any]:
    """Create a BTCPay invoice to purchase credits via Bitcoin/Lightning.

    Returns a checkout link and invoice ID. After paying, call
    check_payment with the invoice_id to credit your balance.

    Args:
        amount_sats: Number of satoshis to purchase (minimum 1)
    """
    try:
        user_id = _require_user_id()
        btcpay = _get_btcpay()
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    settings = get_settings()
    return await credits.purchase_credits_tool(
        btcpay, cache, user_id, amount_sats,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
    )


@mcp.tool()
async def check_payment(invoice_id: str) -> dict[str, Any]:
    """Check the status of a BTCPay invoice and credit balance on settlement.

    Call this after paying a purchase_credits invoice. Credits are granted
    automatically when payment settles. Safe to call multiple times —
    credits are only granted once per invoice.

    Args:
        invoice_id: The invoice ID returned by purchase_credits
    """
    try:
        user_id = _require_user_id()
        btcpay = _get_btcpay()
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    settings = get_settings()
    return await credits.check_payment_tool(
        btcpay, cache, user_id, invoice_id,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
    )


@mcp.tool()
async def check_balance() -> dict[str, Any]:
    """Check your current credit balance and usage summary.

    Shows balance in api_sats, total deposited/consumed, pending invoices,
    today's per-tool usage breakdown, and cache health metrics.
    """
    try:
        user_id = _require_user_id()
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    settings = get_settings()
    result = await credits.check_balance_tool(
        cache, user_id,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
    )
    result["cache_health"] = cache.health()
    return result


@mcp.tool()
async def restore_credits(invoice_id: str) -> dict[str, Any]:
    """Restore credits from a paid invoice that was lost due to cache/vault issues.

    Verifies the invoice is Settled with BTCPay, then credits the balance.
    Idempotent via credited_invoices — won't double-credit.

    Args:
        invoice_id: The invoice ID returned by purchase_credits
    """
    try:
        user_id = _require_user_id()
        btcpay = _get_btcpay()
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    settings = get_settings()
    return await credits.restore_credits_tool(
        btcpay, cache, user_id, invoice_id,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
    )


@mcp.tool()
async def btcpay_status() -> dict[str, Any]:
    """Check BTCPay Server configuration and connectivity.

    Reports which env vars are set (never exposes the API key itself),
    tier config validity, cache health metrics, and — if fully configured —
    whether the server is reachable and the store is accessible.
    Free diagnostic tool that requires no user authentication.
    """
    _ensure_settings_loaded()
    settings = get_settings()

    btcpay_client: BTCPayClient | None = None
    try:
        btcpay_client = _get_btcpay()
    except ValueError:
        pass

    result = await credits.btcpay_status_tool(settings, btcpay_client)

    # Add cache health if ledger cache exists
    if _ledger_cache is not None:
        result["cache_health"] = _ledger_cache.health()
    else:
        result["cache_health"] = None

    return result


async def _test_low_balance_warning_impl(simulated_balance_api_sats: int = 50) -> dict[str, Any]:
    """Core logic for test_low_balance_warning.

    Extracted so tests can call it directly (the @mcp.tool wrapper
    produces a FunctionTool, not a plain coroutine).
    """
    import dataclasses

    try:
        user_id = _require_user_id()
        cache = _get_ledger_cache()
        ledger = await cache.get(user_id)
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    fake_ledger = dataclasses.replace(ledger, balance_api_sats=simulated_balance_api_sats)
    settings = get_settings()
    warning = credits.compute_low_balance_warning(fake_ledger, settings.seed_balance_sats)

    result: dict[str, Any] = {
        "success": True,
        "simulated_tool": "get_types",
        "note": "This is a simulation — no real tool was called and no credits were debited.",
        "simulated_balance_api_sats": simulated_balance_api_sats,
        "real_balance_api_sats": ledger.balance_api_sats,
    }
    if warning:
        result["low_balance_warning"] = warning
    return result


@mcp.tool()
async def test_low_balance_warning(simulated_balance_api_sats: int = 50) -> dict[str, Any]:
    """Simulate a low-balance tool response with an overridden balance.

    Operator diagnostic: uses your real ledger data but substitutes the
    balance so you can see exactly what an agent would see when balance
    is low. Read-only — never mutates your real ledger.

    Args:
        simulated_balance_api_sats: The fake balance to use for the warning check
    """
    return await _test_low_balance_warning_impl(simulated_balance_api_sats)


def main() -> None:
    """Main entry point for the server."""
    mcp.run()


if __name__ == "__main__":
    main()
