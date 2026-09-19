"""HTTP request and response schemas for the Backplane REST API."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backplane.operations.tasks import TaskCreationOutcome
from backplane.services.vault_entities import UpdateMode
from backplane.services.vault_search import VaultNoteSearchHit
from backplane.utils.enums import Priority

EntityKind = Literal["domain", "person", "project", "resource"]


class ErrorResponse(BaseModel, frozen=True):
    """Standard response for domain errors."""

    message: str
    detail: object | None = None


class HealthResponse(BaseModel, frozen=True):
    """Health check response."""

    status: Literal["ok"]
    version: str


class MarkdownResponse(BaseModel, frozen=True):
    """Response containing rendered Markdown."""

    markdown: str


class DailyNoteResponse(MarkdownResponse, frozen=True):
    """Rendered daily note with its date."""

    date: dt.date


class SectionResponse(MarkdownResponse, frozen=True):
    """Response containing a rendered Markdown section."""


class MessageResponse(BaseModel, frozen=True):
    """Response containing a concise outcome message."""

    message: str


class MoveNoteResponse(MessageResponse, frozen=True):
    """Response confirming a note move."""

    path: str


class NamesResponse(BaseModel, frozen=True):
    """Response containing entity display names."""

    names: list[str]


class VaultEntitySectionResponse(BaseModel, frozen=True):
    """Public representation of an entity note heading."""

    heading: str
    path: list[str]
    level: int


class SectionsResponse(BaseModel, frozen=True):
    """Response containing entity note sections."""

    sections: list[VaultEntitySectionResponse]


class SearchResponse(BaseModel, frozen=True):
    """Response containing ranked vault-note hits."""

    hits: list[VaultNoteSearchHit]


class CreateTaskResponse(TaskCreationOutcome, frozen=True):
    """Structured response returned after creating a task."""

    messages: list[str] = Field(default_factory=list)


class DailyNoteUpdateRequest(BaseModel, frozen=True):
    """Request to update a section in a daily note."""

    heading_path: Annotated[list[str], Field(min_length=1)]
    content: str
    mode: UpdateMode = "append"
    create_section_if_not_exists: bool = False
    date: dt.date | None = None


class IdeaRequest(BaseModel, frozen=True):
    """Request to record an idea."""

    idea: str


class MoveNoteRequest(BaseModel, frozen=True):
    """Request to move a vault-relative Markdown note."""

    source_path: str
    destination_path: str


class CreateTaskRequest(BaseModel, frozen=True):
    """Request to create a task note."""

    description: str
    title: str | None = None
    due: str | None = None
    priority: Priority | None = None
    link_capture_id: str | None = None


class LinkCaptureRequest(BaseModel, frozen=True):
    """Request to link a task to an existing inbox capture."""

    capture_id: str


class CreateEntityRequest(BaseModel, frozen=True):
    """Request to create an entity note."""

    name: str


class EntitySectionUpdateRequest(BaseModel, frozen=True):
    """Request to update a section in an entity note."""

    heading_path: Annotated[list[str], Field(min_length=1)]
    content: str
    mode: UpdateMode = "append"
    create_section_if_not_exists: bool = False
