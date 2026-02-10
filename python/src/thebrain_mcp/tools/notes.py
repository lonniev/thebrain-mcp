"""Note operation tools for TheBrain MCP server."""

from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError


async def get_note_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    format: str = "markdown",
) -> dict[str, Any]:
    """Get the note content for a thought.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought
        format: Output format (markdown, html, or text)

    Returns:
        Dictionary with success status and note content
    """
    try:
        note = await api.get_note(brain_id, thought_id, format)

        # Get content based on format
        content = ""
        if format == "markdown":
            content = note.markdown or ""
        elif format == "html":
            content = note.html or ""
        elif format == "text":
            content = note.text or ""
        else:
            content = note.markdown or note.text or ""

        return {
            "success": True,
            "note": {
                "brainId": note.brain_id,
                "thoughtId": note.source_id,
                "format": format,
                "content": content,
                "modificationDateTime": (
                    note.modification_date_time.isoformat()
                    if note.modification_date_time
                    else None
                ),
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def create_or_update_note_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    markdown: str,
) -> dict[str, Any]:
    """Create or update a note with markdown content.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought
        markdown: Markdown content for the note

    Returns:
        Dictionary with success status and message
    """
    try:
        await api.create_or_update_note(brain_id, thought_id, markdown)

        return {
            "success": True,
            "message": f"Note for thought {thought_id} updated successfully",
            "thoughtId": thought_id,
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def append_to_note_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    markdown: str,
) -> dict[str, Any]:
    """Append content to an existing note.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought
        markdown: Markdown content to append

    Returns:
        Dictionary with success status and message
    """
    try:
        await api.append_to_note(brain_id, thought_id, markdown)

        return {
            "success": True,
            "message": f"Content appended to note for thought {thought_id}",
            "thoughtId": thought_id,
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}
