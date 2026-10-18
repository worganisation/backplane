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
from backplane.services.task_catalog import get_task, list_tasks
from backplane.services.task_updates import update_task
from backplane.services.tasks import TaskService
from backplane.utils import enums  # ruff:ignore[typing-only-first-party-import]

if TYPE_CHECKING:
    from fastmcp import FastMCP

_CANDIDATE_SNIPPET_MAX_LEN = 80
_CREATE_TASK_DESCRIPTION = """Create an enriched Obsidian task with model-extracted metadata and entity links.

Use when metadata enrichment or linking a confirmed prior idea is requested.
For ordinary actions to remember ("I need to", "I should", "add a task"), prefer
`capture_task`, which saves immediately without another model call.

Do not use for speculative ideas. Use `record_idea` for loose "maybe / could / worth
investigating" captures unless the user explicitly wants to turn the idea into a task.

Task creation always succeeds even without a prior inbox match. Confirmed prior captures can
be linked with `link_capture_id`; uncertain matches may be returned as candidates and linked
later with `link_task_to_capture`.

Only set:
- `due` when the user gives an explicit date or deadline.
- `priority` when urgency/importance is explicit.
- `title` when the user gives a clear title.

Supply a stable `idempotency_key` for each operation and reuse it with identical fields on retries.

A saved task can return warnings for incomplete links; fix their cause and retry with the same key.

If timing is implied but not explicit, leave `due=null` and keep the timing words in `description`."""
_LINK_TASK_TO_CAPTURE_DESCRIPTION = """Link an existing task note to a confirmed prior inbox capture.

Use after `create_task` returned candidate captures and the user confirms which capture belongs to the task."""


class CreateTaskToolResponse(TaskCreationOutcome, frozen=True):
    """Structured MCP response for task creation."""

    messages: list[str] = Field(default_factory=list)


def _build_create_task_messages(task: TaskCreationOutcome) -> list[str]:
    """Generate follow-up messages based on capture matching results from task creation.

    Args:
        task: Task creation outcome containing match and candidate capture information.

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
    project: Annotated[
        str | None,
        Field(
            description="Explicit project name; creates a stub if absent. Omit for no explicit assignment.",
        ),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Field(
            min_length=1,
            description="Stable operation key; reuse with identical input on retry.",
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
        idempotency_key=idempotency_key,
        project=project,
    )

    outcome = task_creation_outcome(task)
    response = CreateTaskToolResponse.model_validate(
        outcome.model_dump() | {"messages": _build_create_task_messages(outcome)},
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


async def capture_task(
    description: Annotated[
        str,
        Field(min_length=1, description="Full original action to remember."),
    ],
    title: Annotated[
        str | None,
        Field(description="Optional short title; omit if not supplied."),
    ] = None,
    due: Annotated[
        str | None,
        Field(description="Explicit YYYY-MM-DD deadline only."),
    ] = None,
    priority: enums.Priority | None = None,
    project: Annotated[
        str | None,
        Field(
            description="Explicit project name; creates a stub if absent. Omit for no explicit assignment.",
        ),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Field(
            min_length=1,
            description="Stable operation key; reuse unchanged input on retry.",
        ),
    ] = None,
) -> TaskCreationOutcome:
    """Quickly save an action to do as a task and add its board card, without calling another model.

    Prefer for voice capture: 'I need to', 'I should', or 'add a task'. No project is required.
    Preserves original text and explicit project; does not infer entity links,
    schedule reminders or arrange later enrichment.
    Use create_task only when metadata enrichment or a confirmed idea link is requested.
    Reuse the same idempotency_key and fields on retries; report any returned warnings.

    Returns:
        The saved task and any warnings about its board card.
    """
    task = await TaskService().create_task(
        description,
        title=title,
        due=due,
        priority=priority,
        idempotency_key=idempotency_key,
        project=project,
        enrich_metadata=False,
    )
    return task_creation_outcome(task)


def register_task_tools(mcp: FastMCP[None], *, require_oauth: bool = False) -> None:
    """Register task tools on a FastMCP server instance."""
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()

    _ = mcp.tool(**auth_kwargs)(list_tasks)
    _ = mcp.tool(**auth_kwargs)(get_task)
    _ = mcp.tool(**auth_kwargs)(update_task)
    _ = mcp.tool(description=_CREATE_TASK_DESCRIPTION, **auth_kwargs)(create_task)
    _ = mcp.tool(**auth_kwargs)(capture_task)
    _ = mcp.tool(description=_LINK_TASK_TO_CAPTURE_DESCRIPTION, **auth_kwargs)(
        link_task_to_capture,
    )
