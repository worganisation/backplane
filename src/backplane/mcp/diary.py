"""Assist tools for explicit daily diary confirmation."""

from __future__ import annotations

import datetime as dt  # ruff: ignore[typing-only-standard-library-import] -- The transport resolves dates at runtime.
import uuid  # ruff:ignore[typing-only-standard-library-import] -- The transport resolves annotations at runtime.
from typing import TYPE_CHECKING

from backplane.diary.history import DiaryDay, DiaryHistoryService, DiaryPeriod
from backplane.diary.models import (
    DiaryReviewResponse,  # ruff:ignore[typing-only-first-party-import] -- The transport resolves annotations at runtime.
)
from backplane.diary.service import DiaryReview, DiaryService
from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def get_diary_review(prompt_id: uuid.UUID | None = None) -> DiaryReview | None:
    """Read the exact daily review before discussing the diary notification.

    Omit prompt_id for the latest delivered review. If absent, ask which day the user
    means. Ask one combined question about unresolved events and possible walks.
    Calendar entries are scheduled, never evidence of attendance. Consult responses
    for already answered IDs; do not ask again. Mood notes are the user's words.

    Returns:
        Exact prompt and entry IDs, source facts and prior explicit responses.
    """
    return await DiaryService().get_review(prompt_id)


async def save_diary_review(prompt_id: uuid.UUID, response: DiaryReviewResponse) -> str:
    """Save explicit user decisions using exact IDs from get_diary_review.

    Give each deliberate submission a unique request_id; reuse it only for retries
    of that exact submission. A later correction needs a new request_id.
    Only confirm what the user explicitly says. A calendar confirmation means attended;
    an outing confirmation means an outing, not a dog walk. Use dog_walk only when
    explicitly confirmed, dismissed for incorrect suggestions. Keep additional detail
    verbatim in note. Never translate silence or a general acknowledgement into
    attendance or a dog walk. Confirm success only after this tool returns.

    Returns:
        Acknowledgement after durable storage and successful Obsidian export.
    """
    return await DiaryService().save_review(prompt_id, response)


def register_diary_tools(mcp: FastMCP[None], *, require_oauth: bool = False) -> None:
    """Register daily review tools with the same access policy as capture tools."""
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()
    for tool in (
        get_diary_review,
        save_diary_review,
        get_diary_day,
        summarize_diary_period,
    ):
        _ = mcp.tool(**auth_kwargs)(tool)


async def get_diary_day(date: dt.date) -> DiaryDay | None:
    """Read latest collected observations and review notes for a date without collecting.

    Manual Diary/Journal text is available through get_daily_note. Preserve source
    uncertainty and missing measurements; a calendar entry is not proof of attendance.

    Returns:
        Automatic diary data, or null when the day was never collected.
    """
    return await DiaryHistoryService().get_day(date)


async def summarize_diary_period(start: dt.date, end: dt.date) -> DiaryPeriod:
    """Summarize 1 to 366 inclusive days of recorded metrics with coverage counts.

    Missing days are not zero. Report observed-day coverage with averages and totals.
    Weight is not additive. Current-day values are partial. This never queries live
    sources or generates prose. Use get_diary_day for events and get_daily_note for text.

    Returns:
        Deterministic metrics and explicit gaps from latest collected snapshots.
    """
    return await DiaryHistoryService().summarize(start, end)
