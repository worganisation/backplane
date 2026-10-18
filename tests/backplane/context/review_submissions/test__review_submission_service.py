"""Durable receipt, concurrency fencing and real export recovery regressions."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from backplane.context.review_submissions import (
    ReviewAttempt,
    ReviewAttemptFinish,
    ReviewResolution,
    ReviewSubmissionCreate,
)
from backplane.context.tables import CapturePromptRow, CaptureResponseRow
from backplane.diary.models import DiaryDecision
from backplane.diary.render import reviewed_entries
from backplane.diary.service import DiaryService
from backplane.services.idea_followup import FollowupAvailability, IdeaFollowupService
from backplane.services.ideas import IdeaService
from backplane.utils import exc, resolve_under_root

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.services.review_submissions import ReviewSubmissionService


async def test__receive__concurrent_retries_preserve_text_without_responding(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    context_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Concurrent receipts produce one pending item without confirming a diary event."""
    receipts = await asyncio.gather(
        *(submissions.receive(sample_review_request) for _ in range(5)),
    )

    assert len({receipt.id for receipt in receipts}) == 1
    assert all(receipt.text == sample_review_request.text for receipt in receipts)
    assert all(receipt.status == "pending" for receipt in receipts)
    async with context_session_factory() as session:
        prompt = await session.get(CapturePromptRow, sample_review_request.prompt_id)
        assert prompt is not None
        assert prompt.status == "delivered"
        assert (
            await session.scalar(select(func.count()).select_from(CaptureResponseRow))
            == 0
        )


@pytest.mark.parametrize("field", ["text", "conversation_id"])
async def test__receive__rejects_conflicting_operation_key(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    field: str,
) -> None:
    """A received operation cannot silently acquire different text or conversation context."""
    receipt = await submissions.receive(sample_review_request)
    with pytest.raises(exc.ConflictError):
        _ = await submissions.receive(
            sample_review_request.model_copy(update={field: "different"}),
        )

    assert await submissions.get(receipt.id) == receipt


async def test__begin__only_one_concurrent_claim_wins(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
) -> None:
    """Independent database transactions cannot both acquire the same processing lease."""
    receipt = await submissions.receive(sample_review_request)
    results = await asyncio.gather(
        *(submissions.begin(receipt.id) for _ in range(4)),
        return_exceptions=True,
    )

    assert sum(isinstance(result, ReviewAttempt) for result in results) == 1
    assert sum(isinstance(result, exc.ConflictError) for result in results) == 3


async def test__receive__rejects_wrong_destination_kind(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
) -> None:
    """A diary prompt cannot be submitted as an idea destination."""
    with pytest.raises(exc.NotFoundError):
        _ = await submissions.receive(
            sample_review_request.model_copy(update={"kind": "idea"}),
        )

    assert await submissions.list_pending() == []


async def test__finish__speech_is_not_proof_of_a_save(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
) -> None:
    """An assistant claiming success leaves an unpersisted interpretation unresolved."""
    receipt = await submissions.receive(sample_review_request)
    attempt = await submissions.begin(receipt.id)
    assert attempt.submission.attempt_id is not None
    finished = await submissions.finish(
        receipt.id,
        ReviewAttemptFinish(
            attempt_id=attempt.submission.attempt_id,
            assistant_reply="Everything is saved!",
            conversation_id="conversation-followup",
        ),
    )

    assert finished.status == "needs_attention"
    assert finished.result is None
    assert finished.resolution is None
    assert finished.assistant_reply == "Everything is saved!"
    assert finished.conversation_id == "conversation-followup"
    assert [item.id for item in await submissions.list_pending()] == [receipt.id]


async def test__lease__stale_save_and_finish_cannot_change_replacement(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    review_now: dt.datetime,
    mocker: MockerFixture,
) -> None:
    """Expired owners cannot save or overwrite the context of a new attempt."""
    receipt = await submissions.receive(sample_review_request)
    old = await submissions.begin(receipt.id)
    assert old.submission.attempt_id is not None
    _ = mocker.patch(
        "backplane.services.review_submissions.utc_now",
        return_value=review_now + dt.timedelta(minutes=11),
    )
    current = await submissions.begin(receipt.id)

    with pytest.raises(exc.ConflictError):
        _ = await submissions.save(
            receipt.id,
            old.submission.attempt_id,
            ReviewResolution(),
        )

    finished = await submissions.finish(
        receipt.id,
        ReviewAttemptFinish(
            attempt_id=old.submission.attempt_id,
            assistant_reply="Old reply",
            conversation_id="old-conversation",
        ),
    )
    assert finished == current.submission


