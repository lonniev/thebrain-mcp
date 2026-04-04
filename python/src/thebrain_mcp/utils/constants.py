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


# Re-exported from tollbooth
from tollbooth.tool_identity import ToolIdentity, STANDARD_IDENTITIES  # noqa: E402, F401

TOOL_REGISTRY: dict[str, ToolIdentity] = {
    # -- Domain-specific TheBrain tools --

    # Read — knowledge-base browsing
    "list_brains": ToolIdentity(
        capability="list_knowledge_bases",
        category="read",
        intent="List available TheBrain knowledge bases.",
    ),
    "get_brain": ToolIdentity(
        capability="get_knowledge_base",
        category="read",
        intent="Get metadata for a TheBrain knowledge base.",
    ),
    "get_brain_stats": ToolIdentity(
        capability="get_knowledge_base_stats",
        category="read",
        intent="Get statistics for a TheBrain knowledge base.",
    ),
    "set_active_brain": ToolIdentity(
        capability="set_active_knowledge_base",
        category="read",
        intent="Set the active TheBrain knowledge base for the session.",
    ),
    "get_thought": ToolIdentity(
        capability="get_knowledge_node",
        category="read",
        intent="Get a thought (node) by ID.",
    ),
    "get_thought_by_name": ToolIdentity(
        capability="get_knowledge_node_by_name",
        category="read",
        intent="Look up a thought by exact name.",
    ),
    "search_thoughts": ToolIdentity(
        capability="search_knowledge_nodes",
        category="read",
        intent="Full-text search across thoughts.",
    ),
    "get_thought_graph": ToolIdentity(
        capability="get_knowledge_graph",
        category="read",
        intent="Traverse connections around a thought.",
    ),
    "get_types": ToolIdentity(
        capability="list_knowledge_node_types",
        category="read",
        intent="List thought types in the brain.",
    ),
    "get_tags": ToolIdentity(
        capability="list_knowledge_node_tags",
        category="read",
        intent="List tags in the brain.",
    ),
    "get_note": ToolIdentity(
        capability="get_knowledge_node_note",
        category="read",
        intent="Get the note content of a thought.",
    ),
    "get_link": ToolIdentity(
        capability="get_knowledge_link",
        category="read",
        intent="Get a link between thoughts by ID.",
    ),
    "get_attachment": ToolIdentity(
        capability="get_knowledge_attachment",
        category="read",
        intent="Get attachment metadata for a thought.",
    ),
    "get_attachment_content": ToolIdentity(
        capability="get_knowledge_attachment_content",
        category="read",
        intent="Download attachment content.",
    ),
    "list_attachments": ToolIdentity(
        capability="list_knowledge_attachments",
        category="read",
        intent="List attachments for a thought.",
    ),

    # Write — knowledge-base mutations
    "create_thought": ToolIdentity(
        capability="create_knowledge_node",
        category="write",
        intent="Create a new thought in the brain.",
    ),
    "update_thought": ToolIdentity(
        capability="update_knowledge_node",
        category="write",
        intent="Update an existing thought.",
    ),
    "delete_thought": ToolIdentity(
        capability="delete_knowledge_node",
        category="write",
        intent="Delete a thought from the brain.",
    ),
    "create_link": ToolIdentity(
        capability="create_knowledge_link",
        category="write",
        intent="Create a link between two thoughts.",
    ),
    "update_link": ToolIdentity(
        capability="update_knowledge_link",
        category="write",
        intent="Update an existing link.",
    ),
    "delete_link": ToolIdentity(
        capability="delete_knowledge_link",
        category="write",
        intent="Delete a link between thoughts.",
    ),
    "create_or_update_note": ToolIdentity(
        capability="upsert_knowledge_node_note",
        category="write",
        intent="Create or replace a thought's note.",
    ),
    "append_to_note": ToolIdentity(
        capability="append_knowledge_node_note",
        category="write",
        intent="Append content to a thought's note.",
    ),
    "add_file_attachment": ToolIdentity(
        capability="attach_file_to_knowledge_node",
        category="write",
        intent="Upload a file attachment to a thought.",
    ),
    "add_url_attachment": ToolIdentity(
        capability="attach_url_to_knowledge_node",
        category="write",
        intent="Attach a URL to a thought.",
    ),
    "delete_attachment": ToolIdentity(
        capability="delete_knowledge_attachment",
        category="write",
        intent="Delete an attachment from a thought.",
    ),
    "morph_thought": ToolIdentity(
        capability="morph_knowledge_node",
        category="write",
        intent="Change a thought's type or kind.",
    ),

    # Heavy — expensive or bulk operations
    "brain_query": ToolIdentity(
        capability="query_knowledge_base",
        category="heavy",
        intent="Execute a BrainQuery (BQL) pattern against the brain.",
    ),
    "get_modifications": ToolIdentity(
        capability="get_knowledge_base_history",
        category="heavy",
        intent="Get modification history for the brain.",
    ),
    "get_thought_graph_paginated": ToolIdentity(
        capability="get_knowledge_graph_paginated",
        category="heavy",
        intent="Paginated traversal of thought connections.",
    ),
    "scan_orphans": ToolIdentity(
        capability="scan_orphan_knowledge_nodes",
        category="heavy",
        intent="Find disconnected (orphan) thoughts.",
    ),
    "event_for_person": ToolIdentity(
        capability="get_person_event",
        category="heavy",
        intent="Find or create a calendar event for a person.",
    ),
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
