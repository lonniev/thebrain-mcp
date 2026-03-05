"""TheBrain MCP server using FastMCP."""

import logging
import signal
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from tollbooth.config import TollboothConfig
from tollbooth.slug_tools import make_slug_tool

from thebrain_mcp.api.client import TheBrainAPI
from thebrain_mcp.btcpay_client import BTCPayClient, BTCPayError
from thebrain_mcp.config import get_settings
from thebrain_mcp.ledger_cache import LedgerCache
from thebrain_mcp.tools import attachments, brains, credits, links, morpher, notes, orphanage, stats, thoughts, whowhen
from thebrain_mcp.utils.constants import TOOL_COSTS

from thebrain_mcp.vault import (
    CredentialValidationError,
    VaultNotConfiguredError,
    get_session,
    set_session,
)

class TollboothConfigError(Exception):
    """Raised when Tollbooth is misconfigured (e.g., missing BTCPay permissions).

    Blocks all credit-management tools until the operator fixes the config.
    """


# Initialize FastMCP server (don't load settings yet - wait until runtime)
mcp = FastMCP(
    "thebrain-mcp",
    instructions=(
        "TheBrain MCP Server — AI agent access to a personal knowledge graph "
        "powered by TheBrain.\n\n"
        "## Zero-Config Connectivity\n\n"
        "This server runs on FastMCP Cloud over a remote SSE endpoint. "
        "Horizon OAuth handles authentication automatically — no environment "
        "variables, no local install, just connect.\n\n"
        "## Getting Started\n\n"
        "1. Call `session_status` to check your current session.\n"
        "2. If no active session, follow the Secure Courier onboarding flow:\n"
        "   - Get your Nostr npub from the dpyc-oracle's how_to_join() tool\n"
        "   - Call `request_credential_channel(recipient_npub=<npub>)` to receive a welcome DM\n"
        "   - Reply via your Nostr client with your TheBrain API key and brain ID in JSON\n"
        "   - Call `receive_credentials(sender_npub=<npub>)` to vault your credentials\n"
        "3. Returning users: call `receive_credentials(sender_npub=<npub>)` — vault-first "
        "lookup activates instantly, no relay I/O needed.\n\n"
        "## Starter Credits\n\n"
        "First-time users receive a seed balance on registration — enough to "
        "explore your brain without purchasing credits up front.\n\n"
        "## Credits Model\n\n"
        "Tool calls cost api_sats: 1 (read), 5 (write), or 10 (heavy) per call. "
        "Auth and balance tools are always free. Use `check_balance` to see your "
        "balance and usage. Top up via `purchase_credits` with Bitcoin Lightning "
        "(max 0.01 BTC per invoice).\n\n"
        "## Tool Selection Guide\n\n"
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
        "## Full UUIDs Required\n\n"
        "TheBrain API requires full UUIDs (e.g., `9e115e02-fedb-4254-a1ae-39cce16c63e6`) "
        "for all thought and link IDs. Short prefixes like `9e115e02` will return 404. "
        "This is not like GitHub which resolves short SHA prefixes — TheBrain needs the "
        "complete 36-character UUID. If you only have a short prefix, use `search_thoughts` "
        "or `get_thought_by_name` to find the full ID first.\n\n"
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
tool = make_slug_tool(mcp, "brain")

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


# ---------------------------------------------------------------------------
# DPYC registry resolution — derive authority npub from NSEC + community registry
# ---------------------------------------------------------------------------

_cached_operator_npub: str | None = None
_cached_authority_npub: str | None = None
_cached_authority_service_url: str | None = None
_cached_oracle_service_url: str | None = None


def _get_operator_npub() -> str:
    """Derive and cache the operator's npub from its NSEC.

    Raises RuntimeError if TOLLBOOTH_NOSTR_OPERATOR_NSEC is not set.
    """
    global _cached_operator_npub
    if _cached_operator_npub is not None:
        return _cached_operator_npub

    from pynostr.key import PrivateKey  # type: ignore[import-untyped]

    settings = get_settings()
    nsec = settings.tollbooth_nostr_operator_nsec
    if not nsec:
        raise RuntimeError(
            "Operator misconfigured: TOLLBOOTH_NOSTR_OPERATOR_NSEC not set. "
            "Cannot derive operator identity for registry lookup."
        )

    pk = PrivateKey.from_nsec(nsec)
    _cached_operator_npub = pk.public_key.bech32()
    return _cached_operator_npub


async def _resolve_authority_npub() -> str:
    """Derive operator npub from NSEC and look up upstream authority in registry.

    Cached for process lifetime. Raises RuntimeError on failure.
    """
    global _cached_authority_npub
    if _cached_authority_npub is not None:
        return _cached_authority_npub

    from tollbooth.registry import DPYCRegistry, RegistryError

    operator_npub = _get_operator_npub()
    settings = get_settings()

    registry = DPYCRegistry(
        url=settings.dpyc_registry_url,
        cache_ttl_seconds=settings.dpyc_registry_cache_ttl_seconds,
    )
    try:
        authority_npub = await registry.resolve_authority_npub(operator_npub)
    except RegistryError as e:
        raise RuntimeError(
            f"Failed to resolve authority npub for operator {operator_npub}: {e}"
        ) from e
    finally:
        await registry.close()

    _cached_authority_npub = authority_npub
    logger.info(
        "Resolved authority npub from registry: operator=%s authority=%s",
        operator_npub, authority_npub,
    )
    return authority_npub


async def _resolve_authority_service_url() -> str:
    """Resolve the Authority's MCP service URL from the DPYC community registry.

    Cached for process lifetime. Raises RuntimeError on failure.
    """
    global _cached_authority_service_url
    if _cached_authority_service_url is not None:
        return _cached_authority_service_url

    from tollbooth.registry import DPYCRegistry, RegistryError

    operator_npub = _get_operator_npub()
    settings = get_settings()

    registry = DPYCRegistry(
        url=settings.dpyc_registry_url,
        cache_ttl_seconds=settings.dpyc_registry_cache_ttl_seconds,
    )
    try:
        svc = await registry.resolve_authority_service(operator_npub)
    except RegistryError as e:
        raise RuntimeError(
            f"Failed to resolve authority service for operator {operator_npub}: {e}"
        ) from e
    finally:
        await registry.close()

    _cached_authority_service_url = svc["url"]
    logger.info(
        "Resolved authority service URL from registry: %s", svc["url"],
    )
    return _cached_authority_service_url


async def _resolve_oracle_service_url() -> str:
    """Resolve the Oracle's MCP service URL from the DPYC community registry.

    Walks the authority chain to the Prime Authority and finds the
    dpyc-oracle service. Cached for process lifetime. Raises RuntimeError on failure.
    """
    global _cached_oracle_service_url
    if _cached_oracle_service_url is not None:
        return _cached_oracle_service_url

    from tollbooth.registry import DPYCRegistry, RegistryError

    operator_npub = _get_operator_npub()
    settings = get_settings()

    registry = DPYCRegistry(
        url=settings.dpyc_registry_url,
        cache_ttl_seconds=settings.dpyc_registry_cache_ttl_seconds,
    )
    try:
        svc = await registry.resolve_oracle_service(operator_npub)
    except RegistryError as e:
        raise RuntimeError(
            f"Failed to resolve Oracle service for operator {operator_npub}: {e}"
        ) from e
    finally:
        await registry.close()

    _cached_oracle_service_url = svc["url"]
    logger.info(
        "Resolved Oracle service URL from registry: %s", svc["url"],
    )
    return _cached_oracle_service_url


# ---------------------------------------------------------------------------
# DPYC identity (npub-primary: Horizon ID is transport auth, npub is DPYC ID)
# ---------------------------------------------------------------------------

_dpyc_sessions: dict[str, str] = {}  # Horizon user_id → npub


def _get_effective_user_id() -> str:
    """Return the npub for the current user. Requires an active DPYC session.

    Raises ValueError if no DPYC session is active (npub not set).
    Horizon OAuth remains the transport auth layer, but the npub is the
    sole identity for all credit/commerce operations.

    NOTE: Prefer ``_ensure_dpyc_session()`` in async contexts — it
    auto-restores the session from vault on cold start.
    """
    horizon_id = _require_user_id()
    npub = _dpyc_sessions.get(horizon_id)
    if not npub:
        raise ValueError(
            "No DPYC identity active. Credit operations require an npub. "
            "Follow the Secure Courier onboarding flow: call "
            "request_credential_channel(recipient_npub=<npub>), reply via Nostr DM, "
            "then call receive_credentials(sender_npub=<npub>). "
            "Get your npub from the dpyc-oracle's how_to_join() tool."
        )
    return npub


async def _ensure_dpyc_session() -> str:
    """Return the npub for the current user, auto-restoring on cold start.

    Delegates to ``SecureCourierService.ensure_identity()`` which manages
    the in-memory session cache and vault-based cold-start restoration.
    Every operator MCP server gets this for free from the library.

    Raises ValueError if restoration fails (first-time user or forgotten creds).
    """
    horizon_id = _require_user_id()
    courier = _get_courier_service()
    return await courier.ensure_identity(horizon_id, service="thebrain")


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
            "No active session. Follow the Secure Courier onboarding flow "
            "(see session_status) or call receive_credentials(sender_npub=<npub>) "
            "if you've already delivered credentials."
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


@tool
async def whoami() -> dict[str, Any]:
    """Return the authenticated user's identity and token claims.

    This is a diagnostic tool to inspect what OAuth claims are available
    from the FastMCP Cloud authentication layer.
    """
    result: dict[str, Any] = {}
    headers = get_http_headers(include_all=True)
    result["fastmcp_cloud"] = {
        k: v for k, v in headers.items() if k.startswith("fastmcp-")
    } or None
    user_id = _get_current_user_id()
    if user_id:
        npub = _dpyc_sessions.get(user_id)
        result["dpyc_session"] = {"active": npub is not None, "npub": npub}
    return result


# Brain Management Tools


@tool
async def list_brains() -> dict[str, Any]:
    """List all available brains for the user."""
    return await brains.list_brains_tool(get_api())


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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
            get_api(), get_brain_id(brain_id), thought_id, file_path, file_name,
            safe_directory=get_settings().attachment_safe_directory,
        ))
    except Exception:
        await _rollback_debit("add_file_attachment")
        raise


