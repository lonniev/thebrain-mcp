"""TheBrain MCP server using FastMCP.

Standard DPYC tools (check_balance, purchase_credits, Secure Courier,
Oracle, pricing) are provided by ``register_standard_tools`` from the
tollbooth-dpyc wheel. Only domain-specific TheBrain tools are defined here.
"""

import logging
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from tollbooth.credential_templates import CredentialTemplate, FieldSpec
from tollbooth.runtime import OperatorRuntime, register_standard_tools, resolve_npub
from tollbooth.slug_tools import make_slug_tool

from thebrain_mcp.api.client import TheBrainAPI
from thebrain_mcp.config import get_settings
from thebrain_mcp.tools import (
    attachments,
    brains,
    credits,
    links,
    morpher,
    notes,
    orphanage,
    stats,
    thoughts,
    whowhen,
)
from thebrain_mcp.utils.constants import TOOL_COSTS
from thebrain_mcp.vault import (
    get_session,
)

logger = logging.getLogger(__name__)

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
        "   - Get your **patron npub** from the dpyc-oracle's how_to_join() tool — "
        "this is the npub you registered as a DPYC Citizen, your identity for credit operations\n"
        "   - Call `request_credential_channel(recipient_npub=<patron_npub>)` to receive a welcome DM\n"
        "   - Reply via your Nostr client with your TheBrain API key and brain ID in JSON\n"
        "   - Call `receive_credentials(sender_npub=<patron_npub>)` to vault your credentials\n"
        "3. Returning users: call `receive_credentials(sender_npub=<patron_npub>)` — vault-first "
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
        "1. brain_query (BQL) — primary tool for pattern-based CRUD.\n"
        "2. get_thought_by_name — fast exact-name lookup\n"
        "3. search_thoughts — full-text keyword search\n"
        "4. get_thought_graph / get_thought_graph_paginated — traverse connections\n"
        "5. create_or_update_note, append_to_note, list_attachments — note/attachment ops\n"
        "6. create_thought, create_link, etc. — direct CRUD\n\n"
        "## Full UUIDs Required\n\n"
        "TheBrain API requires full UUIDs (36 characters) for all thought and link IDs.\n\n"
        "## Low-Balance Warning\n\n"
        "Any paid tool response may include a `low_balance_warning` key when the user's "
        "credit balance is running low. Proactively inform the user when you see this."
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
    """Extract FastMCP Cloud user ID from request headers."""
    try:
        headers = get_http_headers(include_all=True)
        return headers.get("fastmcp-cloud-user")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OperatorRuntime — replaces all DPYC boilerplate
# ---------------------------------------------------------------------------

runtime = OperatorRuntime(
    service_name="Personal Brain",
    tool_costs=TOOL_COSTS,
    credential_service="thebrain",
    credential_template=CredentialTemplate(
        service="thebrain",
        version=2,
        fields={
            "api_key": FieldSpec(
                required=True,
                sensitive=True,
                description=(
                    "Your TheBrain API key. Found in TheBrain desktop app "
                    "under Preferences > API."
                ),
            ),
            "brain_id": FieldSpec(
                required=True,
                sensitive=False,
                description=(
                    "The ID of the brain to connect to. Found in TheBrain "
                    "under Brain > Properties."
                ),
            ),
        },
        description="TheBrain API key and brain ID for personal knowledge graph access",
    ),
    credential_greeting=(
        "Hi \u2014 I\u2019m Personal Brain MCP, a Tollbooth service for AI agent access "
        "to your TheBrain knowledge graph. You (or your AI agent) requested a "
        "credential channel."
    ),
)

# ---------------------------------------------------------------------------
# Register all standard DPYC tools from the wheel
# ---------------------------------------------------------------------------

register_standard_tools(
    mcp,
    "brain",
    runtime,
    settings_fn=get_settings,
    service_name="thebrain-mcp",
    service_version="",
)


# ---------------------------------------------------------------------------
# API client helpers (domain-specific)
# ---------------------------------------------------------------------------


