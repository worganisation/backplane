"""Daily-note and idea-capture routes."""

from __future__ import annotations

import datetime as dt  # ruff:ignore[typing-only-standard-library-import]  # FastAPI resolves this annotation at runtime
from typing import Annotated

from fastapi import APIRouter, Query, status

from backplane.api.schemas import (
    DailyNoteResponse,
    DailyNoteUpdateRequest,
    IdeaRequest,
    RecordIdeaResponse,
    SectionResponse,
)
from backplane.operations.daily_notes import (
    read_daily_note,
    update_daily_note_section,
)
from backplane.services.ideas import IdeaCapture, IdeaService
from backplane.utils import today

router = APIRouter(tags=["daily notes"])


@router.get("/obsidian/daily-note", response_model=DailyNoteResponse)
async def get_daily_note(date: dt.date | None = None) -> DailyNoteResponse:
    """Read a daily note.

    Returns:
        Rendered daily note response.
    """
    resolved_date = date or today()
    return DailyNoteResponse(
        date=resolved_date,
        markdown=await read_daily_note(resolved_date),
    )


@router.patch("/obsidian/daily-note", response_model=SectionResponse)
async def update_daily_note(request: DailyNoteUpdateRequest) -> SectionResponse:
    """Update a named section in a daily note.

    Returns:
        Rendered updated section response.
    """
    return SectionResponse(
        markdown=await update_daily_note_section(
            heading_path=tuple(request.heading_path),
            content=request.content,
            mode=request.mode,
            create_section_if_not_exists=request.create_section_if_not_exists,
            date=request.date,
        ),
    )


@router.post(
    "/obsidian/ideas",
    response_model=RecordIdeaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["ideas"],
)
async def create_idea(request: IdeaRequest) -> RecordIdeaResponse:
    """Record a loose idea in the idea inbox.

    Returns:
        Idea-capture confirmation response.
    """
    capture = await IdeaService.record(
        request.idea,
        idempotency_key=request.idempotency_key,
    )
    return RecordIdeaResponse(message="Idea recorded successfully.", id=capture.id)


@router.get("/obsidian/ideas", tags=["ideas"])
async def list_ideas(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[IdeaCapture]:
    """List a bounded page of idea captures, newest first.

    Returns:
        A page of capture records.
    """
    return await IdeaService.list_ideas(limit=limit, offset=offset)


@router.get("/obsidian/ideas/{capture_id}", tags=["ideas"])
async def get_idea(capture_id: str) -> IdeaCapture:
    """Read an individual idea or legacy minute group by stable ID.

    Returns:
        The capture record and original text.
    """
    return await IdeaService.get_idea(capture_id)
