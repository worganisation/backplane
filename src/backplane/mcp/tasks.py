"""MCP tools for Obsidian task management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from loguru import logger
from pydantic import Field

from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs
from backplane.operations.tasks import (
    TaskCreationOutcome,
    build_task_capture_messages,
    task_creation_outcome,
)
from backplane.services.tasks import TaskService
from backplane.utils import enums  # ruff:ignore[typing-only-first-party-import]

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


class CreateTaskToolResponse(TaskCreationOutcome, frozen=True):
    """Structured MCP response for task creation."""

    messages: list[str] = Field(default_factory=list)


def _build_create_task_messages(task: TaskCreationOutcome) -> list[str]:
    """Generate follow-up messages based on capture matching results from task creation.

    Parameters:
        task (CreateTaskResult): The result of task creation, containing match and candidate capture information.

    Returns:
        list[str]: Follow-up messages describing capture match status. When a capture
            was matched, includes the capture ID. When candidates exist without a
            match, suggests linking the first candidate. Otherwise empty.
    """
    return build_task_capture_messages(
        task,
        style="mcp",
        candidate_snippet_max_len=_CANDIDATE_SNIPPET_MAX_LEN,
    )


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

    outcome = task_creation_outcome(task)
    response = CreateTaskToolResponse(
        metadata=outcome.metadata,
        slug=outcome.slug,
        matched_capture_id=outcome.matched_capture_id,
        candidate_captures=outcome.candidate_captures,
        domains_created=outcome.domains_created,
        resources_created=outcome.resources_created,
        projects_created=outcome.projects_created,
        people_created=outcome.people_created,
        messages=_build_create_task_messages(outcome),
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
