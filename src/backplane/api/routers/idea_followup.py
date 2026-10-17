"""Authenticated endpoints used by the Home Assistant follow-up automations."""

from __future__ import annotations

import uuid  # ruff:ignore[typing-only-standard-library-import] -- FastAPI inspects runtime annotations.
from typing import Annotated

from fastapi import APIRouter, Depends

from backplane.api.context_auth import require_context_api_token
from backplane.context.schemas import (
    CapturePrompt,
    CapturePromptDismissRequest,
)
from backplane.services.idea_followup import (
    FollowupAvailability,
    IdeaFollowup,
    IdeaFollowupService,
)

router = APIRouter(
    prefix="/idea-followups",
    tags=["idea follow-ups"],
    dependencies=[Depends(require_context_api_token)],
)


def get_idea_followup_service() -> IdeaFollowupService:
    """Return the configured follow-up service."""
    return IdeaFollowupService()


FollowupService = Annotated[IdeaFollowupService, Depends(get_idea_followup_service)]


@router.post("/reserve")
async def reserve_idea_followup(
    request: FollowupAvailability,
    service: FollowupService,
) -> IdeaFollowup | None:
    """Return a new notification claim, or null when no notification should be sent."""
    return await service.reserve(request)


@router.post("/{prompt_id}/delivered")
async def deliver_idea_followup(
    prompt_id: uuid.UUID,
    service: FollowupService,
) -> CapturePrompt:
    """Record notification submission; this is not a phone receipt acknowledgement.

    Returns:
        The updated prompt.
    """
    return await service.mark_submitted(prompt_id)


@router.post("/{prompt_id}/snooze")
async def snooze_idea_followup(
    prompt_id: uuid.UUID,
    service: FollowupService,
) -> CapturePrompt:
    """Return the prompt after recording an idempotent snooze action."""
    return await service.snooze(prompt_id)


@router.post("/{prompt_id}/dismiss")
async def dismiss_idea_followup(
    prompt_id: uuid.UUID,
    service: FollowupService,
) -> CapturePrompt:
    """Return the dismissed prompt, preventing future automatic reminders."""
    return await service.dismiss(prompt_id, CapturePromptDismissRequest())
