"""Task routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from backplane.api.schemas import (
    CreateTaskRequest,
    CreateTaskResponse,
    LinkCaptureRequest,
    MessageResponse,
)
from backplane.operations.tasks import build_task_capture_messages, task_creation_outcome
from backplane.services import task_catalog, task_updates
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
    return await _create_task_response(request, enrich_metadata=True)


@router.post(
    "/obsidian/tasks/capture",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_task(request: CreateTaskRequest) -> CreateTaskResponse:
    """Return a fast task capture, optionally promoting an exact individual idea."""
    return await _create_task_response(request, enrich_metadata=False)


async def _create_task_response(
    request: CreateTaskRequest,
    *,
    enrich_metadata: bool,
) -> CreateTaskResponse:
    """Return the shared task result without coupling transport adapters."""
    task = await TaskService().create_task(
        request.description,
        title=request.title,
        due=request.due,
        priority=request.priority,
        link_capture_id=request.link_capture_id,
        idempotency_key=request.idempotency_key,
        project=request.project,
        enrich_metadata=enrich_metadata,
    )
    outcome = task_creation_outcome(task)
    return CreateTaskResponse.model_validate(
        outcome.model_dump()
        | {"messages": build_task_capture_messages(outcome, style="api")},
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


@router.get("/obsidian/tasks")
async def list_tasks(
    project: str | None = None,
    task_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[task_catalog.TaskRecord]:
    """Return a bounded task page with exact project and status filters."""
    return await task_catalog.list_tasks(
        project=project,
        status=task_status,
        limit=limit,
        offset=offset,
    )


@router.get("/obsidian/tasks/{task_id}")
async def get_task(task_id: str) -> task_catalog.TaskRecord:
    """Return the exact task ID independently of its filename or title."""
    return await task_catalog.get_task(task_id)


@router.patch("/obsidian/tasks/{task_id}")
async def update_task(
    task_id: str,
    request: task_updates.TaskUpdate,
) -> task_updates.TaskUpdateResult:
    """Return persisted task fields and any recoverable board projection warnings."""
    return await task_updates.update_task(task_id, request)