@tool
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


@tool
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


@tool
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
            get_api(), get_brain_id(brain_id), attachment_id, save_to_path,
            safe_directory=get_settings().attachment_safe_directory,
        ))
    except Exception:
        await _rollback_debit("get_attachment_content")
        raise


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


@tool
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


# Morpher Tool


@tool
async def morph_thought(
    thought_id: str,
    brain_id: str | None = None,
    new_parent_id: str | None = None,
    new_type_id: str | None = None,
) -> dict[str, Any]:
    """Atomically reparent and/or retype a thought in one operation.

    Moves a thought to a new parent and/or assigns a new type. Handles
    breaking existing parent links and creating the new parent link.
    At least one of new_parent_id or new_type_id must be provided.

    Args:
        thought_id: The ID of the thought to morph
        brain_id: The ID of the brain (uses active brain if not specified)
        new_parent_id: ID of the new parent thought (replaces all current parents)
        new_type_id: ID of the new type to assign
    """
    gate = await _debit_or_error("morph_thought")
    if gate:
        return gate
    try:
        return await _with_warning(await morpher.morpher_tool(
            get_api(), get_brain_id(brain_id), thought_id, new_parent_id, new_type_id
        ))
    except Exception:
        await _rollback_debit("morph_thought")
        raise


# Orphanage Tool


@tool
async def scan_orphans(
    brain_id: str | None = None,
    dry_run: bool = True,
    batch_size: int = 50,
    orphanage_name: str = "Orphanage",
) -> dict[str, Any]:
    """Scan for orphaned thoughts with zero connections and optionally rescue them.

    Enumerates all thoughts via modification history, checks each for
    connections (parents, children, jumps, siblings, tags), and reports
    those with none. Set dry_run=False to parent orphans under an
    Orphanage collection thought.
    """
    gate = await _debit_or_error("scan_orphans")
    if gate:
        return gate
    try:
        return await _with_warning(await orphanage.scan_orphans_tool(
            get_api(), get_brain_id(brain_id), dry_run, batch_size, orphanage_name
        ))
    except Exception:
        await _rollback_debit("scan_orphans")
        raise


# WhoWhen Tool


