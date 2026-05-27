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
from tollbooth.tool_identity import (  # noqa: E402, F401
    STANDARD_IDENTITIES,
    ToolIdentity,
    capability_uuid,
)

# Frozen UUIDs — declared once at tool birth. Past versions of this
# file derived these from capability_uuid("<name>") at runtime, which
# meant any future rename of a `capability` string above would change
# the UUID and orphan every pricing-model row keyed by the OLD UUID.
# That is what bit this MCP at v1.9.20. They are now opaque constants.
LIST_KNOWLEDGE_BASES_UUID             = "6a4afcbc-dc0b-5c09-b2c9-6c316931c866"
GET_KNOWLEDGE_BASE_UUID               = "3338e45f-922c-5648-8692-0f2aed9e239a"
GET_KNOWLEDGE_BASE_STATS_UUID         = "2d431bc0-7110-5d7f-9421-1844371a5a1b"
SET_ACTIVE_KNOWLEDGE_BASE_UUID        = "9028c861-57d0-5455-8f58-4781f14d15e7"
GET_KNOWLEDGE_NODE_UUID               = "bf9f76f6-f8fe-5ee2-8aed-3c3b27029453"
GET_KNOWLEDGE_NODE_BY_NAME_UUID       = "fb5188ae-5792-54b8-bbd1-6b289605fa31"
SEARCH_KNOWLEDGE_NODES_UUID           = "ce546ef0-01db-500b-b4a4-4a6c92a82c9a"
GET_KNOWLEDGE_GRAPH_UUID              = "5caea62e-f2c6-56a1-a2da-2b5bb691ac9d"
LIST_KNOWLEDGE_NODE_TYPES_UUID        = "7b94a5eb-2e5f-5466-ab95-a4b27e187f39"
LIST_KNOWLEDGE_NODE_TAGS_UUID         = "162587c0-145e-55d9-8aed-0f7e66d5c889"
GET_KNOWLEDGE_NODE_NOTE_UUID          = "b4def8ce-544c-5332-8537-66f245bf6b07"
GET_KNOWLEDGE_LINK_UUID               = "1048ba29-b901-5317-9f4a-9784b1a971b5"
GET_KNOWLEDGE_ATTACHMENT_UUID         = "b069ef7d-7b6d-5a41-9b7c-41e6ddbacb8d"
GET_KNOWLEDGE_ATTACHMENT_CONTENT_UUID = "f74e4628-9728-5c82-88f0-2db755c5daa9"
LIST_KNOWLEDGE_ATTACHMENTS_UUID       = "ca7bb37e-0079-5a05-a850-7a3a8d3c9d4d"
CREATE_KNOWLEDGE_NODE_UUID            = "4a6670f4-2daf-5307-9209-1acedcf7e5f2"
UPDATE_KNOWLEDGE_NODE_UUID            = "5fe8c775-bc29-5987-a951-a748a1e0ca0b"
DELETE_KNOWLEDGE_NODE_UUID            = "8b64ff9a-3a71-501d-ad5b-e76c49c1a182"
CREATE_KNOWLEDGE_LINK_UUID            = "fce4c7d1-2306-5e06-b433-29e7a21d550b"
UPDATE_KNOWLEDGE_LINK_UUID            = "9bacd35b-80da-5c6b-aef9-b58a54d374f6"
DELETE_KNOWLEDGE_LINK_UUID            = "577b5826-7688-56d8-9388-e84bed52bafb"
UPSERT_KNOWLEDGE_NODE_NOTE_UUID       = "91706bcc-189e-51a0-9b9c-19fb877ab18c"
APPEND_KNOWLEDGE_NODE_NOTE_UUID       = "dd9b495b-dbe3-517d-98eb-38858e55228c"
ATTACH_FILE_TO_KNOWLEDGE_NODE_UUID    = "d5139ba5-f340-5765-8ccf-5e8bb51db33b"
ATTACH_URL_TO_KNOWLEDGE_NODE_UUID     = "d5aa8f54-53f4-5400-ab45-4f8df58e567b"
DELETE_KNOWLEDGE_ATTACHMENT_UUID      = "9c4eb660-bebd-50ca-9f74-6fc6a8cd1654"
MORPH_KNOWLEDGE_NODE_UUID             = "745d8849-a1fd-56d0-baeb-ae1022d232e7"
QUERY_KNOWLEDGE_BASE_UUID             = "78bc827b-ee7e-520e-bd88-cd47bb4c1698"
GET_KNOWLEDGE_BASE_HISTORY_UUID       = "ffa70d96-b200-55b4-b9b7-91cbd923577c"
GET_KNOWLEDGE_GRAPH_PAGINATED_UUID    = "d0a5f8c6-d260-5525-8ef9-174b29db7ab6"
SCAN_ORPHAN_KNOWLEDGE_NODES_UUID      = "e2bfb041-5d15-5dc8-93c7-a621bfddec85"
GET_PERSON_EVENT_UUID                 = "4bafffbf-2089-51cd-af72-27d39f93c8c3"