async def test__save__invalid_decision_does_not_pin_resolution(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
) -> None:
    """A fabricated entry identifier cannot freeze an invalid interpretation."""
    receipt = await submissions.receive(sample_review_request)
    attempt = await submissions.begin(receipt.id)
    assert attempt.submission.attempt_id is not None

    with pytest.raises(exc.BadRequestError):
        _ = await submissions.save(
            receipt.id,
            attempt.submission.attempt_id,
            ReviewResolution(
                decisions=[DiaryDecision(entry_id="invented", outcome="confirmed")],
            ),
        )

    unresolved = await submissions.get(receipt.id)
    assert unresolved.resolution is None
    assert unresolved.status == "processing"


async def test__begin__repairs_pinned_export_without_reinterpreting(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    context_session_factory: async_sessionmaker[AsyncSession],
    mocker: MockerFixture,
) -> None:
    """A diary response survives failed export and retries exactly once into the vault."""
    receipt = await submissions.receive(sample_review_request)
    attempt = await submissions.begin(receipt.id)
    assert attempt.submission.attempt_id is not None
    resolution = ReviewResolution(
        decisions=[DiaryDecision(entry_id="meeting", outcome="confirmed")],
    )
    mock_render = mocker.patch(
        "backplane.diary.service.DiaryService.render",
        side_effect=OSError("disk full"),
    )
    with pytest.raises(OSError, match="disk full"):
        _ = await submissions.save(receipt.id, attempt.submission.attempt_id, resolution)

    failed = await submissions.get(receipt.id)
    assert failed.resolution == resolution
    assert failed.status == "needs_attention"
    async with context_session_factory() as session:
        responses = list((await session.scalars(select(CaptureResponseRow))).all())
        assert len(responses) == 1
        assert responses[0].text == sample_review_request.text
        assert responses[0].idempotency_key == str(receipt.id)

    mocker.stop(mock_render)
    repaired = await submissions.begin(receipt.id)
    assert repaired.request_text is None
    assert repaired.submission.status == "saved"
    assert repaired.submission.resolution == resolution
    assert await submissions.list_pending() == []
    assert (await submissions.begin(receipt.id)).submission == repaired.submission
    assert (
        await submissions.save(receipt.id, uuid.uuid4(), ReviewResolution())
        == repaired.submission
    )
    async with context_session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(CaptureResponseRow))
            == 1
        )


async def test__begin__retains_expired_prompt_reply(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    context_session_factory: async_sessionmaker[AsyncSession],
    review_now: dt.datetime,
) -> None:
    """An expired destination remains recoverable without being replaced by another prompt."""
    async with context_session_factory() as session, session.begin():
        prompt = await session.get(CapturePromptRow, sample_review_request.prompt_id)
        assert prompt is not None
        prompt.expires_at = review_now - dt.timedelta(seconds=1)

    receipt = await submissions.receive(sample_review_request)
    attempt = await submissions.begin(receipt.id)

    assert attempt.request_text is None
    assert attempt.submission.status == "needs_attention"
    assert attempt.submission.text == sample_review_request.text
    assert attempt.submission.prompt_id == sample_review_request.prompt_id