@tool
async def event_for_person(
    date: str,
    person: str,
    event_name: str | None = None,
    notes: str | None = None,
    brain_id: str | None = None,
) -> dict[str, Any]:
    """Create an Event+Person+Day in one action.

    Parses a flexible date, finds (or creates) the Person and calendar Day
    thoughts, creates an Event with the structured name
    ``yyyy,MonthName,dd, event_name, person_name``, and wires jump-links
    from the Event to both the Person and the Day.

    Args:
        date: Flexible date string (ISO, natural language, relative)
        person: Full name or thought ID (UUID)
        event_name: Custom event name (auto-generated if omitted)
        notes: Optional markdown note for the Event
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    gate = await _debit_or_error("event_for_person")
    if gate:
        return gate
    try:
        return await _with_warning(await whowhen.event_for_person_tool(
            get_api(), get_brain_id(brain_id), date, person, event_name, notes
        ))
    except Exception:
        await _rollback_debit("event_for_person")
        raise


# ---------------------------------------------------------------------------
# Onboarding guidance (included in session_status for Claude self-guidance)
# ---------------------------------------------------------------------------

_ONBOARDING_NEXT_STEPS = {
    "action": "secure_courier_onboarding",
    "step_1": "Ask the user for their Nostr npub. They can get one from the dpyc-oracle's how_to_join() tool.",
    "step_2": "Call request_credential_channel(recipient_npub=<npub>) to send a welcome DM.",
    "step_3": "Tell the user to open their Nostr client and reply with their TheBrain API key and brain ID in JSON format. Credentials must NEVER appear in this chat.",
    "step_4": "Once the user confirms they replied, call receive_credentials(sender_npub=<npub>) to vault the credentials.",
}


# ---------------------------------------------------------------------------
# Session status
# ---------------------------------------------------------------------------


@tool
async def session_status() -> dict[str, Any]:
    """Check the status of your current session.

    Shows whether you have an active personal session or are using
    the operator's default credentials. Also shows DPYC identity state.

    If no credentials are registered, the response includes a next_steps
    guide for the Secure Courier onboarding flow — follow it to register
    the user's TheBrain credentials via encrypted Nostr DM (credentials
    never appear in chat).
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
                "No active session. Follow the next_steps to onboard via "
                "Secure Courier — credentials travel via encrypted Nostr DM "
                "and never appear in this chat. Returning users: call "
                "receive_credentials(sender_npub=<npub>) to activate instantly."
            )
            result["next_steps"] = _ONBOARDING_NEXT_STEPS

        # DPYC identity
        dpyc_npub = _dpyc_sessions.get(user_id)
        if dpyc_npub:
            result["dpyc_npub"] = dpyc_npub
            result["effective_credit_id"] = dpyc_npub
        else:
            result["effective_credit_id"] = None
            result["dpyc_warning"] = (
                "No DPYC identity active. Credit operations require an npub. "
                "Follow the Secure Courier onboarding flow (see next_steps)."
            )

    return result


# ---------------------------------------------------------------------------
# Secure Courier — credential delivery via encrypted Nostr DM
# ---------------------------------------------------------------------------


async def _on_thebrain_credentials_received(
    sender_npub: str, credentials: dict[str, str], service: str,
) -> dict[str, Any] | None:
    """Operator callback: activate session + DPYC identity after credential receipt.

    Validates the API key + brain ID against TheBrain API, then activates
    the in-memory session, maps the DPYC npub, and seeds the starter balance.
    """
    result: dict[str, Any] = {}

    user_id = _get_current_user_id()
    if not user_id:
        return result

    if not all(k in credentials for k in ("api_key", "brain_id")):
        return result

    api_key = credentials["api_key"]
    brain_id = credentials["brain_id"]

    # Validate credentials against TheBrain API
    test_api = TheBrainAPI(api_key)
    try:
        await test_api.get_brain(brain_id)
    except Exception:
        result["session_activated"] = False
        result["error"] = "Invalid API key or brain ID."
        return result
    finally:
        await test_api.close()

    set_session(user_id, api_key, brain_id)
    _dpyc_sessions[user_id] = sender_npub
    result["session_activated"] = True
    result["dpyc_npub"] = sender_npub

    # Seed starter balance (idempotent via sentinel)
    seed_applied = await _seed_balance(sender_npub)
    if seed_applied:
        result["seed_applied"] = True
        result["seed_balance_api_sats"] = get_settings().seed_balance_sats

    return result


_courier_service = None

_DEFAULT_RELAY = "wss://nostr.wine"
_FALLBACK_POOL = [
    "wss://relay.primal.net",
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]


def _resolve_relays(configured: str | None) -> list[str]:
    """Resolve relay list: env var -> default -> probe fallback pool."""
    from tollbooth.nostr_diagnostics import probe_relay_liveness

    if configured:
        relays = [r.strip() for r in configured.split(",") if r.strip()]
    else:
        relays = [_DEFAULT_RELAY]

    results = probe_relay_liveness(relays, timeout=5)
    live = [r["relay"] for r in results if r["connected"]]

    if live:
        logger.info("Relay probe: %d/%d configured relays live", len(live), len(relays))
        return live

    # All configured relays down — probe fallback pool
    logger.warning("All configured relays down (%s), probing fallback pool...", ", ".join(relays))
    fallback_results = probe_relay_liveness(_FALLBACK_POOL, timeout=5)
    fallback_live = [r["relay"] for r in fallback_results if r["connected"]]

    if fallback_live:
        logger.info("Fallback relays live: %s", ", ".join(fallback_live))
        return fallback_live

    # Nothing alive — return configured + fallback and hope for recovery
    logger.warning("No relays responded — using full list, hoping for recovery")
    return relays + _FALLBACK_POOL


def _get_courier_service():
    """Get or create the SecureCourierService singleton."""
    global _courier_service
    if _courier_service is not None:
        return _courier_service

    from tollbooth.credential_templates import CredentialTemplate, FieldSpec
    from tollbooth.nostr_credentials import NostrProfile
    from tollbooth.secure_courier import SecureCourierService
    from tollbooth.vaults import NeonCredentialVault

    settings = get_settings()

    nsec = settings.tollbooth_nostr_operator_nsec
    if not nsec:
        raise ValueError(
            "Secure Courier not configured. "
            "Set TOLLBOOTH_NOSTR_OPERATOR_NSEC to enable credential delivery via Nostr DM."
        )

    relays = _resolve_relays(settings.tollbooth_nostr_relays)

    templates = {
        "thebrain": CredentialTemplate(
            service="thebrain",
            version=2,
            fields={
                "api_key": FieldSpec(required=True, sensitive=True),
                "brain_id": FieldSpec(required=True, sensitive=False),
            },
            description="TheBrain API key and brain ID for personal knowledge graph access",
        ),
    }

    # Credential vault backed by the same NeonVault used for commerce
    commerce_vault = _get_commerce_vault()
    # commerce_vault may be wrapped in AuditedVault; unwrap to get the NeonVault
    neon_vault = commerce_vault
    if hasattr(neon_vault, "_inner"):
        neon_vault = neon_vault._inner
    credential_vault = NeonCredentialVault(neon_vault=neon_vault)

    _courier_service = SecureCourierService(
        operator_nsec=nsec,
        relays=relays,
        templates=templates,
        credential_vault=credential_vault,
        profile=NostrProfile(
            name="thebrain-mcp",
            display_name="Personal Brain MCP",
            about=(
                "AI agent access to your personal knowledge graph — "
                "Tollbooth DPYC monetized, Nostr-native. "
                "Send credentials via encrypted DM (Secure Courier)."
            ),
            website="https://github.com/lonniev/thebrain-mcp",
        ),
        on_credentials_received=_on_thebrain_credentials_received,
    )

    return _courier_service


