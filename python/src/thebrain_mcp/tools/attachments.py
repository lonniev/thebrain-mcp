"""Attachment operation tools for TheBrain MCP server."""

from pathlib import Path
from typing import Any

from thebrain_mcp.api.client import TheBrainAPI, TheBrainAPIError
from thebrain_mcp.utils.formatters import get_attachment_type_name, get_source_type_name


async def add_file_attachment_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    file_path: str,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Add a file attachment (including images) to a thought.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought
        file_path: Path to the file to attach
        file_name: Name for the attachment (optional, uses filename if not provided)

    Returns:
        Dictionary with success status and attachment details
    """
    try:
        # Verify file exists
        path = Path(file_path)
        if not path.exists():
            raise TheBrainAPIError(f"File not found: {file_path}")

        actual_file_name = file_name or path.name
        file_size = path.stat().st_size

        await api.add_file_attachment(brain_id, thought_id, file_path, file_name)

        return {
            "success": True,
            "message": f"File '{actual_file_name}' attached to thought {thought_id}",
            "attachment": {
                "fileName": actual_file_name,
                "filePath": file_path,
                "size": file_size,
                "thoughtId": thought_id,
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def add_url_attachment_tool(
    api: TheBrainAPI,
    brain_id: str,
    thought_id: str,
    url: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Add a URL attachment to a thought.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought
        url: The URL to attach
        name: Name for the URL attachment (auto-fetched from page title if not provided)

    Returns:
        Dictionary with success status and attachment details
    """
    try:
        await api.add_url_attachment(brain_id, thought_id, url, name)

        return {
            "success": True,
            "message": f"URL '{url}' attached to thought {thought_id}",
            "attachment": {
                "url": url,
                "name": name or "Auto-generated from page title",
                "thoughtId": thought_id,
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_attachment_tool(
    api: TheBrainAPI, brain_id: str, attachment_id: str
) -> dict[str, Any]:
    """Get metadata about an attachment.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        attachment_id: The ID of the attachment

    Returns:
        Dictionary with success status and attachment metadata
    """
    try:
        attachment = await api.get_attachment(brain_id, attachment_id)

        return {
            "success": True,
            "attachment": {
                "id": attachment.id,
                "brainId": attachment.brain_id,
                "sourceId": attachment.source_id,
                "sourceType": attachment.source_type,
                "sourceTypeName": get_source_type_name(attachment.source_type),
                "name": attachment.name,
                "type": attachment.type,
                "typeName": get_attachment_type_name(attachment.type),
                "location": attachment.location,
                "dataLength": attachment.data_length,
                "position": attachment.position,
                "isNotes": attachment.is_notes,
                "creationDateTime": (
                    attachment.creation_date_time.isoformat()
                    if attachment.creation_date_time
                    else None
                ),
                "modificationDateTime": (
                    attachment.modification_date_time.isoformat()
                    if attachment.modification_date_time
                    else None
                ),
                "fileModificationDateTime": (
                    attachment.file_modification_date_time.isoformat()
                    if attachment.file_modification_date_time
                    else None
                ),
            },
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def get_attachment_content_tool(
    api: TheBrainAPI,
    brain_id: str,
    attachment_id: str,
    save_to_path: str | None = None,
) -> dict[str, Any]:
    """Get the binary content of an attachment (e.g., download an image).

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        attachment_id: The ID of the attachment
        save_to_path: Optional path to save the file locally

    Returns:
        Dictionary with success status and content information
    """
    try:
        content = await api.get_attachment_content(brain_id, attachment_id)

        if save_to_path:
            # Save the content to a file
            path = Path(save_to_path)
            path.write_bytes(content)

            return {
                "success": True,
                "message": f"Attachment content saved to {save_to_path}",
                "savedTo": save_to_path,
                "size": len(content),
            }
        else:
            # Return content info without the actual binary data
            return {
                "success": True,
                "message": "Attachment content retrieved",
                "size": len(content),
                "hint": "Use saveToPath parameter to save the content to a file",
            }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def delete_attachment_tool(
    api: TheBrainAPI, brain_id: str, attachment_id: str
) -> dict[str, Any]:
    """Delete an attachment.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        attachment_id: The ID of the attachment

    Returns:
        Dictionary with success status and message
    """
    try:
        await api.delete_attachment(brain_id, attachment_id)
        return {
            "success": True,
            "message": f"Attachment {attachment_id} deleted successfully",
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}


async def list_attachments_tool(
    api: TheBrainAPI, brain_id: str, thought_id: str
) -> dict[str, Any]:
    """List all attachments for a thought.

    Args:
        api: TheBrain API client
        brain_id: The ID of the brain
        thought_id: The ID of the thought

    Returns:
        Dictionary with success status and list of attachments
    """
    try:
        attachments = await api.list_attachments(brain_id, thought_id)

        return {
            "success": True,
            "count": len(attachments),
            "attachments": [
                {
                    "id": att.id,
                    "name": att.name,
                    "type": att.type,
                    "typeName": get_attachment_type_name(att.type),
                    "location": att.location,
                    "dataLength": att.data_length,
                    "isNotes": att.is_notes,
                    "position": att.position,
                }
                for att in attachments
            ],
        }
    except TheBrainAPIError as e:
        return {"success": False, "error": str(e)}