async def test__save__idea_uses_exact_prompt_and_original_text(
    submissions: ReviewSubmissionService,
    context_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An idea reply exports against its server-resolved capture and preserves raw wording."""
    idea = await IdeaService.record("Build a rainwater monitor")
    followups = IdeaFollowupService(context_session_factory)
    followup = await followups.reserve(
        FollowupAvailability(home=True, receptive=True, outside_quiet_hours=True),
    )
    assert followup is not None
    _ = await followups.mark_submitted(followup.prompt.id)
    request = ReviewSubmissionCreate(
        idempotency_key="idea-reply",
        kind="idea",
        prompt_id=followup.prompt.id,
        text="  Use a float sensor.\nKeep my wording.  ",
    )
    receipt = await submissions.receive(request)
    attempt = await submissions.begin(receipt.id)
    assert attempt.submission.attempt_id is not None

    with pytest.raises(exc.BadRequestError):
        _ = await submissions.save(
            receipt.id,
            attempt.submission.attempt_id,
            ReviewResolution(
                decisions=[DiaryDecision(entry_id="meeting", outcome="confirmed")],
            ),
        )

    saved = await submissions.save(
        receipt.id,
        attempt.submission.attempt_id,
        ReviewResolution(),
    )
    assert saved.status == "saved"
    assert saved.result is not None
    content = await (await resolve_under_root(saved.result[2:-2] + ".md")).read_text()
    assert request.text in content
    assert f"capture_id: {idea.id}" in content
    assert f"prompt_id: {followup.prompt.id}" in content


async def test__retry__earlier_reply_cannot_reverse_later_correction(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    context_session_factory: async_sessionmaker[AsyncSession],
    mocker: MockerFixture,
) -> None:
    """Delayed persistence orders decisions by original receipt rather than retry time."""
    first = await submissions.receive(sample_review_request)
    first_attempt = await submissions.begin(first.id)
    assert first_attempt.submission.attempt_id is not None
    mock_respond = mocker.patch.object(
        DiaryService,
        "respond",
        side_effect=OSError("database unavailable"),
    )
    with pytest.raises(OSError, match="database unavailable"):
        _ = await submissions.save(
            first.id,
            first_attempt.submission.attempt_id,
            ReviewResolution(
                decisions=[DiaryDecision(entry_id="meeting", outcome="confirmed")],
            ),
        )

    mocker.stop(mock_respond)
    second = await submissions.receive(
        sample_review_request.model_copy(
            update={"idempotency_key": "correction", "text": "Actually, I missed it."},
        ),
    )
    assert first.created_at < second.created_at
    second_attempt = await submissions.begin(second.id)
    assert second_attempt.submission.attempt_id is not None
    corrected = await submissions.save(
        second.id,
        second_attempt.submission.attempt_id,
        ReviewResolution(
            decisions=[DiaryDecision(entry_id="meeting", outcome="dismissed")],
        ),
    )
    assert corrected.status == "saved"

    repaired = await submissions.begin(first.id)
    assert repaired.request_text is None
    assert repaired.submission.status == "saved"
    review = await DiaryService(context_session_factory).get_review(first.prompt_id)
    assert review is not None
    assert reviewed_entries(review.snapshot, review.responses) == []
    async with context_session_factory() as session:
        responses = list(
            (
                await session.scalars(
                    select(CaptureResponseRow).order_by(CaptureResponseRow.created_at),
                )
            ).all(),
        )

    assert [response.idempotency_key for response in responses] == [
        str(second.id),
        str(first.id),
    ]
    assert [response.responded_at for response in responses] == [
        second.created_at,
        first.created_at,
    ]


@pytest.mark.parametrize("save_first", [False, True])
async def test__archive__preserves_receipt_and_save_truth(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    *,
    save_first: bool,
) -> None:
    """Archiving hides pending work without deleting text or changing a completed save."""
    receipt = await submissions.receive(sample_review_request)
    if save_first:
        attempt = await submissions.begin(receipt.id)
        assert attempt.submission.attempt_id is not None
        receipt = await submissions.save(
            receipt.id,
            attempt.submission.attempt_id,
            ReviewResolution(),
        )

    archived = await submissions.archive(receipt.id)

    assert archived.archived_at is not None
    assert archived.status == receipt.status
    assert archived.text == receipt.text
    assert archived.result == receipt.result
    assert await submissions.get(receipt.id) == archived
    assert await submissions.list_pending() == []
    assert await submissions.archive(receipt.id) == archived
    attempt = await submissions.begin(receipt.id)
    assert attempt.request_text is None
    assert attempt.submission == archived


async def test__archive__rejects_active_processing(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
) -> None:
    """Archiving cannot race an in-flight save under an active processing lease."""
    receipt = await submissions.receive(sample_review_request)
    attempt = await submissions.begin(receipt.id)

    with pytest.raises(exc.ConflictError):
        _ = await submissions.archive(receipt.id)

    assert await submissions.get(receipt.id) == attempt.submission


async def test__archive__expired_attempt_cannot_save_after_archiving(
    submissions: ReviewSubmissionService,
    sample_review_request: ReviewSubmissionCreate,
    review_now: dt.datetime,
    mocker: MockerFixture,
) -> None:
    """An abandoned attempt stays archived when its delayed model tries to save."""
    receipt = await submissions.receive(sample_review_request)
    attempt = await submissions.begin(receipt.id)
    assert attempt.submission.attempt_id is not None
    _ = mocker.patch(
        "backplane.services.review_submissions.utc_now",
        return_value=review_now + dt.timedelta(minutes=11),
    )
    archived = await submissions.archive(receipt.id)
    assert archived.archived_at is not None

    with pytest.raises(exc.ConflictError):
        _ = await submissions.save(
            receipt.id,
            attempt.submission.attempt_id,
            ReviewResolution(),
        )

    assert await submissions.get(receipt.id) == archived
    assert await submissions.list_pending() == []
    assert (await submissions.begin(receipt.id)).request_text is None