@tool
async def request_credential_channel(
    service: str = "thebrain",
    recipient_npub: str | None = None,
) -> dict[str, Any]:
    """Open a Secure Courier channel for out-of-band credential delivery.

    If you provide your npub, the service sends you a welcome DM — just
    open your Nostr client and reply to it with your credentials. No need
    to copy-paste an npub or compose a new message.

    How it works:
    1. Call this tool with your npub — a welcome DM arrives in your Nostr inbox.
    2. Open your Nostr client (Primal, Damus, Amethyst, etc.).
    3. Reply to the welcome message with a JSON payload: {"api_key": "...", "brain_id": "..."}
    4. Return here and call receive_credentials with your npub.

    Your credentials never appear in this chat — they travel on a
    separate, encrypted Nostr channel (the "diplomatic pouch").

    Args:
        service: Which credential template to use (default "thebrain").
        recipient_npub: Your Nostr public key (npub1...). If provided, you'll
            receive a welcome DM to reply to instead of composing from scratch.
    """
    try:
        courier = _get_courier_service()
    except (ValueError, RuntimeError) as e:
        return {"success": False, "error": str(e)}

    try:
        return await courier.open_channel(
            service,
            greeting=(
                "Hi — I'm Personal Brain MCP, a Tollbooth service for AI agent "
                "access to your TheBrain knowledge graph. You (or your AI agent) "
                "requested a credential channel."
            ),
            recipient_npub=recipient_npub,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
async def receive_credentials(
    sender_npub: str = "",
    service: str = "thebrain",
    credential_card: str = "",
) -> dict[str, Any]:
    """Pick up credentials delivered via the Secure Courier.

    If you've previously delivered credentials for this service, they'll
    be returned from the encrypted vault without any relay I/O (instant).

    If this is your first time, the tool checks Nostr relays for your
    encrypted DM, validates it against the template, stores it in the
    vault for future sessions, and activates your session.

    Alternatively, pass a credential_card (ncred1... string) to redeem
    a QR credential card — bypasses relay DM flow entirely.

    Credential values are NEVER echoed back — only the field count and
    service name are returned.

    Args:
        sender_npub: Your Nostr public key (npub1...) — the one you
            sent the DM from.  Required unless credential_card is provided.
        service: Which credential template to match (default "thebrain").
        credential_card: Optional ncred1... credential card string.
            If provided, redeems the card directly (no relay DM needed).
    """
    try:
        courier = _get_courier_service()
    except (ValueError, RuntimeError) as e:
        return {"success": False, "error": str(e)}

    try:
        if credential_card:
            return await courier.redeem_card(credential_card, service=service)
        if not sender_npub:
            return {
                "success": False,
                "error": "Either sender_npub or credential_card is required.",
            }
        return await courier.receive(
            sender_npub, service=service, caller_id=_get_current_user_id(),
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
async def forget_credentials(sender_npub: str, service: str = "thebrain") -> dict[str, Any]:
    """Delete vaulted credentials so you can re-deliver via Secure Courier.

    Use this when you've rotated your API keys and need to send fresh
    credentials through the diplomatic pouch.

    Args:
        sender_npub: Your Nostr public key (npub1...).
        service: Which service's credentials to forget (default "thebrain").
    """
    try:
        courier = _get_courier_service()
    except (ValueError, RuntimeError) as e:
        return {"success": False, "error": str(e)}

    return await courier.forget(
        sender_npub, service=service, caller_id=_get_current_user_id(),
    )


# ---------------------------------------------------------------------------
# Vault + credit infrastructure singletons
# ---------------------------------------------------------------------------

_COMMERCE_VAULT_HOME = "4a6ebe9b-88a8-48a8-b0e0-9be688d81f45"

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


async def _seed_balance(npub: str) -> bool:
    """Apply seed balance for a new user (idempotent via sentinel)."""
    settings = get_settings()
    if settings.seed_balance_sats <= 0:
        return False
    try:
        cache = _get_ledger_cache()
        ledger = await cache.get(npub)
        sentinel = "seed_balance_v1"
        if sentinel not in ledger.credited_invoices:
            ledger.credit_deposit(settings.seed_balance_sats, sentinel)
            cache.mark_dirty(npub)
            await cache.flush_user(npub)
            return True
    except Exception:
        pass
    return False


_commerce_vault: Any = None


def _get_commerce_vault() -> Any:
    """Singleton NeonVault for commerce ledgers.

    Requires NEON_DATABASE_URL. Optional: Wrapped with AuditedVault for
    Nostr audit trail when configured.

    Raises VaultNotConfiguredError if not configured.
    """
    global _commerce_vault
    if _commerce_vault is not None:
        return _commerce_vault

    settings = get_settings()

    if not settings.neon_database_url:
        raise VaultNotConfiguredError(
            "Commerce vault not configured. Set NEON_DATABASE_URL to enable credits."
        )

    from tollbooth.vaults import NeonVault

    vault: Any = NeonVault(database_url=settings.neon_database_url)
    # ensure_schema is idempotent — safe on every cold start
    import asyncio

    try:
        asyncio.ensure_future(vault.ensure_schema())
    except RuntimeError:
        pass  # No running event loop yet (e.g. during test setup)
    logger.info("NeonVault initialized for ledger persistence.")

    # Also ensure credential vault schema
    from tollbooth.vaults import NeonCredentialVault

    cred_vault = NeonCredentialVault(neon_vault=vault)
    try:
        asyncio.ensure_future(cred_vault.ensure_schema())
    except RuntimeError:
        pass

    # Optional: Nostr audit decorator
    if settings.tollbooth_nostr_audit_enabled == "true":
        from tollbooth.nostr_audit import AuditedVault, NostrAuditPublisher

        publisher = NostrAuditPublisher(
            operator_nsec=settings.tollbooth_nostr_operator_nsec or "",
            relays=[r.strip() for r in (settings.tollbooth_nostr_relays or "").split(",") if r.strip()],
        )
        vault = AuditedVault(vault, publisher)
        logger.info("Nostr audit enabled — publishing to %s", settings.tollbooth_nostr_relays)

    _commerce_vault = vault
    return _commerce_vault


# ---------------------------------------------------------------------------
# Constraint gate singleton
# ---------------------------------------------------------------------------

_gate: Any = None
_gate_initialized: bool = False


def _get_gate():
    """Return the ConstraintGate singleton, or None if constraints are off."""
    global _gate, _gate_initialized
    if _gate_initialized:
        return _gate
    from tollbooth.constraints.gate import ConstraintGate
    settings = get_settings()
    config = settings.to_tollbooth_config()
    if config.constraints_enabled:
        _gate = ConstraintGate(config)
    _gate_initialized = True
    return _gate


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
    if settings.tollbooth_royalty_address:
        logger.info(
            "BTCPay initialized — royalty payouts enabled: %s (%.1f%%, min %d sats)",
            settings.tollbooth_royalty_address,
            settings.tollbooth_royalty_percent * 100,
            settings.tollbooth_royalty_min_sats,
        )
    else:
        logger.info("BTCPay initialized — royalty payouts disabled (no address configured)")
    return _btcpay_client


# Preflight permission check (runs once per BTCPay client lifecycle)
_btcpay_preflight_done = False

_REQUIRED_BTCPAY_PERMISSIONS = [
    "btcpay.store.cancreateinvoice",
    "btcpay.store.canviewinvoices",
    "btcpay.store.cancreatenonapprovedpullpayments",
]


async def _ensure_btcpay_preflight(btcpay: BTCPayClient) -> None:
    """Verify BTCPay API key has required permissions.  Runs once.

    When royalty is configured (address is set), the payout permission
    is mandatory.  Raises TollboothConfigError on failure — the server
    refuses to serve credit tools until the operator fixes the API key.
    """
    global _btcpay_preflight_done
    if _btcpay_preflight_done:
        return

    settings = get_settings()
    royalty_configured = bool(settings.tollbooth_royalty_address)

    required = [
        "btcpay.store.cancreateinvoice",
        "btcpay.store.canviewinvoices",
    ]
    if royalty_configured:
        required.append("btcpay.store.cancreatenonapprovedpullpayments")

    try:
        key_info = await btcpay.get_api_key_info()
    except BTCPayError as e:
        raise TollboothConfigError(
            f"Cannot verify BTCPay API key permissions: {e}. "
            f"Tollbooth requires a permission check when royalty is configured."
        ) from e

    granted = set(key_info.get("permissions", []))
    store_id = settings.btcpay_store_id

    missing = []
    for perm in required:
        # BTCPay grants either global ("btcpay.store.canX") or store-scoped ("btcpay.store.canX:storeId")
        if perm not in granted and f"{perm}:{store_id}" not in granted:
            missing.append(perm)

    if missing:
        raise TollboothConfigError(
            f"BTCPay API key missing required permissions: {missing}. "
            f"Tollbooth requires all of: {required}. "
            f"Regenerate your API key with these permissions."
        )

    _btcpay_preflight_done = True
    logger.info("BTCPay preflight passed — all required permissions verified.")


def _get_ledger_cache() -> LedgerCache:
    """Get or create the ledger cache singleton.

    Starts the background flush task on first creation so dirty
    entries are periodically written to vault (safety net for debits).
    Also registers SIGTERM/SIGINT handlers for graceful shutdown.
    """
    global _ledger_cache
    if _ledger_cache is not None:
        return _ledger_cache
    vault = _get_commerce_vault()
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
_reconciled_users: set[str] = set()


async def _graceful_shutdown() -> None:
    """Flush all dirty ledger entries to vault before process exit."""
    global _shutdown_triggered, _ledger_cache, _commerce_vault
    if _shutdown_triggered:
        return
    _shutdown_triggered = True

    if _ledger_cache is not None:
        dirty = _ledger_cache.dirty_count
        logger.info("Graceful shutdown: flushing %d dirty ledger entries...", dirty)
        try:
            import asyncio as _aio
            await _aio.wait_for(
                _shutdown_flush_and_stop(), timeout=8.0
            )
        except _aio.TimeoutError:
            logger.error("Graceful shutdown timed out after 8s — some entries may be lost.")

    if _commerce_vault is not None:
        _closer = getattr(_commerce_vault, "close", None)
        if _closer is not None:
            await _closer()
        _commerce_vault = None


async def _shutdown_flush_and_stop() -> None:
    """Flush and stop the ledger cache (extracted for wait_for wrapping)."""
    assert _ledger_cache is not None
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
    Uses the effective DPYC user ID (npub) for ledger lookup.
    """
    try:
        user_id = await _ensure_dpyc_session()
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


def _demand_window_key() -> str:
    """Hourly demand window key (e.g. '2026-03-05T14:00')."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")


async def _get_global_demand(tool_name: str) -> dict[str, int]:
    """Read global demand from NeonVault. Returns {} on error (base pricing)."""
    try:
        vault = _get_commerce_vault()
        count = await vault.get_demand(tool_name, _demand_window_key())
        return {tool_name: count}
    except Exception:
        return {}


def _fire_and_forget_demand_increment(tool_name: str) -> None:
    """Increment demand counter — async, non-blocking."""
    import asyncio

    async def _inc():
        try:
            vault = _get_commerce_vault()
            await vault.increment_demand(tool_name, _demand_window_key())
        except Exception:
            pass

    asyncio.create_task(_inc())


async def _debit_or_error(tool_name: str) -> dict[str, Any] | None:
    """Check balance and debit credits for a paid tool call.

    Returns None if the tool is free or STDIO mode (proceed with execution).
    Returns an error dict if the user has insufficient balance or no DPYC session.
    Uses the npub (effective DPYC ID) for all ledger operations.
    """
    cost = TOOL_COSTS.get(tool_name, 0)
    if cost == 0:
        return None

    horizon_id = _get_current_user_id()
    if not horizon_id:
        # STDIO mode (local dev) — no gating
        return None

    try:
        user_id = await _ensure_dpyc_session()
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        cache = _get_ledger_cache()
        ledger = await cache.get(user_id)
    except Exception:
        # Vault not configured — skip gating
        return None

    # ConstraintGate may modify cost or deny the call
    gate = _get_gate()
    if gate and gate.enabled:
        demand = await _get_global_demand(tool_name)
        denial, effective_cost = gate.check(
            tool_name=tool_name,
            base_cost=cost,
            ledger=ledger,
            npub=user_id,
            global_demand=demand,
        )
        if denial is not None:
            return denial
        cost = effective_cost

    # Constraint may have reduced cost to zero (free trial)
    if cost == 0:
        return None

    if not ledger.debit(tool_name, cost):
        return {
            "success": False,
            "error": f"Insufficient balance ({ledger.balance_api_sats} api_sats) "
                     f"for {tool_name} ({cost} api_sats). "
                     f"Use purchase_credits to add funds.",
        }

    cache.mark_dirty(user_id)

    # Successful debit — increment demand (fire-and-forget)
    _fire_and_forget_demand_increment(tool_name)

    return None


async def _rollback_debit(tool_name: str) -> None:
    """Undo a debit when the downstream API call fails."""
    cost = TOOL_COSTS.get(tool_name, 0)
    if cost == 0:
        return

    try:
        user_id = await _ensure_dpyc_session()
    except ValueError:
        return

    try:
        cache = _get_ledger_cache()
        ledger = await cache.get(user_id)
    except Exception:
        return

    ledger.rollback_debit(tool_name, cost)
    cache.mark_dirty(user_id)


# Credit Management Tools


@tool
async def purchase_credits(
    amount_sats: int,
) -> dict[str, Any]:
    """Create a BTCPay Lightning invoice to purchase credits for tool calls.

    Automatically obtains an Authority-signed certificate behind the scenes —
    no manual certification step needed.

    Call flow:
    1. Call purchase_credits(amount_sats) → get Lightning invoice
    2. Pay the invoice with any Lightning wallet
    3. Call check_payment(invoice_id) → credits land in your balance

    Credits are denominated in api_sats: 1 sat buys 1 api_sat (default tier).
    VIP tiers may have higher multipliers. Maximum 1,000,000 sats (0.01 BTC) per invoice.

    Args:
        amount_sats: Number of satoshis to purchase (minimum 1, maximum 1,000,000).
            The Authority's certification fee is deducted automatically; the
            invoice will be for the net amount (purchase minus tax).

    Returns:
        invoice_id: BTCPay invoice ID (pass to check_payment after paying).
        checkout_link: URL to pay the Lightning invoice.
        expected_credits: How many api_sats you'll receive at your tier multiplier.
        certificate_jti: Certificate ID for audit trail.

    Next step: Pay the invoice, then call check_payment(invoice_id).
    """
    try:
        user_id = await _ensure_dpyc_session()
        btcpay = _get_btcpay()
        await _ensure_btcpay_preflight(btcpay)
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError, TollboothConfigError) as e:
        return {"success": False, "error": str(e)}

    settings = get_settings()

    try:
        authority_npub = await _resolve_authority_npub()
        authority_url = await _resolve_authority_service_url()
        operator_npub = _get_operator_npub()
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    # Auto-certify via server-to-server MCP call with Horizon OAuth
    from tollbooth.authority_client import AuthorityCertifier, AuthorityCertifyError

    certifier = AuthorityCertifier(authority_url, operator_npub)
    try:
        cert_result = await certifier.certify(amount_sats)
    except AuthorityCertifyError as e:
        return {"success": False, "error": f"Authority certification failed: {e}"}

    return await credits.purchase_credits_tool(
        btcpay, cache, user_id, amount_sats,
        certificate=cert_result["certificate"],
        authority_npub=authority_npub,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
        default_credit_ttl_seconds=settings.credit_ttl_seconds,
    )


