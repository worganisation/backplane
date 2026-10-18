"""Real database and vault fixtures for durable notification replies."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from backplane.context.review_submissions import ReviewSubmissionCreate
from backplane.diary.models import DiaryEntry, DiarySnapshot
from backplane.diary.service import DiaryService
from backplane.services.idea_followup import FollowupAvailability
from backplane.services.review_submissions import ReviewSubmissionService

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.utils import AsyncPath


@pytest.fixture
def review_now(mocker: MockerFixture) -> dt.datetime:
    """Keep prompt expiry and attempt leases on the same deterministic clock."""
    now = dt.datetime(2026, 10, 18, 21, tzinfo=dt.UTC)
    for module in (
        "backplane.diary.service",
        "backplane.services.review_submissions",
        "backplane.services.idea_followup",
    ):
        _ = mocker.patch(f"{module}.utc_now", return_value=now)

    return now


@pytest.fixture
def submissions(
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
    review_now: dt.datetime,
    mocker: MockerFixture,
) -> ReviewSubmissionService:
    """Bind production receipt operations to disposable PostgreSQL and a real vault."""
    _ = obsidian_vault, review_now
    _ = mocker.patch(
        "backplane.diary.service.generate_narrative",
        return_value="Will attended his meeting.",
    )
    return ReviewSubmissionService(context_session_factory)


@pytest.fixture
async def sample_review_request(
    context_session_factory: async_sessionmaker[AsyncSession],
    submissions: ReviewSubmissionService,
    review_now: dt.datetime,
) -> ReviewSubmissionCreate:
    """Create a delivered diary prompt with one genuine confirmable observation."""
    _ = submissions
    diary = DiaryService(context_session_factory)
    await diary.store_snapshot(
        DiarySnapshot(
            date=review_now.date(),
            collected_at=review_now,
            entries=[
                DiaryEntry(
                    id="meeting",
                    source="calendar.personal",
                    kind="calendar",
                    text="Planning meeting",
                    needs_confirmation=True,
                ),
            ],
        ),
    )
    review = await diary.reserve(
        FollowupAvailability(home=True, receptive=True, outside_quiet_hours=True),
    )
    assert review is not None
    _ = await diary.submitted(review.prompt.id)

    return ReviewSubmissionCreate(
        idempotency_key="phone-reply-1",
        prompt_id=review.prompt.id,
        kind="diary",
        text="  I attended the meeting.\nKeep my exact words.  ",
        conversation_id="conversation-original",
    )
