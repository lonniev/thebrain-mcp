"""TheBrain MCP server using FastMCP.

Standard DPYC tools (check_balance, purchase_credits, Secure Courier,
Oracle, pricing) are provided by ``register_standard_tools`` from the
tollbooth-dpyc wheel. Only domain-specific TheBrain tools are defined here.
"""

import logging
import sys
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field
from tollbooth.credential_templates import CredentialTemplate, FieldSpec
from tollbooth.runtime import OperatorRuntime, register_standard_tools
from tollbooth.slug_tools import make_slug_tool
from tollbooth.tool_identity import STANDARD_IDENTITIES, capability_uuid

from thebrain_mcp.api.client import TheBrainAPI
from thebrain_mcp.config import get_settings
from thebrain_mcp.tools import (
    attachments,
    brains,
    links,
    morpher,
    notes,
    orphanage,
    stats,
    thoughts,
    whowhen,
)
from thebrain_mcp.utils.constants import TOOL_REGISTRY
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
        "No environment variables, no local install, just connect.\n\n"
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

_settings_loaded = False


def _ensure_settings_loaded() -> None:
    """Ensure settings are loaded (called at runtime, not import time)."""
    global _settings_loaded
    if not _settings_loaded:
        try:
            get_settings()
            _settings_loaded = True
        except Exception as e:
            print(f"Error: Failed to load settings: {e}", file=sys.stderr)
            sys.exit(1)


# ---------------------------------------------------------------------------
# OperatorRuntime — replaces all DPYC boilerplate
# ---------------------------------------------------------------------------

