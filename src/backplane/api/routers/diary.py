"""Authenticated diary reconciliation and notification endpoints."""

from __future__ import annotations

import uuid  # ruff:ignore[typing-only-standard-library-import] -- The transport resolves annotations at runtime.
from typing import Annotated

from fastapi import APIRouter, Depends

from backplane.api.context_auth import require_context_api_token
from backplane.context.schemas import (
    CapturePrompt,  # ruff:ignore[typing-only-first-party-import] -- The transport resolves annotations at runtime.
)
from backplane.diary.models import (  # ruff:ignore[typing-only-first-party-import] -- The transport resolves annotations at runtime.
    DiarySyncRequest,
    DiarySyncResult,
)
from backplane.diary.service import DiaryReview, DiaryService
from backplane.services.idea_followup import (
    FollowupAvailability,  # ruff:ignore[typing-only-first-party-import] -- The transport resolves annotations at runtime.
)

router = APIRouter(
    prefix="/diary",
    tags=["diary"],
    dependencies=[Depends(require_context_api_token)],
)


def get_diary_service() -> DiaryService:
    """Return the configured diary service."""
    return DiaryService()


Service = Annotated[DiaryService, Depends(get_diary_service)]


@router.post("/sync")
async def sync_diary(request: DiarySyncRequest, service: Service) -> DiarySyncResult:
    """Return the persisted and exported day, with narrative readiness explicit."""
    return await service.sync(request.date, narrative=request.narrative)


@router.post("/reserve")
async def reserve_diary(
    request: FollowupAvailability,
    service: Service,
) -> DiaryReview | None:
    """Return one new daily notification claim, or null."""
    return await service.reserve(request)


@router.post("/{prompt_id}/delivered")
async def deliver_diary(prompt_id: uuid.UUID, service: Service) -> CapturePrompt:
    """Return the prompt after recording notification submission."""
    return await service.submitted(prompt_id)


@router.post("/{prompt_id}/dismiss")
async def dismiss_diary(prompt_id: uuid.UUID, service: Service) -> CapturePrompt:
    """Return the dismissed prompt without confirming observations."""
    return await service.dismiss_review(prompt_id)
