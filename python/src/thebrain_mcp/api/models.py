"""Pydantic models for TheBrain API requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Brain(BaseModel):
    """Brain information."""

    id: str
    name: str
    home_thought_id: str = Field(alias="homeThoughtId")


class Thought(BaseModel):
    """Thought information."""

    id: str
    brain_id: str = Field(alias="brainId")
    name: str
    label: str | None = None
    kind: int
    type_id: str | None = Field(None, alias="typeId")
    foreground_color: str | None = Field(None, alias="foregroundColor")
    background_color: str | None = Field(None, alias="backgroundColor")
    ac_type: int = Field(alias="acType")
    creation_date_time: datetime | None = Field(None, alias="creationDateTime")
    modification_date_time: datetime | None = Field(None, alias="modificationDateTime")


class Link(BaseModel):
    """Link information."""

    id: str
    brain_id: str = Field(alias="brainId")
    thought_id_a: str = Field(alias="thoughtIdA")
    thought_id_b: str = Field(alias="thoughtIdB")
    name: str | None = None
    color: str | None = None
    thickness: int | None = None
    relation: int
    direction: int | None = None
    meaning: int | None = None
    kind: int | None = None
    type_id: str | None = Field(None, alias="typeId")
    creation_date_time: datetime | None = Field(None, alias="creationDateTime")
    modification_date_time: datetime | None = Field(None, alias="modificationDateTime")


class Attachment(BaseModel):
    """Attachment information."""

    id: str
    brain_id: str = Field(alias="brainId")
    source_id: str = Field(alias="sourceId")
    source_type: int = Field(alias="sourceType")
    name: str
    type: int
    location: str | None = None
    data_length: int | None = Field(None, alias="dataLength")
    position: int | None = None
    is_notes: bool | None = Field(None, alias="isNotes")
    creation_date_time: datetime | None = Field(None, alias="creationDateTime")
    modification_date_time: datetime | None = Field(None, alias="modificationDateTime")
    file_modification_date_time: datetime | None = Field(None, alias="fileModificationDateTime")


class Note(BaseModel):
    """Note information."""

    brain_id: str = Field(alias="brainId")
    source_id: str = Field(alias="sourceId")
    markdown: str | None = None
    html: str | None = None
    text: str | None = None
    modification_date_time: datetime | None = Field(None, alias="modificationDateTime")


class SearchResult(BaseModel):
    """Search result information."""

    name: str | None = None
    search_result_type: int = Field(alias="searchResultType")
    source_thought: Thought | None = Field(None, alias="sourceThought")
    snippet: str | None = None
    attachment_id: str | None = Field(None, alias="attachmentId")


class ThoughtGraph(BaseModel):
    """Thought graph with connections."""

    active_thought: Thought = Field(alias="activeThought")
    parents: list[Thought] | None = None
    children: list[Thought] | None = None
    jumps: list[Thought] | None = None
    siblings: list[Thought] | None = None
    tags: list[Thought] | None = None
    type: Thought | None = None
    links: list[Link] | None = None
    attachments: list[Attachment] | None = None


class BrainStats(BaseModel):
    """Brain statistics."""

    brain_name: str = Field(alias="brainName")
    brain_id: str = Field(alias="brainId")
    date_generated: datetime | None = Field(None, alias="dateGenerated")
    thoughts: int | None = None
    forgotten_thoughts: int | None = Field(None, alias="forgottenThoughts")
    links: int | None = None
    links_per_thought: float | None = Field(None, alias="linksPerThought")
    thought_types: int | None = Field(None, alias="thoughtTypes")
    link_types: int | None = Field(None, alias="linkTypes")
    tags: int | None = None
    notes: int | None = None
    internal_files: int | None = Field(None, alias="internalFiles")
    internal_folders: int | None = Field(None, alias="internalFolders")
    external_files: int | None = Field(None, alias="externalFiles")
    external_folders: int | None = Field(None, alias="externalFolders")
    web_links: int | None = Field(None, alias="webLinks")
    internal_files_size: int | None = Field(None, alias="internalFilesSize")
    icons_files_size: int | None = Field(None, alias="iconsFilesSize")
    assigned_icons: int | None = Field(None, alias="assignedIcons")


class Modification(BaseModel):
    """Modification/change history entry."""

    source_id: str = Field(alias="sourceId")
    source_type: int = Field(alias="sourceType")
    mod_type: int = Field(alias="modType")
    old_value: str | None = Field(None, alias="oldValue")
    new_value: str | None = Field(None, alias="newValue")
    user_id: str | None = Field(None, alias="userId")
    creation_date_time: datetime | None = Field(None, alias="creationDateTime")
    modification_date_time: datetime | None = Field(None, alias="modificationDateTime")
    extra_a_id: str | None = Field(None, alias="extraAId")
    extra_b_id: str | None = Field(None, alias="extraBId")


class JsonPatchOperation(BaseModel):
    """JSON Patch operation for updates."""

    op: str = "replace"
    path: str
    value: Any


class JsonPatchDocument(BaseModel):
    """JSON Patch document wrapper."""

    patch_document: list[JsonPatchOperation] = Field(alias="patchDocument")