@tool
async def check_payment(invoice_id: str) -> dict[str, Any]:
    """Verify that a Lightning invoice has settled and credit the payment to your balance.

    Call this after paying the invoice from purchase_credits. Safe to call
    multiple times — credits are only granted once per invoice (idempotent).
    Also fires a 2% royalty payout to the Tollbooth originator on settlement.

    Invoice lifecycle: New → Processing → Settled (credits granted) or
    Expired/Invalid (invoice removed from pending list).

    Args:
        invoice_id: The BTCPay invoice ID returned by purchase_credits

    Returns:
        status: BTCPay invoice status (New, Processing, Settled, Expired, Invalid).
        credits_granted: api_sats credited (only on first Settled check; 0 if already credited).
        balance_api_sats: Your updated balance after any crediting.

    Next step: Call check_balance to confirm, then continue using tools.
    """
    try:
        user_id = await _ensure_dpyc_session()
        btcpay = _get_btcpay()
        await _ensure_btcpay_preflight(btcpay)
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError, TollboothConfigError) as e:
        return {"success": False, "error": str(e)}

    settings = get_settings()
    return await credits.check_payment_tool(
        btcpay, cache, user_id, invoice_id,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
        royalty_address=settings.tollbooth_royalty_address,
        royalty_percent=settings.tollbooth_royalty_percent,
        royalty_min_sats=settings.tollbooth_royalty_min_sats,
        default_credit_ttl_seconds=settings.credit_ttl_seconds,
    )


