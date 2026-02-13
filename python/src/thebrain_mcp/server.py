"""TheBrain MCP server using FastMCP."""

import sys
import time
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from thebrain_mcp.api.client import TheBrainAPI
from thebrain_mcp.config import get_settings
from thebrain_mcp.brainquery import BrainQuerySyntaxError, execute, parse
from thebrain_mcp.tools import attachments, brains, links, notes, stats, thoughts
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
mcp = FastMCP("thebrain-mcp")

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
    return await brains.get_brain_tool(get_api(), brain_id)


@mcp.tool()
async def set_active_brain(brain_id: str) -> dict[str, Any]:
    """Set the active brain for subsequent operations.

    Args:
        brain_id: The ID of the brain to set as active
    """
    global active_brain_id
    result = await brains.set_active_brain_tool(get_api(), brain_id)
    if result.get("success"):
        user_id = _get_current_user_id()
        if user_id:
            session = get_session(user_id)
            if session:
                session.active_brain_id = brain_id
                return result
        active_brain_id = brain_id
    return result


@mcp.tool()
async def get_brain_stats(brain_id: str | None = None) -> dict[str, Any]:
    """Get statistics about a brain.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await brains.get_brain_stats_tool(get_api(), get_brain_id(brain_id))


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
    """Create a new thought with optional visual properties.

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
    return await thoughts.create_thought_tool(
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
    )


