"""Task routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from backplane.api.schemas import (
    CreateTaskRequest,
    CreateTaskResponse,
    LinkCaptureRequest,
    MessageResponse,
)
from backplane.operations.tasks import build_task_capture_messages, task_creation_outcome
from backplane.services.tasks import TaskService

router = APIRouter(tags=["tasks"])


@router.post(
    "/obsidian/tasks",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(request: CreateTaskRequest) -> CreateTaskResponse:
    """Create a structured task note.

    Returns:
        Created task response.
    """
    task = await TaskService().create_task(
        request.description,
        title=request.title,
        due=request.due,
        priority=request.priority,
        link_capture_id=request.link_capture_id,
    )
    outcome = task_creation_outcome(task)
    return CreateTaskResponse(
        metadata=outcome.metadata,
        slug=outcome.slug,
        matched_capture_id=outcome.matched_capture_id,
        candidate_captures=outcome.candidate_captures,
        domains_created=outcome.domains_created,
        resources_created=outcome.resources_created,
        projects_created=outcome.projects_created,
        people_created=outcome.people_created,
        messages=build_task_capture_messages(outcome, style="api"),
    )


@router.post(
    "/obsidian/tasks/{task_slug}/link-capture",
    response_model=MessageResponse,
)
async def link_task_to_capture(
    task_slug: Annotated[str, Path(min_length=1)],
    request: LinkCaptureRequest,
) -> MessageResponse:
    """Link an existing task to a confirmed inbox capture.

    Returns:
        Task-capture link confirmation.
    """
    return MessageResponse(
        message=await TaskService().link_capture(task_slug, request.capture_id),
    )
