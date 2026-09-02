"""Authenticated context-capture REST routes."""

from __future__ import annotations

import datetime as dt  # ruff:ignore[typing-only-standard-library-import]  # FastAPI runtime annotations
import uuid  # ruff:ignore[typing-only-standard-library-import]  # FastAPI runtime annotations
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backplane.api.context_auth import require_context_api_token
from backplane.context.database import context_session_factory
from backplane.context.schemas import (
    CapturePolicy,
    CapturePolicyUpdate,
    CapturePrompt,
    CapturePromptDeliveryRequest,
    CapturePromptDismissRequest,
    CapturePromptEvaluationRequest,
    CapturePromptEvaluationResult,
    CapturePromptExpireRequest,
    CapturePromptResponseRequest,
    CapturePromptResponseResult,
    ContextEventBatchCreate,
    ContextEventBatchResult,
    ContextEventCreate,
    ContextEventList,
    ContextEventResult,
)
from backplane.services.context_capture import ContextCaptureService

router = APIRouter(
    tags=["context capture"],
    dependencies=[Depends(require_context_api_token)],
)


def get_context_capture_service() -> ContextCaptureService:
    """Build the context service used by REST handlers.

    Returns:
        Context-capture service bound to the configured database.
    """
    return ContextCaptureService(context_session_factory())


ContextService = Annotated[ContextCaptureService, Depends(get_context_capture_service)]


@router.post("/context/events", response_model=ContextEventResult)
async def ingest_context_event(
    request: ContextEventCreate,
    service: ContextService,
) -> ContextEventResult:
    """Ingest one source event idempotently.

    Returns:
        Canonical event and whether it was newly created.
    """
    return await service.ingest_event(request)


@router.post("/context/events/batch", response_model=ContextEventBatchResult)
async def ingest_context_events(
    request: ContextEventBatchCreate,
    service: ContextService,
) -> ContextEventBatchResult:
    """Ingest an event batch atomically.

    Returns:
        Ordered results for every event in the batch.
    """
    return await service.ingest_events(request)


@router.get("/context", response_model=ContextEventList)
async def get_context(
    service: ContextService,
    user_id: Annotated[str, Query(min_length=1, max_length=128)],
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    kinds: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ContextEventList:
    """Return a bounded chronological context window."""
    return ContextEventList(
        events=await service.list_events(
            user_id=user_id,
            start=start,
            end=end,
            kinds=kinds,
            limit=limit,
        ),
    )


@router.get("/capture-policies/{user_id}", response_model=CapturePolicy)
async def get_capture_policy(user_id: str, service: ContextService) -> CapturePolicy:
    """Return a user's capture policy, creating defaults if absent."""
    return await service.get_policy(user_id)


@router.put("/capture-policies/{user_id}", response_model=CapturePolicy)
async def update_capture_policy(
    user_id: str,
    request: CapturePolicyUpdate,
    service: ContextService,
) -> CapturePolicy:
    """Replace mutable capture-policy values.

    Returns:
        Updated canonical policy.
    """
    return await service.update_policy(user_id, request)


@router.post(
    "/capture-prompts/evaluate",
    response_model=CapturePromptEvaluationResult,
)
async def evaluate_capture_prompt(
    request: CapturePromptEvaluationRequest,
    service: ContextService,
) -> CapturePromptEvaluationResult:
    """Evaluate a prompt candidate under global policy.

    Returns:
        Deterministic decision and canonical prompt.
    """
    return await service.evaluate_prompt(request)


@router.post(
    "/capture-prompts/{prompt_id}/delivered",
    response_model=CapturePrompt,
)
async def mark_capture_prompt_delivered(
    prompt_id: uuid.UUID,
    request: CapturePromptDeliveryRequest,
    service: ContextService,
) -> CapturePrompt:
    """Record successful prompt delivery.

    Returns:
        Updated canonical prompt.
    """
    return await service.mark_delivered(prompt_id, request)


@router.post(
    "/capture-prompts/{prompt_id}/respond",
    response_model=CapturePromptResponseResult,
)
async def respond_to_capture_prompt(
    prompt_id: uuid.UUID,
    request: CapturePromptResponseRequest,
    service: ContextService,
) -> CapturePromptResponseResult:
    """Append an idempotent response observation.

    Returns:
        Updated prompt and immutable response.
    """
    return await service.respond(prompt_id, request)


@router.post(
    "/capture-prompts/{prompt_id}/dismiss",
    response_model=CapturePrompt,
)
async def dismiss_capture_prompt(
    prompt_id: uuid.UUID,
    request: CapturePromptDismissRequest,
    service: ContextService,
) -> CapturePrompt:
    """Record prompt dismissal.

    Returns:
        Updated canonical prompt.
    """
    return await service.dismiss(prompt_id, request)


@router.post(
    "/capture-prompts/{prompt_id}/expire",
    response_model=CapturePrompt,
)
async def expire_capture_prompt(
    prompt_id: uuid.UUID,
    request: CapturePromptExpireRequest,
    service: ContextService,
) -> CapturePrompt:
    """Record prompt expiry.

    Returns:
        Updated canonical prompt.
    """
    return await service.expire(prompt_id, request)
