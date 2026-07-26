"""MCP tools for Obsidian task management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from loguru import logger
from pydantic import BaseModel, Field

from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs
from backplane.services.tasks import CaptureCandidate, CreateTaskResult, TaskService
from backplane.utils import enums  # ruff:ignore[typing-only-first-party-import]
from backplane.utils.helpers.obsidian import VaultNoteMetadata

if TYPE_CHECKING:
    from fastmcp import FastMCP

_CANDIDATE_SNIPPET_MAX_LEN = 80
_CREATE_TASK_DESCRIPTION = """Create a structured Obsidian task note for an actionable item.

Use when the user says they need to do something, wants something on their list, asks to make a
task, or uses phrasing like "I should…", "I need to…", "remind me to…", or "add this to my list".

Do not use for speculative ideas. Use `record_idea` for loose "maybe / could / worth
investigating" captures unless the user explicitly wants to turn the idea into a task.

Task creation always succeeds even without a prior inbox match. Confirmed prior captures can
be linked with `link_capture_id`; uncertain matches may be returned as candidates and linked
later with `link_task_to_capture`.

Only set:
- `due` when the user gives an explicit date or deadline.
- `priority` when urgency/importance is explicit.
- `title` when the user gives a clear title.

If timing is implied but not explicit, leave `due=null` and keep the timing words in `description`."""
_LINK_TASK_TO_CAPTURE_DESCRIPTION = """Link an existing task note to a confirmed prior inbox capture.

Use after `create_task` returned candidate captures and the user confirms which capture belongs to the task."""


class CreateTaskToolResponse(BaseModel, frozen=True):
    """Structured MCP response for task creation."""

    metadata: VaultNoteMetadata
    slug: str
    matched_capture_id: str | None = None
    candidate_captures: list[CaptureCandidate] = Field(default_factory=list)
    domains_created: list[str] = Field(default_factory=list)
    resources_created: list[str] = Field(default_factory=list)
    projects_created: list[str] = Field(default_factory=list)
    people_created: list[str] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)


def _build_create_task_messages(task: CreateTaskResult) -> list[str]:
    """Generate follow-up messages based on capture matching results from task creation.

    Parameters:
        task (CreateTaskResult): The result of task creation, containing match and candidate capture information.

    Returns:
        list[str]: Follow-up messages describing capture match status. When a capture
            was matched, includes the capture ID. When candidates exist without a
            match, suggests linking the first candidate. Otherwise empty.
    """
    messages: list[str] = []
    if task.matched_capture_id:
        messages.append(f"Matched inbox capture from {task.matched_capture_id}.")
    elif task.candidate_captures:
        candidate = task.candidate_captures[0]
        snippet = " ".join(candidate.text.split())
        if len(snippet) > _CANDIDATE_SNIPPET_MAX_LEN:
            snippet = f"{snippet[: _CANDIDATE_SNIPPET_MAX_LEN - 3]}..."
        messages.append(
            (
                f"This looked similar to {candidate.id} ({snippet!r}); "
                f"say 'link it to {candidate.id}' to connect that capture."
            ),
        )
    return messages


async def create_task(
    *,
    description: Annotated[
        str,
        Field(
            description=(
                "Natural-language task description. Include distinctive names, nouns, "
                "and context that may help matching and metadata extraction."
            ),
        ),
    ],
    title: Annotated[
        str | None,
        Field(
            description="Optional title override. Omit unless the user supplied a clear title.",
        ),
    ] = None,
    due: Annotated[
        str | None,
        Field(description="Optional due date in YYYY-MM-DD. Only set when explicit."),
    ] = None,
    priority: Annotated[
        enums.Priority | None,
        Field(
            description="Optional priority override. Only set when explicit.",
        ),
    ] = None,
    link_capture_id: Annotated[
        str | None,
        Field(
            description=(
                "Confirmed inbox capture ID to link. Omit unless the user confirmed the capture."
            ),
        ),
    ] = None,
) -> CreateTaskToolResponse:
    """Create a structured Obsidian task note from natural language.

    Returns:
        A response containing the created task's metadata, slug, any matched or candidate inbox captures,
        newly created entities, and follow-up messages for potential linking.
    """
    logger.info(
        (
            "create_task called: description_len={} title={!r} due={!r} "
            "priority={!r} link_capture_id={!r}"
        ),
        len(description),
        title,
        due,
        priority,
        link_capture_id,
    )

    task = await TaskService().create_task(
        description,
        title=title,
        due=due,
        priority=priority,
        link_capture_id=link_capture_id,
    )

    response = CreateTaskToolResponse(
        metadata=task.metadata,
        slug=task.slug,
        matched_capture_id=task.matched_capture_id,
        candidate_captures=task.candidate_captures,
        domains_created=task.domains_created,
        resources_created=task.resources_created,
        projects_created=task.projects_created,
        people_created=task.people_created,
        messages=_build_create_task_messages(task),
    )
    logger.info(
        "create_task succeeded: slug={} matched_capture_id={}",
        task.slug,
        task.matched_capture_id,
    )
    return response


async def link_task_to_capture(
    *,
    task_slug: Annotated[
        str,
        Field(
            description=(
                "Task title, filename stem, or internal slug from the task creation response."
            ),
        ),
    ],
    capture_id: Annotated[
        str,
        Field(description="Inbox capture ID, e.g. `2026-05-25T21:15`."),
    ],
) -> str:
    """Link an existing task note to a confirmed inbox capture.

    Returns:
        A confirmation message indicating the task was successfully linked to the capture.
    """
    logger.info(
        "link_task_to_capture called: task_slug={!r} capture_id={!r}",
        task_slug,
        capture_id,
    )
    response = await TaskService().link_capture(task_slug, capture_id)
    logger.info("link_task_to_capture response={!r}", response)
    return response


def register_task_tools(mcp: FastMCP[None], *, require_oauth: bool = False) -> None:
    """Register task tools on a FastMCP server instance."""
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()

    _ = mcp.tool(description=_CREATE_TASK_DESCRIPTION, **auth_kwargs)(create_task)
    _ = mcp.tool(description=_LINK_TASK_TO_CAPTURE_DESCRIPTION, **auth_kwargs)(
        link_task_to_capture,
    )
