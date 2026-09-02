"""Shared task-result projection for transport adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backplane.services.tasks import CaptureCandidate, CreateTaskResult
from backplane.utils.helpers.obsidian import VaultNoteMetadata

TaskCaptureMessageStyle = Literal["api", "mcp"]


class TaskCreationOutcome(BaseModel, frozen=True):
    """Adapter-neutral public fields from a created task."""

    metadata: VaultNoteMetadata
    slug: str
    matched_capture_id: str | None = None
    candidate_captures: list[CaptureCandidate] = Field(default_factory=list)
    domains_created: list[str] = Field(default_factory=list)
    resources_created: list[str] = Field(default_factory=list)
    projects_created: list[str] = Field(default_factory=list)
    people_created: list[str] = Field(default_factory=list)


def task_creation_outcome(task: CreateTaskResult) -> TaskCreationOutcome:
    """Project a domain task result into the shared adapter outcome.

    Args:
        task: Domain task creation result to project.

    Returns:
        Public task outcome fields independent of an HTTP or MCP transport.
    """
    return TaskCreationOutcome(
        metadata=task.metadata,
        slug=task.slug,
        matched_capture_id=task.matched_capture_id,
        candidate_captures=task.candidate_captures,
        domains_created=task.domains_created,
        resources_created=task.resources_created,
        projects_created=task.projects_created,
        people_created=task.people_created,
    )


def build_task_capture_messages(
    task: TaskCreationOutcome,
    *,
    style: TaskCaptureMessageStyle,
    candidate_snippet_max_len: int | None = None,
) -> list[str]:
    """Build adapter-specific follow-up guidance for capture matching.

    Args:
        task: Adapter-neutral task outcome to inspect for capture matches.
        style: Message wording style.
        candidate_snippet_max_len: Optional maximum length for candidate text snippets.

    Returns:
        Follow-up messages for a matched or candidate capture.
    """
    if task.matched_capture_id:
        return [f"Matched inbox capture from {task.matched_capture_id}."]
    if not task.candidate_captures:
        return []

    candidate = task.candidate_captures[0]
    snippet = " ".join(candidate.text.split())
    if candidate_snippet_max_len is not None and len(snippet) > candidate_snippet_max_len:
        snippet = f"{snippet[: candidate_snippet_max_len - 3]}..."

    if style == "mcp":
        message = (
            f"This looked similar to {candidate.id} ({snippet!r}); "
            f"say 'link it to {candidate.id}' to connect that capture."
        )
    else:
        message = (
            f"This looked similar to {candidate.id} ({snippet!r}); "
            "link it with that capture ID to connect the task."
        )
    return [message]