@tool
async def check_balance() -> dict[str, Any]:
    """Check your current credit balance, tier info, usage summary, and cache health.

    Read-only — no side effects. Call anytime to check your funding level,
    review today's per-tool usage breakdown, or inspect invoice history.

    Returns:
        balance_api_sats: Current available credit balance.
        total_deposited_api_sats: Lifetime credits purchased.
        total_consumed_api_sats: Lifetime credits consumed by tool calls.
        pending_invoices: Count of unpaid invoices.
        today_usage: Per-tool call counts and api_sats consumed today.
        cache_health: Ledger cache metrics (dirty count, size, flush stats).

    Next step: If balance is low, call purchase_credits to top up.
    """
    try:
        user_id = await _ensure_dpyc_session()
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    # One-time reconciliation per user per process lifetime
    if user_id not in _reconciled_users:
        _reconciled_users.add(user_id)
        try:
            btcpay = _get_btcpay()
            settings_r = get_settings()
            from tollbooth.tools.credits import reconcile_pending_invoices
            recon = await reconcile_pending_invoices(
                btcpay, cache, user_id,
                tier_config_json=settings_r.btcpay_tier_config,
                user_tiers_json=settings_r.btcpay_user_tiers,
                default_credit_ttl_seconds=settings_r.credit_ttl_seconds,
            )
            if recon["reconciled"] > 0:
                logger.info(
                    "Reconciled %d pending invoice(s) for %s: %s",
                    recon["reconciled"], user_id, recon["actions"],
                )
        except Exception:
            logger.warning("Reconciliation failed for %s (non-fatal).", user_id)

    settings = get_settings()
    result = await credits.check_balance_tool(
        cache, user_id,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
        default_credit_ttl_seconds=settings.credit_ttl_seconds,
    )
    result["cache_health"] = cache.health()
    return result


