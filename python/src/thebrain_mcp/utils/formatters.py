"""Utility functions for formatting responses."""

from thebrain_mcp.utils.constants import (
    AccessType,
    AttachmentType,
    LinkDirection,
    LinkKind,
    LinkMeaning,
    ModificationType,
    RelationType,
    SearchResultType,
    SourceType,
    ThoughtKind,
)


def get_kind_name(kind: int) -> str:
    """Get human-readable name for thought kind."""
    try:
        return ThoughtKind(kind).name.title()
    except ValueError:
        return "Unknown"


def get_relation_name(relation: int) -> str:
    """Get human-readable name for link relation."""
    try:
        return RelationType(relation).name.title()
    except ValueError:
        return "Unknown"


def get_access_type_name(ac_type: int) -> str:
    """Get human-readable name for access type."""
    try:
        return AccessType(ac_type).name.title()
    except ValueError:
        return "Unknown"


def get_search_result_type_name(result_type: int) -> str:
    """Get human-readable name for search result type."""
    try:
        return SearchResultType(result_type).name.title()
    except ValueError:
        return "Unknown"


def get_source_type_name(source_type: int) -> str:
    """Get human-readable name for source type."""
    try:
        return SourceType(source_type).name.title()
    except ValueError:
        return "Unknown"


def get_attachment_type_name(att_type: int) -> str:
    """Get human-readable name for attachment type."""
    try:
        return AttachmentType(att_type).name.title()
    except ValueError:
        return f"Type{att_type}"


def get_link_meaning_name(meaning: int) -> str:
    """Get human-readable name for link meaning."""
    try:
        return LinkMeaning(meaning).name.title()
    except ValueError:
        return "Unknown"


def get_link_kind_name(kind: int) -> str:
    """Get human-readable name for link kind."""
    try:
        return LinkKind(kind).name.title()
    except ValueError:
        return "Unknown"


def get_modification_type_name(mod_type: int) -> str:
    """Get human-readable name for modification type."""
    try:
        return ModificationType(mod_type).name.replace("_", " ").title()
    except ValueError:
        return f"ModType{mod_type}"


def get_direction_info(direction: int | None) -> dict[str, str | int | bool] | None:
    """Get detailed information about link direction."""
    if direction is None:
        return None

    is_directed = bool(direction & LinkDirection.DIRECTED)
    is_backward = bool(direction & LinkDirection.BACKWARD)
    is_one_way = bool(direction & LinkDirection.ONE_WAY)

    # Build description
    parts = []
    if is_directed:
        parts.append("B→A" if is_backward else "A→B")
    else:
        parts.append("Undirected")

    if is_one_way:
        parts.append("One-Way")

    return {
        "value": direction,
        "isDirected": is_directed,
        "isBackward": is_backward,
        "isOneWay": is_one_way,
        "description": ", ".join(parts),
    }


def format_bytes(bytes_count: int | None) -> str:
    """Format byte count as human-readable string."""
    if not bytes_count or bytes_count == 0:
        return "0 Bytes"

    k = 1024
    sizes = ["Bytes", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(bytes_count)

    while size >= k and i < len(sizes) - 1:
        size /= k
        i += 1

    return f"{size:.2f} {sizes[i]}"
