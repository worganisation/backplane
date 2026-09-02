"""Daily-note and idea-capture routes."""

from __future__ import annotations

import datetime as dt  # ruff:ignore[typing-only-standard-library-import]  # FastAPI resolves this annotation at runtime

from fastapi import APIRouter, status

from backplane.api.schemas import (
    DailyNoteResponse,
    DailyNoteUpdateRequest,
    IdeaRequest,
    MessageResponse,
    SectionResponse,
)
from backplane.operations.daily_notes import (
    read_daily_note,
    record_idea,
    update_daily_note_section,
)
from backplane.utils import today

router = APIRouter(tags=["daily notes"])


@router.get("/obsidian/daily-note", response_model=DailyNoteResponse)
async def get_daily_note(date: dt.date | None = None) -> DailyNoteResponse:
    """Read a daily note.

    Returns:
        Rendered daily note response.
    """
    return DailyNoteResponse(date=date or today(), markdown=await read_daily_note(date))


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
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["ideas"],
)
async def create_idea(request: IdeaRequest) -> MessageResponse:
    """Record a loose idea in the idea inbox.

    Returns:
        Idea-capture confirmation response.
    """
    return MessageResponse(message=await record_idea(request.idea))