@tool
async def account_statement(days: int = 30) -> dict[str, Any]:
    """Generate a customer-facing account statement with purchase history and usage.

    Returns a detailed statement including: account summary (balance, deposited,
    consumed, expired), invoice line items with dates and amounts, active credit
    tranches with expiration dates, all-time per-tool usage breakdown, and recent
    daily usage logs.

    Suitable as proof-of-purchase and usage auditing for customers.
    Free — no credits consumed.

    Args:
        days: Number of days of daily usage history to include (default 30).

    Returns:
        account_summary: Balance, deposited, consumed, expired totals.
        purchase_history: Invoice line items sorted by date (most recent first).
        active_tranches: Current credit allocations with expiration info.
        tool_usage_all_time: Per-tool call counts and api_sats (sorted by usage).
        daily_usage: Per-day usage breakdown for the requested period.
    """
    try:
        user_id = await _ensure_dpyc_session()
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    result = await credits.account_statement_tool(cache, user_id, days=days)
    if result.get("success"):
        result["infographic_hint"] = (
            "Call account_statement_infographic for a visual SVG version (1 api_sat)."
        )
    return result


@tool
async def account_statement_infographic(days: int = 30) -> dict[str, Any]:
    """Generate a visual SVG infographic of your account statement.

    Returns the same data as account_statement, rendered as a dark-themed
    SVG graphic with balance hero, metrics cards, health gauge, tranche
    table, and tool usage breakdown. Suitable for sharing or embedding.

    Costs 1 api_sat per call.

    Args:
        days: Number of days of daily usage history to include (default 30).

    Returns:
        svg: The SVG markup string.
        generated_at: ISO timestamp of generation.
    """
    gate = await _debit_or_error("account_statement_infographic")
    if gate:
        return gate

    try:
        user_id = await _ensure_dpyc_session()
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError) as e:
        await _rollback_debit("account_statement_infographic")
        return {"success": False, "error": str(e)}

    try:
        from thebrain_mcp.infographic import render_account_infographic

        data = await credits.account_statement_tool(cache, user_id, days=days)
        if not data.get("success"):
            await _rollback_debit("account_statement_infographic")
            return data

        svg = render_account_infographic(data)
        result: dict[str, Any] = {
            "success": True,
            "svg": svg,
            "generated_at": data.get("generated_at", ""),
        }
        return await _with_warning(result)
    except Exception:
        await _rollback_debit("account_statement_infographic")
        raise


@tool
async def restore_credits(invoice_id: str) -> dict[str, Any]:
    """Restore credits from a paid invoice that was lost due to cache or vault issues.

    Emergency recovery tool. Call when you paid an invoice but your balance
    didn't update — typically caused by a cache eviction or vault flush failure.
    Checks vault records first, falls back to BTCPay API verification. Safe to
    call multiple times; will never double-credit.

    Args:
        invoice_id: The BTCPay invoice ID from a purchase_credits call you already paid

    Returns:
        source: 'vault_record' or 'btcpay' — where settlement was confirmed.
        credits_granted: api_sats credited (0 if already credited).
        balance_api_sats: Updated balance after restoration.
    """
    try:
        user_id = await _ensure_dpyc_session()
        btcpay = _get_btcpay()
        await _ensure_btcpay_preflight(btcpay)
        cache = _get_ledger_cache()
    except (ValueError, VaultNotConfiguredError, TollboothConfigError) as e:
        return {"success": False, "error": str(e)}

    settings = get_settings()
    return await credits.restore_credits_tool(
        btcpay, cache, user_id, invoice_id,
        tier_config_json=settings.btcpay_tier_config,
        user_tiers_json=settings.btcpay_user_tiers,
        default_credit_ttl_seconds=settings.credit_ttl_seconds,
    )


@tool
async def btcpay_status() -> dict[str, Any]:
    """Check BTCPay Server configuration, connectivity, and permissions.

    Operator diagnostic tool. Reports which env vars are configured (never
    exposes the API key itself), tier config validity, royalty settings, cache
    health, and — if fully configured — whether the server is reachable, the
    store is accessible, and the API key has required permissions.

    Call this during initial setup to verify BTCPay configuration, or when
    payments aren't working to diagnose connectivity or permission issues.
    Free — requires no user authentication or balance.

    Returns:
        btcpay_host/btcpay_store_id: Configured endpoints.
        server_reachable: True/False/None (None if not configured).
        store_name: Store name or error status.
        api_key_permissions: Required vs present permissions, with missing list.
        royalty_config: Address, percent, min_sats, enabled flag.
        cache_health: Ledger cache metrics (if initialized).
    """
    _ensure_settings_loaded()
    settings = get_settings()

    btcpay_client: BTCPayClient | None = None
    try:
        btcpay_client = _get_btcpay()
    except ValueError:
        pass

    try:
        authority_npub = await _resolve_authority_npub()
    except RuntimeError:
        authority_npub = None  # Non-fatal for diagnostics

    config = TollboothConfig(
        btcpay_host=settings.btcpay_host,
        btcpay_store_id=settings.btcpay_store_id,
        btcpay_api_key=settings.btcpay_api_key,
        btcpay_tier_config=settings.btcpay_tier_config,
        btcpay_user_tiers=settings.btcpay_user_tiers,
        seed_balance_sats=settings.seed_balance_sats,
        tollbooth_royalty_address=settings.tollbooth_royalty_address,
        tollbooth_royalty_percent=settings.tollbooth_royalty_percent,
        tollbooth_royalty_min_sats=settings.tollbooth_royalty_min_sats,
        authority_npub=authority_npub,
        credit_ttl_seconds=settings.credit_ttl_seconds,
    )
    result = await credits.btcpay_status_tool(config, btcpay_client)

    # Augment version provenance with host-layer packages
    import importlib.metadata as _meta
    versions = result.get("versions", {})
    try:
        versions["thebrain_mcp"] = _meta.version("thebrain-mcp")
    except _meta.PackageNotFoundError:
        versions["thebrain_mcp"] = "unknown"
    result["versions"] = versions

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

    from tollbooth.ledger import Tranche

    try:
        user_id = await _ensure_dpyc_session()
        cache = _get_ledger_cache()
        ledger = await cache.get(user_id)
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    # Build a fake ledger with the simulated balance (balance_api_sats
    # is now a computed property over tranches, not a settable field).
    fake_ledger = dataclasses.replace(ledger)
    fake_ledger.tranches = [
        Tranche(
            granted_at=time.time(),
            original_sats=simulated_balance_api_sats,
            remaining_sats=simulated_balance_api_sats,
            invoice_id="simulation",
        )
    ]
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