def _get_operator_api() -> TheBrainAPI:
    """Get or create the operator's API client (singleton)."""
    global _operator_api_client
    _ensure_settings_loaded()
    if _operator_api_client is None:
        settings = get_settings()
        _operator_api_client = TheBrainAPI(settings.thebrain_api_key, settings.thebrain_api_url)
    return _operator_api_client


def get_api() -> TheBrainAPI:
    """Get API client — per-user if session active, operator's for STDIO mode."""
    _ensure_settings_loaded()

    user_id = _get_current_user_id()
    if user_id:
        session = get_session(user_id)
        if session:
            return session.api_client
        raise ValueError(
            "No active session. Follow the Secure Courier onboarding flow "
            "(see session_status) or call receive_credentials(sender_npub=<npub>) "
            "if you've already delivered credentials."
        )

    return _get_operator_api()


def get_brain_id(brain_id: str | None = None) -> str:
    """Get brain ID: explicit arg > per-user session > operator default (STDIO only)."""
    _ensure_settings_loaded()
    if brain_id:
        return brain_id

    user_id = _get_current_user_id()
    if user_id:
        session = get_session(user_id)
        if session and session.active_brain_id:
            return session.active_brain_id

    if active_brain_id:
        return active_brain_id
    raise ValueError("Brain ID is required. Use set_active_brain first or provide brainId.")


# ---------------------------------------------------------------------------
# Low-balance warning helper (uses runtime)
# ---------------------------------------------------------------------------


async def _with_warning(result: dict[str, Any], npub: str = "") -> dict[str, Any]:
    """Attach a low-balance warning to a paid tool result if balance is low."""
    try:
        user_id = resolve_npub(npub)
        cache = await runtime.ledger_cache()
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


# ---------------------------------------------------------------------------
# Domain-specific MCP tools
# ---------------------------------------------------------------------------


# Authentication Diagnostics


@tool
async def whoami() -> dict[str, Any]:
    """Return the authenticated user's identity and token claims."""
    result: dict[str, Any] = {}
    headers = get_http_headers(include_all=True)
    result["fastmcp_cloud"] = {
        k: v for k, v in headers.items() if k.startswith("fastmcp-")
    } or None
    user_id = _get_current_user_id()
    if user_id:
        result["dpyc_session"] = {"active": False, "npub": None, "note": "Pass npub explicitly to credit tools."}
    return result


# Brain Management Tools


@tool
async def list_brains() -> dict[str, Any]:
    """List all available brains for the user."""
    return await brains.list_brains_tool(get_api())


@tool
async def get_brain(brain_id: str, npub: str = "") -> dict[str, Any]:
    """Get details about a specific brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_brain", npub)
    if err:
        return err
    try:
        return await _with_warning(await brains.get_brain_tool(get_api(), brain_id))
    except Exception:
        await runtime.rollback_debit("get_brain", npub)
        raise


@tool
async def set_active_brain(brain_id: str, npub: str = "") -> dict[str, Any]:
    """Set the active brain for subsequent operations. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain to set as active
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("set_active_brain", npub)
    if err:
        return err
    global active_brain_id
    try:
        result = await brains.set_active_brain_tool(get_api(), brain_id)
    except Exception:
        await runtime.rollback_debit("set_active_brain", npub)
        raise
    if result.get("success"):
        user_id = _get_current_user_id()
        if user_id:
            session = get_session(user_id)
            if session:
                session.active_brain_id = brain_id
                return await _with_warning(result, npub=npub)
        active_brain_id = brain_id
    return await _with_warning(result, npub=npub)


