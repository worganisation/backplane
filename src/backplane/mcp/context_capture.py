"""MCP tools for canonical context capture."""

from __future__ import annotations

import datetime as dt  # ruff:ignore[typing-only-standard-library-import]  # FastMCP runtime annotations
import uuid  # ruff:ignore[typing-only-standard-library-import]  # FastMCP runtime annotations
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from backplane.context.schemas import (
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
from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs
from backplane.services.context_capture import ContextCaptureService

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def record_context_event(request: ContextEventCreate) -> ContextEventResult:
    """Return the canonical result after recording one contextual observation."""
    return await ContextCaptureService().ingest_event(request)


async def record_context_events(
    request: ContextEventBatchCreate,
) -> ContextEventBatchResult:
    """Return ordered results after recording an observation batch atomically."""
    return await ContextCaptureService().ingest_events(request)


async def find_context_events(
    *,
    user_id: Annotated[str, Field(min_length=1, max_length=128)],
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    kinds: list[str] | None = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> ContextEventList:
    """Return a bounded chronological context window."""
    return ContextEventList(
        events=await ContextCaptureService().list_events(
            user_id=user_id,
            start=start,
            end=end,
            kinds=kinds,
            limit=limit,
        ),
    )


async def evaluate_capture_prompt(
    request: CapturePromptEvaluationRequest,
) -> CapturePromptEvaluationResult:
    """Return the deterministic global-policy decision for a prompt candidate."""
    return await ContextCaptureService().evaluate_prompt(request)


async def mark_capture_prompt_delivered(
    *,
    prompt_id: uuid.UUID,
    request: CapturePromptDeliveryRequest,
) -> CapturePrompt:
    """Return the canonical prompt after recording successful delivery."""
    return await ContextCaptureService().mark_delivered(prompt_id, request)


async def respond_to_capture_prompt(
    *,
    prompt_id: uuid.UUID,
    request: CapturePromptResponseRequest,
) -> CapturePromptResponseResult:
    """Return the prompt and immutable response after an idempotent append."""
    return await ContextCaptureService().respond(prompt_id, request)


async def dismiss_capture_prompt(
    *,
    prompt_id: uuid.UUID,
    request: CapturePromptDismissRequest,
) -> CapturePrompt:
    """Return the canonical prompt after dismissing it."""
    return await ContextCaptureService().dismiss(prompt_id, request)


async def expire_capture_prompt(
    *,
    prompt_id: uuid.UUID,
    request: CapturePromptExpireRequest,
) -> CapturePrompt:
    """Return the canonical prompt after expiring it."""
    return await ContextCaptureService().expire(prompt_id, request)


def register_context_capture_tools(
    mcp: FastMCP[None],
    *,
    require_oauth: bool = False,
) -> None:
    """Register context-capture tools on a FastMCP server."""
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()
    for tool in (
        record_context_event,
        record_context_events,
        find_context_events,
        evaluate_capture_prompt,
        mark_capture_prompt_delivered,
        respond_to_capture_prompt,
        dismiss_capture_prompt,
        expire_capture_prompt,
    ):
        _ = mcp.tool(**auth_kwargs)(tool)
