"""Constants and enums for TheBrain MCP server."""

from enum import IntEnum


class ThoughtKind(IntEnum):
    """Thought kinds in TheBrain."""

    NORMAL = 1
    TYPE = 2
    EVENT = 3
    TAG = 4
    SYSTEM = 5


class RelationType(IntEnum):
    """Link relation types in TheBrain."""

    CHILD = 1
    PARENT = 2
    JUMP = 3
    SIBLING = 4


class AccessType(IntEnum):
    """Access control types for thoughts."""

    PUBLIC = 0
    PRIVATE = 1


class LinkDirection(IntEnum):
    """Link direction flags (can be combined with bitwise OR)."""

    UNDIRECTED = 0
    DIRECTED = 1  # A→B
    BACKWARD = 2  # B→A (use with DIRECTED: 1 | 2 = 3)
    ONE_WAY = 4  # Can combine: DIRECTED | ONE_WAY = 5


class SearchResultType(IntEnum):
    """Types of search results."""

    UNKNOWN = 0
    THOUGHT = 1
    LINK = 2
    ATTACHMENT = 3
    NOTE = 4
    LABEL = 5
    TYPE = 6
    TAG = 7


class SourceType(IntEnum):
    """Source types for attachments."""

    BRAIN = 1
    THOUGHT = 2
    LINK = 3
    ATTACHMENT = 4
    BRAIN_SETTING = 5
    BRAIN_ACCESS = 6
    CALENDAR_EVENT = 7
    FIELD_INSTANCE = 8
    FIELD_DEFINITION = 9


class AttachmentType(IntEnum):
    """Attachment types."""

    FILE = 0
    URL = 1
    INTERNAL_FILE = 2
    EXTERNAL_FILE = 3
    WEB_LINK = 4


class LinkMeaning(IntEnum):
    """Link meaning types."""

    NORMAL = 1
    INSTANCE_OF = 2
    TYPE_OF = 3
    HAS_EVENT = 4
    HAS_TAG = 5
    SYSTEM = 6
    SUB_TAG_OF = 7


class LinkKind(IntEnum):
    """Link kind types."""

    NORMAL = 1
    TYPE = 2


class ModificationType(IntEnum):
    """Modification/change types for brain history."""

    # Generic Actions
    CREATED = 101
    DELETED = 102
    CHANGED_NAME = 103
    CREATED_BY_PASTE = 104
    MODIFIED_BY_PASTE = 105

    # Thoughts and Links
    CHANGED_COLOR = 201
    CHANGED_LABEL = 202
    SET_TYPE = 203
    CHANGED_COLOR2 = 204
    CREATED_ICON = 205
    DELETED_ICON = 206
    CHANGED_ICON = 207

    # Thought Specific
    FORGOT = 301
    REMEMBERED = 302
    CHANGED_ACCESS_TYPE = 303
    CHANGED_KIND = 304

    # Link Specific
    CHANGED_THICKNESS = 401
    MOVED_LINK = 402
    CHANGED_DIRECTION = 403
    CHANGED_MEANING = 404
    CHANGED_RELATION = 405

    # Attachment Specific
    CHANGED_CONTENT = 501
    CHANGED_LOCATION = 502
    CHANGED_POSITION = 503

    # Note Specific
    CREATED_NOTE = 801
    DELETED_NOTE = 802
    CHANGED_NOTE = 803


class NoteFormat(str):
    """Note format types."""

    MARKDOWN = "markdown"
    HTML = "html"
    TEXT = "text"


# Re-exported from tollbooth (backward compat)
from tollbooth.constants import MAX_INVOICE_SATS, LOW_BALANCE_FLOOR_API_SATS, ToolTier  # noqa: E402, F401


TOOL_COSTS: dict[str, int] = {
    # Free (0 sats) — never gated
    "whoami": ToolTier.FREE,
    "session_status": ToolTier.FREE,
    "register_credentials": ToolTier.FREE,
    "activate_session": ToolTier.FREE,
    "list_brains": ToolTier.FREE,
    "purchase_credits": ToolTier.FREE,
    "check_payment": ToolTier.FREE,
    "check_balance": ToolTier.FREE,
    "btcpay_status": ToolTier.FREE,
    "restore_credits": ToolTier.FREE,
    "refresh_config": ToolTier.FREE,
    "test_low_balance_warning": ToolTier.FREE,
    # Read (1 sat)
    "get_brain": ToolTier.READ,
    "get_brain_stats": ToolTier.READ,
    "set_active_brain": ToolTier.READ,
    "get_thought": ToolTier.READ,
    "get_thought_by_name": ToolTier.READ,
    "search_thoughts": ToolTier.READ,
    "get_thought_graph": ToolTier.READ,
    "get_types": ToolTier.READ,
    "get_tags": ToolTier.READ,
    "get_note": ToolTier.READ,
    "get_link": ToolTier.READ,
    "get_attachment": ToolTier.READ,
    "get_attachment_content": ToolTier.READ,
    "list_attachments": ToolTier.READ,
    # Write (5 sats)
    "create_thought": ToolTier.WRITE,
    "update_thought": ToolTier.WRITE,
    "delete_thought": ToolTier.WRITE,
    "create_link": ToolTier.WRITE,
    "update_link": ToolTier.WRITE,
    "delete_link": ToolTier.WRITE,
    "create_or_update_note": ToolTier.WRITE,
    "append_to_note": ToolTier.WRITE,
    "add_file_attachment": ToolTier.WRITE,
    "add_url_attachment": ToolTier.WRITE,
    "delete_attachment": ToolTier.WRITE,
    # Heavy (10 sats)
    "brain_query": ToolTier.HEAVY,
    "get_modifications": ToolTier.HEAVY,
    "get_thought_graph_paginated": ToolTier.HEAVY,
}


# MIME type mapping for file uploads
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