@tool
async def get_brain_stats(brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Get statistics about a brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_brain_stats", npub)
    if err:
        return err
    try:
        return await _with_warning(await brains.get_brain_stats_tool(get_api(), get_brain_id(brain_id)))
    except Exception:
        await runtime.rollback_debit("get_brain_stats", npub)
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
    npub: str = "",
) -> dict[str, Any]:
    """Create a new thought with optional type, color, label, and parent link. Requires npub for credit billing.

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
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("create_thought", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.create_thought_tool(
            get_api(), get_brain_id(brain_id), name, kind, label,
            foreground_color, background_color, type_id,
            source_thought_id, relation, ac_type,
        ))
    except Exception:
        await runtime.rollback_debit("create_thought", npub)
        raise


@tool
async def get_thought(thought_id: str, brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Get details about a specific thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_thought", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.get_thought_tool(get_api(), get_brain_id(brain_id), thought_id))
    except Exception:
        await runtime.rollback_debit("get_thought", npub)
        raise


@tool
async def get_thought_by_name(
    name_exact: str, brain_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Exact name lookup — returns the first thought matching the name exactly. Requires npub for credit billing.

    Args:
        name_exact: The exact name to match (case-sensitive)
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_thought_by_name", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.get_thought_by_name_tool(
            get_api(), get_brain_id(brain_id), name_exact
        ))
    except Exception:
        await runtime.rollback_debit("get_thought_by_name", npub)
        raise


@tool
async def update_thought(
    thought_id: str, brain_id: str | None = None, name: str | None = None,
    label: str | None = None, foreground_color: str | None = None,
    background_color: str | None = None, kind: int | None = None,
    ac_type: int | None = None, type_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Update a thought's properties. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought to update
        brain_id: The ID of the brain (uses active brain if not specified)
        name: New name
        label: New label
        foreground_color: New foreground color in hex
        background_color: New background color in hex
        kind: New kind
        ac_type: New access type
        type_id: New type ID
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("update_thought", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.update_thought_tool(
            get_api(), get_brain_id(brain_id), thought_id, name, label,
            foreground_color, background_color, kind, ac_type, type_id,
        ))
    except Exception:
        await runtime.rollback_debit("update_thought", npub)
        raise


@tool
async def delete_thought(thought_id: str, brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Permanently delete a thought by ID. Cannot be undone. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("delete_thought", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.delete_thought_tool(get_api(), get_brain_id(brain_id), thought_id))
    except Exception:
        await runtime.rollback_debit("delete_thought", npub)
        raise


@tool
async def search_thoughts(
    query_text: str, brain_id: str | None = None, max_results: int = 30,
    only_search_thought_names: bool = False, npub: str = "",
) -> dict[str, Any]:
    """Full-text search across thought names and content. Requires npub for credit billing.

    Args:
        query_text: Search query text
        brain_id: The ID of the brain (uses active brain if not specified)
        max_results: Maximum number of results
        only_search_thought_names: Only search in thought names (not content)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("search_thoughts", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.search_thoughts_tool(
            get_api(), get_brain_id(brain_id), query_text, max_results, only_search_thought_names
        ))
    except Exception:
        await runtime.rollback_debit("search_thoughts", npub)
        raise


@tool
async def get_thought_graph(
    thought_id: str, brain_id: str | None = None, include_siblings: bool = False, npub: str = "",
) -> dict[str, Any]:
    """Get a thought's full connection graph. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        include_siblings: Include sibling thoughts in the graph
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_thought_graph", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.get_thought_graph_tool(
            get_api(), get_brain_id(brain_id), thought_id, include_siblings
        ))
    except Exception:
        await runtime.rollback_debit("get_thought_graph", npub)
        raise


@tool
async def get_thought_graph_paginated(
    thought_id: str, page_size: int = 10, cursor: str | None = None,
    direction: str = "older", relation_filter: str | None = None,
    brain_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Cursor-based paginated traversal of a thought's connections. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        page_size: Number of results per page (default 10)
        cursor: Pagination cursor from a previous response
        direction: "older" (newest first) or "newer" (oldest first)
        relation_filter: Filter by relation: "child", "parent", "jump", "sibling"
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_thought_graph_paginated", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.get_thought_graph_paginated_tool(
            get_api(), get_brain_id(brain_id), thought_id,
            page_size, cursor, direction, relation_filter,
        ))
    except Exception:
        await runtime.rollback_debit("get_thought_graph_paginated", npub)
        raise


@tool
async def get_types(brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """List all thought types defined in the brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_types", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.get_types_tool(get_api(), get_brain_id(brain_id)))
    except Exception:
        await runtime.rollback_debit("get_types", npub)
        raise


