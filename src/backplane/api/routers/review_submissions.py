"""Authenticated receipt and recovery endpoints for Home Assistant review replies."""

from __future__ import annotations

import uuid  # ruff:ignore[typing-only-standard-library-import] -- The transport resolves annotations at runtime.
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backplane.api.context_auth import require_context_api_token
from backplane.context.review_submissions import (  # ruff:ignore[typing-only-first-party-import] -- FastAPI resolves annotations at runtime.
    ReviewAttempt,
    ReviewAttemptFinish,
    ReviewSubmission,
    ReviewSubmissionCreate,
)
from backplane.services.review_submissions import ReviewSubmissionService

router = APIRouter(
    prefix="/review-submissions",
    tags=["review inbox"],
    dependencies=[Depends(require_context_api_token)],
)


def get_review_submission_service() -> ReviewSubmissionService:
    """Return the configured durable review inbox."""
    return ReviewSubmissionService()


Service = Annotated[ReviewSubmissionService, Depends(get_review_submission_service)]


@router.post("")
async def receive_reply(
    request: ReviewSubmissionCreate,
    service: Service,
) -> ReviewSubmission:
    """Return a durable receipt before any model processing."""
    return await service.receive(request)


@router.get("")
async def list_replies(
    service: Service,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReviewSubmission]:
    """Return unresolved replies, including abandoned attempts, oldest first."""
    return await service.list_pending(limit=limit, offset=offset)


@router.get("/{submission_id}")
async def get_reply(submission_id: uuid.UUID, service: Service) -> ReviewSubmission:
    """Return exact original wording and factual save status."""
    return await service.get(submission_id)


@router.post("/{submission_id}/begin")
async def begin_reply(submission_id: uuid.UUID, service: Service) -> ReviewAttempt:
    """Return a processing claim, or repair an already pinned export."""
    return await service.begin(submission_id)


@router.post("/{submission_id}/finish")
async def finish_reply(
    submission_id: uuid.UUID,
    request: ReviewAttemptFinish,
    service: Service,
) -> ReviewSubmission:
    """Return the receipt after recording conversational output separately from save status."""
    return await service.finish(submission_id, request)
