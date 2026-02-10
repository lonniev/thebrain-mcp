"""TheBrain MCP server using FastMCP."""

import sys
from typing import Any

from fastmcp import FastMCP

from thebrain_mcp.api.client import TheBrainAPI
from thebrain_mcp.config import get_settings
from thebrain_mcp.tools import attachments, brains, links, notes, stats, thoughts

# Initialize FastMCP server (don't load settings yet - wait until runtime)
mcp = FastMCP("thebrain-mcp")

# Global API client and active brain state (initialized at runtime)
api_client: TheBrainAPI | None = None
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


def get_api() -> TheBrainAPI:
    """Get or create API client."""
    global api_client
    _ensure_settings_loaded()
    if api_client is None:
        settings = get_settings()
        api_client = TheBrainAPI(settings.thebrain_api_key, settings.thebrain_api_url)
    return api_client


def get_brain_id(brain_id: str | None = None) -> str:
    """Get brain ID from argument or active brain."""
    _ensure_settings_loaded()  # Ensure settings loaded to get active_brain_id
    if brain_id:
        return brain_id
    if active_brain_id:
        return active_brain_id
    raise ValueError("Brain ID is required. Use set_active_brain first or provide brainId.")


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


def main() -> None:
    """Main entry point for the server."""
    mcp.run()


if __name__ == "__main__":
    main()