@tool
async def get_tags(brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Get all tags in a brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_tags", npub)
    if err:
        return err
    try:
        return await _with_warning(await thoughts.get_tags_tool(get_api(), get_brain_id(brain_id)))
    except Exception:
        await runtime.rollback_debit("get_tags", npub)
        raise


# Link Operations


@tool
async def create_link(
    thought_id_a: str, thought_id_b: str, relation: int,
    brain_id: str | None = None, name: str | None = None,
    color: str | None = None, thickness: int | None = None,
    direction: int | None = None, type_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Create a relationship between two thoughts by ID. Requires npub for credit billing.

    Args:
        thought_id_a: ID of the first thought
        thought_id_b: ID of the second thought
        relation: Relation type (1=Child, 2=Parent, 3=Jump, 4=Sibling)
        brain_id: The ID of the brain (uses active brain if not specified)
        name: Label for the link
        color: Link color in hex format
        thickness: Link thickness (1-10)
        direction: Direction flags
        type_id: ID of link type
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("create_link", npub)
    if err:
        return err
    try:
        return await _with_warning(await links.create_link_tool(
            get_api(), get_brain_id(brain_id), thought_id_a, thought_id_b,
            relation, name, color, thickness, direction, type_id,
        ))
    except Exception:
        await runtime.rollback_debit("create_link", npub)
        raise


@tool
async def update_link(
    link_id: str, brain_id: str | None = None, name: str | None = None,
    color: str | None = None, thickness: int | None = None,
    direction: int | None = None, relation: int | None = None, npub: str = "",
) -> dict[str, Any]:
    """Update link properties. Requires npub for credit billing.

    Args:
        link_id: The ID of the link to update
        brain_id: The ID of the brain (uses active brain if not specified)
        name: New label
        color: New color in hex
        thickness: New thickness (1-10)
        direction: New direction flags
        relation: New relation type
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("update_link", npub)
    if err:
        return err
    try:
        return await _with_warning(await links.update_link_tool(
            get_api(), get_brain_id(brain_id), link_id, name, color, thickness, direction, relation
        ))
    except Exception:
        await runtime.rollback_debit("update_link", npub)
        raise


@tool
async def get_link(link_id: str, brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Get details about a specific link. Requires npub for credit billing.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_link", npub)
    if err:
        return err
    try:
        return await _with_warning(await links.get_link_tool(get_api(), get_brain_id(brain_id), link_id))
    except Exception:
        await runtime.rollback_debit("get_link", npub)
        raise


@tool
async def delete_link(link_id: str, brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Permanently delete a link by ID. Cannot be undone. Requires npub for credit billing.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("delete_link", npub)
    if err:
        return err
    try:
        return await _with_warning(await links.delete_link_tool(get_api(), get_brain_id(brain_id), link_id))
    except Exception:
        await runtime.rollback_debit("delete_link", npub)
        raise


# Attachment Operations


@tool
async def add_file_attachment(
    thought_id: str, file_path: str, brain_id: str | None = None,
    file_name: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Add a file attachment to a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        file_path: Path to the file to attach
        brain_id: The ID of the brain (uses active brain if not specified)
        file_name: Name for the attachment (optional)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("add_file_attachment", npub)
    if err:
        return err
    try:
        return await _with_warning(await attachments.add_file_attachment_tool(
            get_api(), get_brain_id(brain_id), thought_id, file_path, file_name,
            safe_directory=get_settings().attachment_safe_directory,
        ))
    except Exception:
        await runtime.rollback_debit("add_file_attachment", npub)
        raise


@tool
async def add_url_attachment(
    thought_id: str, url: str, brain_id: str | None = None, name: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Add a URL attachment to a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        url: The URL to attach
        brain_id: The ID of the brain (uses active brain if not specified)
        name: Name for the URL attachment (auto-fetched if not provided)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("add_url_attachment", npub)
    if err:
        return err
    try:
        return await _with_warning(await attachments.add_url_attachment_tool(
            get_api(), get_brain_id(brain_id), thought_id, url, name
        ))
    except Exception:
        await runtime.rollback_debit("add_url_attachment", npub)
        raise


@tool
async def get_attachment(attachment_id: str, brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Get metadata about an attachment. Requires npub for credit billing.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_attachment", npub)
    if err:
        return err
    try:
        return await _with_warning(await attachments.get_attachment_tool(get_api(), get_brain_id(brain_id), attachment_id))
    except Exception:
        await runtime.rollback_debit("get_attachment", npub)
        raise


@tool
async def get_attachment_content(
    attachment_id: str, brain_id: str | None = None, save_to_path: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Get the binary content of an attachment. Requires npub for credit billing.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
        save_to_path: Optional path to save the file locally
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_attachment_content", npub)
    if err:
        return err
    try:
        return await _with_warning(await attachments.get_attachment_content_tool(
            get_api(), get_brain_id(brain_id), attachment_id, save_to_path,
            safe_directory=get_settings().attachment_safe_directory,
        ))
    except Exception:
        await runtime.rollback_debit("get_attachment_content", npub)
        raise


@tool
async def delete_attachment(attachment_id: str, brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """Delete an attachment. Requires npub for credit billing.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("delete_attachment", npub)
    if err:
        return err
    try:
        return await _with_warning(await attachments.delete_attachment_tool(
            get_api(), get_brain_id(brain_id), attachment_id
        ))
    except Exception:
        await runtime.rollback_debit("delete_attachment", npub)
        raise


@tool
async def list_attachments(thought_id: str, brain_id: str | None = None, npub: str = "") -> dict[str, Any]:
    """List all attachments for a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("list_attachments", npub)
    if err:
        return err
    try:
        return await _with_warning(await attachments.list_attachments_tool(
            get_api(), get_brain_id(brain_id), thought_id
        ))
    except Exception:
        await runtime.rollback_debit("list_attachments", npub)
        raise


# Note Operations


@tool
async def get_note(
    thought_id: str, brain_id: str | None = None, format: str = "markdown", npub: str = "",
) -> dict[str, Any]:
    """Get the note content for a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        format: Output format (markdown, html, or text)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_note", npub)
    if err:
        return err
    try:
        return await _with_warning(await notes.get_note_tool(get_api(), get_brain_id(brain_id), thought_id, format))
    except Exception:
        await runtime.rollback_debit("get_note", npub)
        raise


@tool
async def create_or_update_note(
    thought_id: str, markdown: str, brain_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Create or update a note with markdown content. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        markdown: Markdown content for the note
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("create_or_update_note", npub)
    if err:
        return err
    try:
        return await _with_warning(await notes.create_or_update_note_tool(
            get_api(), get_brain_id(brain_id), thought_id, markdown
        ))
    except Exception:
        await runtime.rollback_debit("create_or_update_note", npub)
        raise


@tool
async def append_to_note(
    thought_id: str, markdown: str, brain_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Append content to an existing note. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        markdown: Markdown content to append
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("append_to_note", npub)
    if err:
        return err
    try:
        return await _with_warning(await notes.append_to_note_tool(
            get_api(), get_brain_id(brain_id), thought_id, markdown
        ))
    except Exception:
        await runtime.rollback_debit("append_to_note", npub)
        raise


# Advanced Operations


@tool
async def get_modifications(
    brain_id: str | None = None, max_logs: int = 100,
    start_time: str | None = None, end_time: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Get modification history for a brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        max_logs: Maximum number of logs to return
        start_time: Start time for logs (ISO format)
        end_time: End time for logs (ISO format)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("get_modifications", npub)
    if err:
        return err
    try:
        return await _with_warning(await stats.get_modifications_tool(
            get_api(), get_brain_id(brain_id), max_logs, start_time, end_time
        ))
    except Exception:
        await runtime.rollback_debit("get_modifications", npub)
        raise


# BrainQuery Tool


@tool
async def brain_query(
    query: str, brain_id: str | None = None, confirm: bool = False, npub: str = "",
) -> dict[str, Any]:
    """Primary tool for pattern-based operations on TheBrain. Requires npub for credit billing.

    Accepts BrainQuery (BQL) -- a Cypher subset supporting MATCH, WHERE, CREATE,
    SET, MERGE, DELETE, and RETURN.

    Args:
        query: A BrainQuery string (Cypher subset).
        brain_id: The ID of the brain (uses active brain if not specified)
        confirm: Set to true to confirm and execute a DELETE operation.
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("brain_query", npub)
    if err:
        return err

    from thebrain_mcp.brainquery import BrainQuerySyntaxError, execute, parse

    try:
        parsed = parse(query)
    except BrainQuerySyntaxError as e:
        await runtime.rollback_debit("brain_query", npub)
        return {"success": False, "error": str(e)}

    if parsed.action == "match_delete":
        parsed.confirm_delete = confirm

    api = get_api()
    bid = get_brain_id(brain_id)

    try:
        result = await execute(api, bid, parsed)
        return await _with_warning(result.to_dict())
    except Exception:
        await runtime.rollback_debit("brain_query", npub)
        raise


# Morpher Tool


@tool
async def morph_thought(
    thought_id: str, brain_id: str | None = None,
    new_parent_id: str | None = None, new_type_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Atomically reparent and/or retype a thought in one operation. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought to morph
        brain_id: The ID of the brain (uses active brain if not specified)
        new_parent_id: ID of the new parent thought
        new_type_id: ID of the new type to assign
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("morph_thought", npub)
    if err:
        return err
    try:
        return await _with_warning(await morpher.morpher_tool(
            get_api(), get_brain_id(brain_id), thought_id, new_parent_id, new_type_id
        ))
    except Exception:
        await runtime.rollback_debit("morph_thought", npub)
        raise


# Orphanage Tool


@tool
async def scan_orphans(
    brain_id: str | None = None, dry_run: bool = True, batch_size: int = 50,
    orphanage_name: str = "Orphanage", npub: str = "",
) -> dict[str, Any]:
    """Scan for orphaned thoughts with zero connections and optionally rescue them. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        dry_run: If true, only report orphans without rescuing them
        batch_size: Number of orphans to process per batch
        orphanage_name: Name of the orphanage thought to rescue orphans under
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("scan_orphans", npub)
    if err:
        return err
    try:
        return await _with_warning(await orphanage.scan_orphans_tool(
            get_api(), get_brain_id(brain_id), dry_run, batch_size, orphanage_name
        ))
    except Exception:
        await runtime.rollback_debit("scan_orphans", npub)
        raise


# WhoWhen Tool


@tool
async def event_for_person(
    date: str, person: str, event_name: str | None = None, notes: str | None = None,
    brain_id: str | None = None, npub: str = "",
) -> dict[str, Any]:
    """Create an Event+Person+Day in one action. Requires npub for credit billing.

    Args:
        date: Flexible date string (ISO, natural language, relative)
        person: Full name or thought ID (UUID)
        event_name: Custom event name (auto-generated if omitted)
        notes: Optional markdown note for the Event
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    err = await runtime.debit_or_error("event_for_person", npub)
    if err:
        return err
    try:
        return await _with_warning(await whowhen.event_for_person_tool(
            get_api(), get_brain_id(brain_id), date, person, event_name, notes
        ))
    except Exception:
        await runtime.rollback_debit("event_for_person", npub)
        raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the server."""
    mcp.run()


if __name__ == "__main__":
    main()