@mcp.tool()
async def get_thought(thought_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Get details about a specific thought.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await thoughts.get_thought_tool(get_api(), get_brain_id(brain_id), thought_id)


@mcp.tool()
async def get_thought_by_name(
    name_exact: str, brain_id: str | None = None
) -> dict[str, Any]:
    """Find a thought by its exact name.

    Returns the first thought matching the name exactly. Depends on TheBrain's
    cloud search index — may return not-found for thoughts that exist but
    aren't indexed. Use get_thought_graph for reliable traversal.

    Args:
        name_exact: The exact name to match (case-sensitive)
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await thoughts.get_thought_by_name_tool(
        get_api(), get_brain_id(brain_id), name_exact
    )


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
    """Update a thought including its visual properties.

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
    return await thoughts.update_thought_tool(
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
    )


@mcp.tool()
async def delete_thought(thought_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Delete a thought.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await thoughts.delete_thought_tool(get_api(), get_brain_id(brain_id), thought_id)


@mcp.tool()
async def search_thoughts(
    query_text: str,
    brain_id: str | None = None,
    max_results: int = 30,
    only_search_thought_names: bool = False,
) -> dict[str, Any]:
    """Search for thoughts in a brain.

    Note: Search depends on TheBrain's cloud index, which may not cover all
    thoughts. For reliable lookup, use get_thought_graph to traverse connections,
    or get_thought_by_name for exact name matches on indexed thoughts.

    Args:
        query_text: Search query text
        brain_id: The ID of the brain (uses active brain if not specified)
        max_results: Maximum number of results
        only_search_thought_names: Only search in thought names (not content)
    """
    return await thoughts.search_thoughts_tool(
        get_api(), get_brain_id(brain_id), query_text, max_results, only_search_thought_names
    )


@mcp.tool()
async def get_thought_graph(
    thought_id: str, brain_id: str | None = None, include_siblings: bool = False
) -> dict[str, Any]:
    """Get a thought with all its connections and attachments.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
        include_siblings: Include sibling thoughts in the graph
    """
    return await thoughts.get_thought_graph_tool(
        get_api(), get_brain_id(brain_id), thought_id, include_siblings
    )


@mcp.tool()
async def get_thought_graph_paginated(
    thought_id: str,
    page_size: int = 10,
    cursor: str | None = None,
    direction: str = "older",
    relation_filter: str | None = None,
    brain_id: str | None = None,
) -> dict[str, Any]:
    """Get a thought's connections with cursor-based pagination.

    Fetches the full graph, sorts by modification date, and returns a page.
    Use this instead of get_thought_graph when a thought has many connections.

    Args:
        thought_id: The ID of the thought
        page_size: Number of results per page (default 10)
        cursor: Pagination cursor from a previous response (omit for first page)
        direction: "older" (newest first, default) or "newer" (oldest first)
        relation_filter: Filter by relation: "child", "parent", "jump", "sibling", or omit for all
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await thoughts.get_thought_graph_paginated_tool(
        get_api(), get_brain_id(brain_id), thought_id,
        page_size, cursor, direction, relation_filter,
    )


@mcp.tool()
async def get_types(brain_id: str | None = None) -> dict[str, Any]:
    """Get all thought types in a brain.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await thoughts.get_types_tool(get_api(), get_brain_id(brain_id))


@mcp.tool()
async def get_tags(brain_id: str | None = None) -> dict[str, Any]:
    """Get all tags in a brain.

    Args:
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await thoughts.get_tags_tool(get_api(), get_brain_id(brain_id))


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
    """Create a link between two thoughts with visual properties.

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
    return await links.create_link_tool(
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
    )


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
    return await links.update_link_tool(
        get_api(), get_brain_id(brain_id), link_id, name, color, thickness, direction, relation
    )


@mcp.tool()
async def get_link(link_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Get details about a specific link.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await links.get_link_tool(get_api(), get_brain_id(brain_id), link_id)


@mcp.tool()
async def delete_link(link_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Delete a link.

    Args:
        link_id: The ID of the link
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await links.delete_link_tool(get_api(), get_brain_id(brain_id), link_id)


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
    return await attachments.add_file_attachment_tool(
        get_api(), get_brain_id(brain_id), thought_id, file_path, file_name
    )


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
    return await attachments.add_url_attachment_tool(
        get_api(), get_brain_id(brain_id), thought_id, url, name
    )


@mcp.tool()
async def get_attachment(attachment_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Get metadata about an attachment.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await attachments.get_attachment_tool(get_api(), get_brain_id(brain_id), attachment_id)


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
    return await attachments.get_attachment_content_tool(
        get_api(), get_brain_id(brain_id), attachment_id, save_to_path
    )


@mcp.tool()
async def delete_attachment(attachment_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """Delete an attachment.

    Args:
        attachment_id: The ID of the attachment
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await attachments.delete_attachment_tool(
        get_api(), get_brain_id(brain_id), attachment_id
    )


@mcp.tool()
async def list_attachments(thought_id: str, brain_id: str | None = None) -> dict[str, Any]:
    """List all attachments for a thought.

    Args:
        thought_id: The ID of the thought
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    return await attachments.list_attachments_tool(
        get_api(), get_brain_id(brain_id), thought_id
    )


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
    return await notes.get_note_tool(get_api(), get_brain_id(brain_id), thought_id, format)


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
    return await notes.create_or_update_note_tool(
        get_api(), get_brain_id(brain_id), thought_id, markdown
    )


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
    return await notes.append_to_note_tool(
        get_api(), get_brain_id(brain_id), thought_id, markdown
    )


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
    return await stats.get_modifications_tool(
        get_api(), get_brain_id(brain_id), max_logs, start_time, end_time
    )


# BrainQuery Tool


@mcp.tool()
async def brain_query(
    query: str,
    brain_id: str | None = None,
) -> dict[str, Any]:
    """Execute a BrainQuery (Cypher subset) against TheBrain.

    Supports MATCH for searching and CREATE for adding thoughts in context.
    Uses name-first resolution with lazy type filtering.

    Examples:
        Find by name:    MATCH (n {name: "Claude Thoughts"}) RETURN n
        Find by type:    MATCH (p:Person {name: "Alice"}) RETURN p
        Get children:    MATCH (n {name: "Projects"})-[:CHILD]->(m) RETURN m
        Create child:    MATCH (p {name: "Ideas"}) CREATE (p)-[:CHILD]->(n {name: "New Idea"})
        Link existing:   MATCH (a {name: "A"}), (b {name: "B"}) CREATE (a)-[:JUMP]->(b)
        Substring search: MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n

    Args:
        query: A BrainQuery string (Cypher subset). See examples above.
        brain_id: The ID of the brain (uses active brain if not specified)
    """
    try:
        parsed = parse(query)
    except BrainQuerySyntaxError as e:
        return {"success": False, "error": str(e)}

    api = get_api()
    bid = get_brain_id(brain_id)

    result = await execute(api, bid, parsed)
    return result.to_dict()


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

    return {
        "success": True,
        "message": "Credentials registered and session activated.",
        "userId": user_id,
        "brainId": brain_id,
        "vaultThoughtId": thought_id,
    }


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


_VAULT_HOME_THOUGHT_ID = "529bd3cb-59cb-42b9-b360-f0963f1b1c0f"


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


def main() -> None:
    """Main entry point for the server."""
    mcp.run()


if __name__ == "__main__":
    main()