@tool
async def test_low_balance_warning(simulated_balance_api_sats: int = 50) -> dict[str, Any]:
    """Simulate a low-balance tool response with an overridden balance.

    Operator diagnostic: uses your real ledger data but substitutes the
    balance so you can see exactly what an agent would see when balance
    is low. Read-only — never mutates your real ledger.

    Args:
        simulated_balance_api_sats: The fake balance to use for the warning check
    """
    return await _test_low_balance_warning_impl(simulated_balance_api_sats)


# OpenTimestamps Bitcoin Anchoring Tools


def _get_neon_vault() -> Any:
    """Unwrap AuditedVault to reach the NeonVault underneath.

    OTS anchor tools require NeonVault-specific methods (fetch_all_balances,
    store_anchor, etc.) that aren't part of the VaultBackend protocol.
    """
    vault = _get_commerce_vault()
    # If wrapped in AuditedVault, unwrap to inner vault
    inner = getattr(vault, "_inner", None)
    if inner is not None:
        vault = inner
    # Verify it's a NeonVault (has fetch_all_balances)
    if not hasattr(vault, "fetch_all_balances"):
        raise ValueError(
            "OTS anchoring requires NeonVault. "
            "Set NEON_DATABASE_URL to enable NeonVault persistence."
        )
    return vault


@tool
async def anchor_ledger() -> dict[str, Any]:
    """Anchor all ledger balances to Bitcoin via OpenTimestamps.

    Builds a SHA-256 Merkle tree of every patron's current balance,
    submits the root to OTS calendar servers, and stores the anchor
    record for later proof generation. Bitcoin confirmation takes 1-6 hours.

    Operator-only tool. Requires TOLLBOOTH_OTS_ENABLED=true and NeonVault.
    """
    settings = get_settings()
    if settings.tollbooth_ots_enabled != "true":
        return {
            "success": False,
            "error": "OTS anchoring is not enabled. "
            "Set TOLLBOOTH_OTS_ENABLED=true to enable.",
        }

    try:
        vault = _get_neon_vault()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    calendars = None
    if settings.tollbooth_ots_calendars:
        calendars = [c.strip() for c in settings.tollbooth_ots_calendars.split(",") if c.strip()]

    from tollbooth.tools.anchors import anchor_ledger_tool
    return await anchor_ledger_tool(vault, ots_calendars=calendars)


@tool
async def get_anchor_proof(anchor_id: str) -> dict[str, Any]:
    """Get a Merkle inclusion proof for your balance in a Bitcoin anchor.

    Proves that your balance (identified by npub) was included in a
    Merkle tree whose root was submitted to Bitcoin via OpenTimestamps.
    The proof can be independently verified using only SHA-256.

    Args:
        anchor_id: The anchor record ID (from list_anchors or anchor_ledger).
    """
    gate = await _debit_or_error("get_anchor_proof")
    if gate:
        return gate

    try:
        user_id = await _ensure_dpyc_session()
        vault = _get_neon_vault()
    except (ValueError, VaultNotConfiguredError) as e:
        await _rollback_debit("get_anchor_proof")
        return {"success": False, "error": str(e)}

    from tollbooth.tools.anchors import get_anchor_proof_tool
    try:
        result = await get_anchor_proof_tool(vault, anchor_id, user_id)
        return await _with_warning(result)
    except Exception:
        await _rollback_debit("get_anchor_proof")
        raise


@tool
async def list_anchors(
    limit: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    """List recent Bitcoin anchor records.

    Shows when ledger snapshots were anchored to Bitcoin, their status
    (submitted, confirmed), and how many patron balances were included.

    Args:
        limit: Maximum number of anchors to return (default 20).
        status: Optional filter by status (e.g., "submitted", "confirmed").
    """
    try:
        vault = _get_neon_vault()
    except (ValueError, VaultNotConfiguredError) as e:
        return {"success": False, "error": str(e)}

    from tollbooth.tools.anchors import list_anchors_tool
    return await list_anchors_tool(vault, limit=limit, status=status)


# ---------------------------------------------------------------------------
# Oracle delegation tools (free, unauthenticated community tools)
# ---------------------------------------------------------------------------


async def _call_oracle(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve Oracle URL and delegate a tool call via OracleClient."""
    from tollbooth.oracle_client import OracleClient, OracleClientError

    try:
        oracle_url = await _resolve_oracle_service_url()
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    try:
        return await OracleClient(oracle_url).call_tool(tool_name, arguments)
    except OracleClientError as e:
        return {"success": False, "error": f"Oracle delegation failed: {e}"}


@tool
async def how_to_join() -> dict[str, Any]:
    """Get DPYC onboarding instructions from the community Oracle.

    Free — no authentication or credits required. Returns step-by-step
    instructions for joining the DPYC Honor Chain, generating a Nostr
    keypair, and connecting to an Operator.
    """
    return await _call_oracle("how_to_join")


@tool
async def get_tax_rate() -> dict[str, Any]:
    """Get the current DPYC certification tax rate from the Oracle.

    Free — no authentication or credits required. Returns the rate
    percent and minimum sats charged by Authorities when certifying
    Operator credit purchases.
    """
    return await _call_oracle("get_tax_rate")


@tool
async def lookup_member(npub: str) -> dict[str, Any]:
    """Look up a DPYC community member by their Nostr npub.

    Free — no authentication or credits required. Returns the member's
    role, status, services, and upstream authority information.

    Args:
        npub: The Nostr public key (bech32 npub format) to look up.
    """
    return await _call_oracle("lookup_member", {"npub": npub})


@tool
async def dpyc_about() -> dict[str, Any]:
    """Describe the DPYC ecosystem via the community Oracle.

    Free — no authentication or credits required. Returns a description
    of the DPYC philosophy, the Honor Chain, and how Tollbooth
    monetization works.
    """
    return await _call_oracle("about")


@tool
async def network_advisory() -> dict[str, Any]:
    """Get active network advisories from the DPYC Oracle.

    Free — no authentication or credits required. Returns any current
    advisories about network status, maintenance windows, or
    ecosystem-wide announcements.
    """
    return await _call_oracle("network_advisory")


def main() -> None:
    """Main entry point for the server."""
    mcp.run()


if __name__ == "__main__":
    main()