runtime = OperatorRuntime(
    service_name="Personal Brain",
    tool_registry={**STANDARD_IDENTITIES, **TOOL_REGISTRY},
    operator_credential_template=CredentialTemplate(
        service="thebrain-operator",
        version=1,
        fields={
            "btcpay_host": FieldSpec(
                required=True, sensitive=True,
                description="The URL of your BTCPay Server instance.",
            ),
            "btcpay_api_key": FieldSpec(
                required=True, sensitive=True,
                description="Your BTCPay Server API key.",
            ),
            "btcpay_store_id": FieldSpec(
                required=True, sensitive=True,
                description="Your BTCPay Store ID.",
            ),
        },
        description="BTCPay Lightning payment credentials",
    ),
    patron_credential_template=CredentialTemplate(
        service="thebrain",
        version=3,
        fields={
            "api_key": FieldSpec(
                required=True,
                sensitive=True,
                description=(
                    "Your TheBrain API key. Found at https://bra.in/keys "
                    "or in the TheBrain desktop app under Preferences > API."
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
        description="TheBrain API access credentials",
    ),
    operator_credential_greeting=(
        "Hi \u2014 I\u2019m Personal Brain MCP, a Tollbooth service for AI agent access "
        "to your TheBrain knowledge graph. You (the operator) need to provide "
        "BTCPay credentials."
    ),
    patron_credential_greeting=(
        "Hi \u2014 I\u2019m Personal Brain MCP, a Tollbooth service for AI agent access "
        "to your TheBrain knowledge graph. You (or your AI agent) requested a "
        "credential channel."
    ),
    on_forget=lambda service, npub: _on_credentials_forgotten(service, npub),
)


def _on_credentials_forgotten(service: str, npub: str) -> None:
    """Called by the wheel when forget_credentials succeeds.

    Clears the in-memory session so the patron gate re-checks the vault.
    """
    from thebrain_mcp.vault import clear_session
    clear_session(npub)
    _revoked_npubs.add(npub)
    logger.info("Session cleared for %s (service=%s)", npub[:20], service)

# ---------------------------------------------------------------------------
# Register all standard DPYC tools from the wheel
# ---------------------------------------------------------------------------

register_standard_tools(
    mcp,
    "brain",
    runtime,
    service_name="thebrain-mcp",
    service_version="",
)


# ---------------------------------------------------------------------------
# API client helpers (domain-specific)
# ---------------------------------------------------------------------------


def get_api(npub: str) -> TheBrainAPI:
    """Get API client for the patron identified by npub."""
    _ensure_settings_loaded()
    session = get_session(npub)
    if session:
        return session.api_client
    raise ValueError(_SESSION_GUIDANCE["no_credentials"])


_revoked_npubs: set[str] = set()


# Patron-facing guidance for each lifecycle state.
_SESSION_GUIDANCE: dict[str, str] = {
    "vault_bootstrapping": (
        "The server is establishing its encrypted connection to the "
        "credential vault. This happens once after a cold start and "
        "typically completes within 10-15 seconds. "
        "Action: repeat your request shortly — no re-authentication needed."
    ),
    "operator_not_configured": (
        "The operator's TheBrain API credentials have not been delivered "
        "yet. This is an operator setup step, not a patron action. "
        "Action: contact the operator or try again later."
    ),
    "credentials_revoked": (
        "Your TheBrain credentials were cleared by a previous "
        "forget_credentials call. "
        "Action: call request_patron_credentials to re-onboard your "
        "TheBrain API key and brain ID via Secure Courier."
    ),
    "no_credentials": (
        "No TheBrain credentials are stored for your identity. This is "
        "expected on first use. "
        "Action: call request_patron_credentials with your npub to set "
        "up your TheBrain API key and brain ID via Secure Courier."
    ),
    "api_key_invalid": (
        "Your TheBrain API key was found in the vault but could not be "
        "used — the key may have been revoked or expired. "
        "Action: call request_patron_credentials to deliver fresh "
        "credentials via Secure Courier."
    ),
}


async def _ensure_session(npub: str) -> TheBrainAPI:
    """Restore or require patron session. Returns API client.

    Hard gate: if no patron credentials exist in the vault for this
    npub, raises ValueError directing the caller to the Secure Courier
    onboarding flow.
    """
    # Check if this npub was revoked (forget_credentials was called)
    if npub in _revoked_npubs:
        from thebrain_mcp.vault import clear_session
        clear_session(npub)
        _revoked_npubs.discard(npub)
        raise ValueError(_SESSION_GUIDANCE["credentials_revoked"])

    # Check in-memory session first
    session = get_session(npub)
    if session:
        return session.api_client

    # Try vault restore
    situation = "no_credentials"
    try:
        creds = await runtime.load_patron_session(npub)
    except Exception:
        raise ValueError(_SESSION_GUIDANCE["vault_bootstrapping"])

    if creds and "api_key" in creds:
        try:
            from thebrain_mcp.vault import set_session as _set_session
            session = _set_session(
                npub, creds["api_key"], creds.get("brain_id", ""),
            )
            logger.info("Restored session for %s from vault.", npub[:20])
            return session.api_client
        except Exception:
            situation = "api_key_invalid"
    elif creds is not None:
        # Vault returned something but no api_key — operator issue
        situation = "operator_not_configured"

    guidance = _SESSION_GUIDANCE.get(situation, _SESSION_GUIDANCE["no_credentials"])
    raise ValueError(guidance)


def get_brain_id(brain_id: str | None = None, npub: str = "") -> str:
    """Get brain ID: explicit arg > patron session.

    If brain_id is provided, use it directly. Otherwise look up the
    patron's active brain from their session.
    """
    if brain_id:
        return brain_id

    if npub:
        session = get_session(npub)
        if session and session.active_brain_id:
            return session.active_brain_id

    raise ValueError(
        "brain_id is required. Use set_active_brain or provide brain_id."
    )


# ---------------------------------------------------------------------------
# Domain-specific MCP tools
# ---------------------------------------------------------------------------


# Authentication Diagnostics


# Brain Management Tools


_INTERNAL_BRAIN_PATTERNS = {"credential vault", "mcp vault", "operator vault"}


@tool
@runtime.paid_tool(capability_uuid("list_knowledge_bases"), catch_errors=False)
async def list_brains(npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """List available brains.

    Args:
        npub: Required. Your Nostr public key (npub1...).
    """
    api = await _ensure_session(npub)
    result = await brains.list_brains_tool(api)
    # Filter out internal/operator brains
    if isinstance(result, dict) and "brains" in result:
        result["brains"] = [
            b for b in result["brains"]
            if not any(
                p in (b.get("name", "") or "").lower()
                for p in _INTERNAL_BRAIN_PATTERNS
            )
        ]
    elif isinstance(result, list):
        result = [
            b for b in result
            if not any(
                p in (b.get("name", "") or "").lower()
                for p in _INTERNAL_BRAIN_PATTERNS
            )
        ]
    return result


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_base"), catch_errors=False)
async def get_brain(brain_id: str, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Get details about a specific brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await brains.get_brain_tool(api, brain_id)


@tool
@runtime.paid_tool(capability_uuid("set_active_knowledge_base"), catch_errors=False)
async def set_active_brain(brain_id: str, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Set the active brain for subsequent operations. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain to set as active
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    result = await brains.set_active_brain_tool(api, brain_id)
    if result.get("success"):
        session = get_session(npub)
        if session:
            session.active_brain_id = brain_id
    return result


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_base_stats"), catch_errors=False)
async def get_brain_stats(brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Get statistics about a brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await brains.get_brain_stats_tool(api, get_brain_id(brain_id, npub))


# Thought Operations


@tool
@runtime.paid_tool(capability_uuid("create_knowledge_node"), catch_errors=False)
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
    npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
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
    api = await _ensure_session(npub)
    return await thoughts.create_thought_tool(
        api, get_brain_id(brain_id, npub), name, kind, label,
        foreground_color, background_color, type_id,
        source_thought_id, relation, ac_type,
    )


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_node"), catch_errors=False)
async def get_thought(thought_id: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Get details about a specific thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await thoughts.get_thought_tool(api, get_brain_id(brain_id, npub), thought_id)


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_node_by_name"), catch_errors=False)
async def get_thought_by_name(
    name_exact: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Exact name lookup — returns the first thought matching the name exactly. Requires npub for credit billing.

    Args:
        name_exact: The exact name to match (case-sensitive)
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await thoughts.get_thought_by_name_tool(
        api, get_brain_id(brain_id, npub), name_exact
    )


@tool
@runtime.paid_tool(capability_uuid("update_knowledge_node"), catch_errors=False)
async def update_thought(
    thought_id: str, brain_id: str | None = None, name: str | None = None,
    label: str | None = None, foreground_color: str | None = None,
    background_color: str | None = None, kind: int | None = None,
    ac_type: int | None = None, type_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
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
    api = await _ensure_session(npub)
    return await thoughts.update_thought_tool(
        api, get_brain_id(brain_id, npub), thought_id, name, label,
        foreground_color, background_color, kind, ac_type, type_id,
    )


@tool
@runtime.paid_tool(capability_uuid("delete_knowledge_node"), catch_errors=False)
async def delete_thought(thought_id: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Permanently delete a thought by ID. Cannot be undone. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await thoughts.delete_thought_tool(api, get_brain_id(brain_id, npub), thought_id)


@tool
@runtime.paid_tool(capability_uuid("search_knowledge_nodes"), catch_errors=False)
async def search_thoughts(
    query_text: str, brain_id: str | None = None, max_results: int = 30,
    only_search_thought_names: bool = False, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Full-text search across thought names and content. Requires npub for credit billing.

    Args:
        query_text: Search query text
        brain_id: The ID of the brain (uses active brain if not specified)
        max_results: Maximum number of results
        only_search_thought_names: Only search in thought names (not content)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await thoughts.search_thoughts_tool(
        api, get_brain_id(brain_id, npub), query_text, max_results, only_search_thought_names
    )


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_graph"), catch_errors=False)
async def get_thought_graph(
    thought_id: str, brain_id: str | None = None, include_siblings: bool = False, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Get a thought's full connection graph. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        include_siblings: Include sibling thoughts in the graph
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await thoughts.get_thought_graph_tool(
        api, get_brain_id(brain_id, npub), thought_id, include_siblings
    )


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_graph_paginated"), catch_errors=False)
async def get_thought_graph_paginated(
    thought_id: str, page_size: int = 10, cursor: str | None = None,
    direction: str = "older", relation_filter: str | None = None,
    brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
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
    api = await _ensure_session(npub)
    return await thoughts.get_thought_graph_paginated_tool(
        api, get_brain_id(brain_id, npub), thought_id,
        page_size, cursor, direction, relation_filter,
    )


@tool
@runtime.paid_tool(capability_uuid("list_knowledge_node_types"), catch_errors=False)
async def get_types(brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """List all thought types defined in the brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await thoughts.get_types_tool(api, get_brain_id(brain_id, npub))


@tool
@runtime.paid_tool(capability_uuid("list_knowledge_node_tags"), catch_errors=False)
async def get_tags(brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Get all tags in a brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await thoughts.get_tags_tool(api, get_brain_id(brain_id, npub))


# Link Operations


@tool
@runtime.paid_tool(capability_uuid("create_knowledge_link"), catch_errors=False)
async def create_link(
    thought_id_a: str, thought_id_b: str, relation: int,
    brain_id: str | None = None, name: str | None = None,
    color: str | None = None, thickness: int | None = None,
    direction: int | None = None, type_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
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
    api = await _ensure_session(npub)
    return await links.create_link_tool(
        api, get_brain_id(brain_id, npub), thought_id_a, thought_id_b,
        relation, name, color, thickness, direction, type_id,
    )


@tool
@runtime.paid_tool(capability_uuid("update_knowledge_link"), catch_errors=False)
async def update_link(
    link_id: str, brain_id: str | None = None, name: str | None = None,
    color: str | None = None, thickness: int | None = None,
    direction: int | None = None, relation: int | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
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
    api = await _ensure_session(npub)
    return await links.update_link_tool(
        api, get_brain_id(brain_id, npub), link_id, name, color, thickness, direction, relation
    )


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_link"), catch_errors=False)
async def get_link(link_id: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Get details about a specific link. Requires npub for credit billing.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await links.get_link_tool(api, get_brain_id(brain_id, npub), link_id)


@tool
@runtime.paid_tool(capability_uuid("delete_knowledge_link"), catch_errors=False)
async def delete_link(link_id: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Permanently delete a link by ID. Cannot be undone. Requires npub for credit billing.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await links.delete_link_tool(api, get_brain_id(brain_id, npub), link_id)


# Attachment Operations


@tool
@runtime.paid_tool(capability_uuid("attach_file_to_knowledge_node"), catch_errors=False)
async def add_file_attachment(
    thought_id: str, file_path: str, brain_id: str | None = None,
    file_name: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Add a file attachment to a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        file_path: Path to the file to attach
        brain_id: The ID of the brain (uses active brain if not specified)
        file_name: Name for the attachment (optional)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await attachments.add_file_attachment_tool(
        api, get_brain_id(brain_id, npub), thought_id, file_path, file_name,
        safe_directory=get_settings().attachment_safe_directory,
    )


@tool
@runtime.paid_tool(capability_uuid("attach_url_to_knowledge_node"), catch_errors=False)
async def add_url_attachment(
    thought_id: str, url: str, brain_id: str | None = None, name: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Add a URL attachment to a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        url: The URL to attach
        brain_id: The ID of the brain (uses active brain if not specified)
        name: Name for the URL attachment (auto-fetched if not provided)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await attachments.add_url_attachment_tool(
        api, get_brain_id(brain_id, npub), thought_id, url, name
    )


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_attachment"), catch_errors=False)
async def get_attachment(attachment_id: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Get metadata about an attachment. Requires npub for credit billing.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await attachments.get_attachment_tool(api, get_brain_id(brain_id, npub), attachment_id)


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_attachment_content"), catch_errors=False)
async def get_attachment_content(
    attachment_id: str, brain_id: str | None = None, save_to_path: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Get the binary content of an attachment. Requires npub for credit billing.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
        save_to_path: Optional path to save the file locally
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await attachments.get_attachment_content_tool(
        api, get_brain_id(brain_id, npub), attachment_id, save_to_path,
        safe_directory=get_settings().attachment_safe_directory,
    )


@tool
@runtime.paid_tool(capability_uuid("delete_knowledge_attachment"), catch_errors=False)
async def delete_attachment(attachment_id: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """Delete an attachment. Requires npub for credit billing.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await attachments.delete_attachment_tool(
        api, get_brain_id(brain_id, npub), attachment_id
    )


@tool
@runtime.paid_tool(capability_uuid("list_knowledge_attachments"), catch_errors=False)
async def list_attachments(thought_id: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "") -> dict[str, Any]:
    """List all attachments for a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await attachments.list_attachments_tool(
        api, get_brain_id(brain_id, npub), thought_id
    )


# Note Operations


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_node_note"), catch_errors=False)
async def get_note(
    thought_id: str, brain_id: str | None = None, format: str = "markdown", npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Get the note content for a thought. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        format: Output format (markdown, html, or text)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await notes.get_note_tool(api, get_brain_id(brain_id, npub), thought_id, format)


@tool
@runtime.paid_tool(capability_uuid("upsert_knowledge_node_note"), catch_errors=False)
async def create_or_update_note(
    thought_id: str, markdown: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Create or update a note with markdown content. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        markdown: Markdown content for the note
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await notes.create_or_update_note_tool(
        api, get_brain_id(brain_id, npub), thought_id, markdown
    )


@tool
@runtime.paid_tool(capability_uuid("append_knowledge_node_note"), catch_errors=False)
async def append_to_note(
    thought_id: str, markdown: str, brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Append content to an existing note. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought
        markdown: Markdown content to append
        brain_id: The ID of the brain (uses active brain if not specified)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await notes.append_to_note_tool(
        api, get_brain_id(brain_id, npub), thought_id, markdown
    )


# Advanced Operations


@tool
@runtime.paid_tool(capability_uuid("get_knowledge_base_history"), catch_errors=False)
async def get_modifications(
    brain_id: str | None = None, max_logs: int = 100,
    start_time: str | None = None, end_time: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Get modification history for a brain. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        max_logs: Maximum number of logs to return
        start_time: Start time for logs (ISO format)
        end_time: End time for logs (ISO format)
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await stats.get_modifications_tool(
        api, get_brain_id(brain_id, npub), max_logs, start_time, end_time
    )


# BrainQuery Tool


@tool
@runtime.paid_tool(capability_uuid("query_knowledge_base"), catch_errors=False)
async def brain_query(
    query: str, brain_id: str | None = None, confirm: bool = False, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
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
    from thebrain_mcp.brainquery import execute, parse

    parsed = parse(query)  # raises BrainQuerySyntaxError on bad syntax

    if parsed.action == "match_delete":
        parsed.confirm_delete = confirm

    api = await _ensure_session(npub)
    bid = get_brain_id(brain_id, npub)

    result = await execute(api, bid, parsed)
    return result.to_dict()


# Morpher Tool


@tool
@runtime.paid_tool(capability_uuid("morph_knowledge_node"), catch_errors=False)
async def morph_thought(
    thought_id: str, brain_id: str | None = None,
    new_parent_id: str | None = None, new_type_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Atomically reparent and/or retype a thought in one operation. Requires npub for credit billing.

    Args:
        thought_id: The ID of the thought to morph
        brain_id: The ID of the brain (uses active brain if not specified)
        new_parent_id: ID of the new parent thought
        new_type_id: ID of the new type to assign
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await morpher.morpher_tool(
        api, get_brain_id(brain_id, npub), thought_id, new_parent_id, new_type_id
    )


# Orphanage Tool


@tool
@runtime.paid_tool(capability_uuid("scan_orphan_knowledge_nodes"), catch_errors=False)
async def scan_orphans(
    brain_id: str | None = None, dry_run: bool = True, batch_size: int = 50,
    orphanage_name: str = "Orphanage", npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
) -> dict[str, Any]:
    """Scan for orphaned thoughts with zero connections and optionally rescue them. Requires npub for credit billing.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
        dry_run: If true, only report orphans without rescuing them
        batch_size: Number of orphans to process per batch
        orphanage_name: Name of the orphanage thought to rescue orphans under
        npub: Your DPYC patron Nostr public key (npub1...) for credit attribution.
    """
    api = await _ensure_session(npub)
    return await orphanage.scan_orphans_tool(
        api, get_brain_id(brain_id, npub), dry_run, batch_size, orphanage_name
    )


# WhoWhen Tool


@tool
@runtime.paid_tool(capability_uuid("get_person_event"), catch_errors=False)
async def event_for_person(
    date: str, person: str, event_name: str | None = None, notes: str | None = None,
    brain_id: str | None = None, npub: Annotated[str, Field(description="Required. Your Nostr public key (npub1...) for credit billing.")] = "",
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
    api = await _ensure_session(npub)
    return await whowhen.event_for_person_tool(
        api, get_brain_id(brain_id, npub), date, person, event_name, notes
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the server."""
    mcp.run()


if __name__ == "__main__":
    main()