_DOMAIN_TOOLS = [
    # -- Domain-specific TheBrain tools --

    # Read — knowledge-base browsing
    ToolIdentity(
        tool_id=LIST_KNOWLEDGE_BASES_UUID,
        capability="list_knowledge_bases",
        category="read",
        intent="List available TheBrain knowledge bases.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_BASE_UUID,
        capability="get_knowledge_base",
        category="read",
        intent="Get metadata for a TheBrain knowledge base.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_BASE_STATS_UUID,
        capability="get_knowledge_base_stats",
        category="read",
        intent="Get statistics for a TheBrain knowledge base.",
    ),
    ToolIdentity(
        tool_id=SET_ACTIVE_KNOWLEDGE_BASE_UUID,
        capability="set_active_knowledge_base",
        category="read",
        intent="Set the active TheBrain knowledge base for the session.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_NODE_UUID,
        capability="get_knowledge_node",
        category="read",
        intent="Get a thought (node) by ID.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_NODE_BY_NAME_UUID,
        capability="get_knowledge_node_by_name",
        category="read",
        intent="Look up a thought by exact name.",
    ),
    ToolIdentity(
        tool_id=SEARCH_KNOWLEDGE_NODES_UUID,
        capability="search_knowledge_nodes",
        category="read",
        intent="Full-text search across thoughts.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_GRAPH_UUID,
        capability="get_knowledge_graph",
        category="read",
        intent="Traverse connections around a thought.",
    ),
    ToolIdentity(
        tool_id=LIST_KNOWLEDGE_NODE_TYPES_UUID,
        capability="list_knowledge_node_types",
        category="read",
        intent="List thought types in the brain.",
    ),
    ToolIdentity(
        tool_id=LIST_KNOWLEDGE_NODE_TAGS_UUID,
        capability="list_knowledge_node_tags",
        category="read",
        intent="List tags in the brain.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_NODE_NOTE_UUID,
        capability="get_knowledge_node_note",
        category="read",
        intent="Get the note content of a thought.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_LINK_UUID,
        capability="get_knowledge_link",
        category="read",
        intent="Get a link between thoughts by ID.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_ATTACHMENT_UUID,
        capability="get_knowledge_attachment",
        category="read",
        intent="Get attachment metadata for a thought.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_ATTACHMENT_CONTENT_UUID,
        capability="get_knowledge_attachment_content",
        category="read",
        intent="Download attachment content.",
    ),
    ToolIdentity(
        tool_id=LIST_KNOWLEDGE_ATTACHMENTS_UUID,
        capability="list_knowledge_attachments",
        category="read",
        intent="List attachments for a thought.",
    ),

    # Write — knowledge-base mutations
    ToolIdentity(
        tool_id=CREATE_KNOWLEDGE_NODE_UUID,
        capability="create_knowledge_node",
        category="write",
        intent="Create a new thought in the brain.",
    ),
    ToolIdentity(
        tool_id=UPDATE_KNOWLEDGE_NODE_UUID,
        capability="update_knowledge_node",
        category="write",
        intent="Update an existing thought.",
    ),
    ToolIdentity(
        tool_id=DELETE_KNOWLEDGE_NODE_UUID,
        capability="delete_knowledge_node",
        category="write",
        intent="Delete a thought from the brain.",
    ),
    ToolIdentity(
        tool_id=CREATE_KNOWLEDGE_LINK_UUID,
        capability="create_knowledge_link",
        category="write",
        intent="Create a link between two thoughts.",
    ),
    ToolIdentity(
        tool_id=UPDATE_KNOWLEDGE_LINK_UUID,
        capability="update_knowledge_link",
        category="write",
        intent="Update an existing link.",
    ),
    ToolIdentity(
        tool_id=DELETE_KNOWLEDGE_LINK_UUID,
        capability="delete_knowledge_link",
        category="write",
        intent="Delete a link between thoughts.",
    ),
    ToolIdentity(
        tool_id=UPSERT_KNOWLEDGE_NODE_NOTE_UUID,
        capability="upsert_knowledge_node_note",
        category="write",
        intent="Create or replace a thought's note.",
    ),
    ToolIdentity(
        tool_id=APPEND_KNOWLEDGE_NODE_NOTE_UUID,
        capability="append_knowledge_node_note",
        category="write",
        intent="Append content to a thought's note.",
    ),
    ToolIdentity(
        tool_id=ATTACH_FILE_TO_KNOWLEDGE_NODE_UUID,
        capability="attach_file_to_knowledge_node",
        category="write",
        intent="Upload a file attachment to a thought.",
    ),
    ToolIdentity(
        tool_id=ATTACH_URL_TO_KNOWLEDGE_NODE_UUID,
        capability="attach_url_to_knowledge_node",
        category="write",
        intent="Attach a URL to a thought.",
    ),
    ToolIdentity(
        tool_id=DELETE_KNOWLEDGE_ATTACHMENT_UUID,
        capability="delete_knowledge_attachment",
        category="write",
        intent="Delete an attachment from a thought.",
    ),
    ToolIdentity(
        tool_id=MORPH_KNOWLEDGE_NODE_UUID,
        capability="morph_knowledge_node",
        category="write",
        intent="Change a thought's type or kind.",
    ),

    # Heavy — expensive or bulk operations
    ToolIdentity(
        tool_id=QUERY_KNOWLEDGE_BASE_UUID,
        capability="query_knowledge_base",
        category="heavy",
        intent="Execute a BrainQuery (BQL) pattern against the brain.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_BASE_HISTORY_UUID,
        capability="get_knowledge_base_history",
        category="heavy",
        intent="Get modification history for the brain.",
    ),
    ToolIdentity(
        tool_id=GET_KNOWLEDGE_GRAPH_PAGINATED_UUID,
        capability="get_knowledge_graph_paginated",
        category="heavy",
        intent="Paginated traversal of thought connections.",
    ),
    ToolIdentity(
        tool_id=SCAN_ORPHAN_KNOWLEDGE_NODES_UUID,
        capability="scan_orphan_knowledge_nodes",
        category="heavy",
        intent="Find disconnected (orphan) thoughts.",
    ),
    ToolIdentity(
        tool_id=GET_PERSON_EVENT_UUID,
        capability="get_person_event",
        category="heavy",
        intent="Find or create a calendar event for a person.",
    ),
]

TOOL_REGISTRY: dict[str, ToolIdentity] = {ti.tool_id: ti for ti in _DOMAIN_TOOLS}


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
