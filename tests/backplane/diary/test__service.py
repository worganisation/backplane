"""Real PostgreSQL diary revisions, concurrent review claims and export recovery."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import TYPE_CHECKING

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from backplane.api.app import create_api_app
from backplane.api.routers.diary import get_diary_service
from backplane.context.schemas import (
    CaptureBudgetClass,
    CapturePromptDeliveryRequest,
    CapturePromptEvaluationRequest,
)
from backplane.context.tables import CapturePromptRow, CaptureResponseRow, ContextEventRow
from backplane.diary.models import (
    DiaryDecision,
    DiaryEntry,
    DiaryReviewResponse,
    DiarySnapshot,
)
from backplane.diary.render import facts_text
from backplane.diary.service import DiaryReview, DiaryService
from backplane.mcp.diary import get_diary_review, save_diary_review
from backplane.services.idea_followup import FollowupAvailability
from backplane.services.obsidian import ObsidianService
from backplane.utils import SETTINGS, exc, format_human_date

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.utils import AsyncPath

NOW = dt.datetime(2026, 10, 17, 21, tzinfo=dt.UTC)
DATE = NOW.date()
AVAILABLE = FollowupAvailability(home=True, receptive=True, outside_quiet_hours=True)


def snapshot(steps: float = 1000, minutes: int = 0) -> DiarySnapshot:
    """Provide one completed calendar event and a tentative walking outing."""
    return DiarySnapshot(
        date=DATE,
        collected_at=NOW + dt.timedelta(minutes=minutes),
        metrics={"steps": steps},
        entries=[
            DiaryEntry(
                id="meeting",
                source="calendar.work",
                kind="calendar",
                text="Scheduled: Planning",
                needs_confirmation=True,
            ),
            DiaryEntry(
                id="walk",
                source="person.will",
                kind="outing",
                text="Possible walk",
                needs_confirmation=True,
            ),
        ],
    )


@pytest.fixture
def diary(
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> DiaryService:
    """Provide isolated production storage, an actual vault and deterministic inference."""
    _ = obsidian_vault
    _ = mocker.patch("backplane.diary.service.utc_now", return_value=NOW)
    _ = mocker.patch(
        "backplane.diary.service.generate_narrative",
        return_value="Will recorded his day.",
    )
    return DiaryService(context_session_factory)


async def test_concurrent_revisions_export_and_narrative_cache(
    diary: DiaryService,
    mocker: MockerFixture,
) -> None:
    """Competing workers leave one snapshot; corrections invalidate prose and stale polls lose."""
    await asyncio.gather(*(diary.store_snapshot(snapshot()) for _ in range(5)))
    async with diary._session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ContextEventRow)) == 1
        )
    result = await diary.render(DATE)
    assert not result.narrative_ready
    generation = mocker.patch(
        "backplane.diary.service.generate_narrative",
        return_value="A day of steps.",
    )
    await diary.narrate(DATE)
    await diary.narrate(DATE)
    generation.assert_awaited_once()
    assert (await diary.render(DATE)).narrative_ready

    await diary.store_snapshot(snapshot(950, 1))
    await diary.store_snapshot(snapshot(1200, -1))
    assert not (await diary.render(DATE)).narrative_ready
    async with diary._session_factory() as session:
        row = await diary._latest(session, DATE, "diary_snapshot")
        assert row is not None
        assert DiarySnapshot.model_validate(row.payload).metrics["steps"] == 950
    await diary.store_snapshot(snapshot(1000, 2))
    async with diary._session_factory() as session:
        row = await diary._latest(session, DATE, "diary_snapshot")
        assert row is not None
        assert DiarySnapshot.model_validate(row.payload).metrics["steps"] == 1000


async def test_export_failure_retains_snapshot_for_retry(
    diary: DiaryService,
    mocker: MockerFixture,
) -> None:
    """A failed vault write cannot roll back source persistence or advance success."""
    collector = mocker.patch(
        "backplane.diary.service.collect_day",
        return_value=snapshot(),
    )
    exporter = mocker.patch(
        "backplane.diary.service.export_day",
        side_effect=OSError("disk full"),
    )
    with pytest.raises(OSError, match="disk full"):
        _ = await diary.sync(DATE)
    async with diary._session_factory() as session:
        assert await diary._latest(session, DATE, "diary_snapshot") is not None
    mocker.stop(exporter)
    result = await diary.sync(DATE, narrative=True)
    assert result.narrative_ready
    assert collector.await_count == 2
    async with diary._session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ContextEventRow)
                .where(ContextEventRow.kind == "diary_snapshot"),
            )
            == 1
        )


async def test_narrative_failure_and_changed_input_are_retryable(
    diary: DiaryService,
    mocker: MockerFixture,
) -> None:
    """Failed or obsolete model output never replaces the factual record."""
    await diary.store_snapshot(snapshot())
    generation = mocker.patch(
        "backplane.diary.service.generate_narrative",
        side_effect=TimeoutError,
    )
    await diary.narrate(DATE)
    assert not (await diary.render(DATE)).narrative_ready
    mocker.stop(generation)

    async def change_during_generation(_facts: str) -> str:
        await diary.store_snapshot(snapshot(900, 1))
        return "Stale prose."

    generation = mocker.patch(
        "backplane.diary.service.generate_narrative",
        side_effect=change_during_generation,
    )
    await diary.narrate(DATE)
    assert not (await diary.render(DATE)).narrative_ready
    mocker.stop(generation)
    await diary.narrate(DATE)
    assert (await diary.render(DATE)).narrative_ready


async def test_one_review_concurrent_claims_and_explicit_corrections(
    diary: DiaryService,
) -> None:
    """One claim survives concurrency, while retries and deliberate reversals differ."""
    await diary.store_snapshot(snapshot())
    claims = await asyncio.gather(*(diary.reserve(AVAILABLE) for _ in range(5)))
    reviews = [item for item in claims if item is not None]
    assert len(reviews) == 5
    assert len({review.prompt.id for review in reviews}) == 1
    async with diary._session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(CapturePromptRow)) == 1
        )
    review = reviews[0]
    found = await diary.get_review_for_date(DATE)
    assert found is not None
    assert found.prompt.id == review.prompt.id
    assert await diary.get_review_for_date(DATE - dt.timedelta(days=1)) is None
    assert await diary.get_review() is None
    _ = await diary.submitted(review.prompt.id)
    assert await diary.reserve(AVAILABLE) is None
    assert await diary.get_review() is not None
    for request_id, outcome in [
        ("first", "confirmed"),
        ("second", "dismissed"),
        ("third", "confirmed"),
    ]:
        response = DiaryReviewResponse(
            request_id=request_id,
            decisions=[
                DiaryDecision.model_validate({"entry_id": "meeting", "outcome": outcome}),
            ],
            note="My words.\nSecond line.",
        )
        _ = await diary.save_review(review.prompt.id, response)
        _ = await diary.save_review(review.prompt.id, response)
    async with diary._session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(CaptureResponseRow))
            == 3
        )
        responses = await diary._responses(session, DATE)
    assert "Attended: Planning" in facts_text(snapshot(), responses)
    assert await diary.reserve(AVAILABLE) is None
    _ = await diary.dismiss_review(review.prompt.id)
    assert await diary.get_review() is None


async def test_unsubmitted_review_retry_keeps_pinned_snapshot_and_budget(
    diary: DiaryService,
    mocker: MockerFixture,
) -> None:
    """A failed notification can recover its exact claim despite newer source collection."""
    await diary.store_snapshot(snapshot())
    original = await diary.reserve(AVAILABLE)
    assert original is not None

    await diary.store_snapshot(snapshot(2000, 1))
    retry = await diary.reserve(AVAILABLE)
    assert retry is not None
    assert retry == original
    assert retry.snapshot.metrics["steps"] == 1000
    async with diary._session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(CapturePromptRow)) == 1
        )

    assert await diary.reserve(FollowupAvailability()) is None
    clock = mocker.patch(
        "backplane.diary.service.utc_now",
        return_value=NOW.replace(hour=10),
    )
    assert await diary.reserve(AVAILABLE) is None
    mocker.stop(clock)

    _ = await diary.dismiss_review(original.prompt.id)
    assert await diary.reserve(AVAILABLE) is None


async def test_unsubmitted_retry_respects_other_prompt_delivery_cooldown(
    diary: DiaryService,
    mocker: MockerFixture,
) -> None:
    """Recovering a diary skips its own reservation but respects other interruptions."""
    await diary.store_snapshot(snapshot())
    original = await diary.reserve(AVAILABLE)
    assert original is not None

    other = await diary.evaluate_prompt(
        CapturePromptEvaluationRequest(
            user_id="will",
            source="mood_capture",
            idempotency_key="other-prompt",
            kind="mood",
            budget_class=CaptureBudgetClass.CONTEXT,
            event_ids=original.prompt.event_ids,
            reason="A mood check",
            wording="How are you feeling?",
            scheduled_for=NOW - dt.timedelta(hours=2),
        ),
    )
    assert other.allowed
    _ = await diary.mark_delivered(
        other.prompt.id,
        CapturePromptDeliveryRequest(delivered_at=NOW + dt.timedelta(minutes=5)),
    )

    clock = mocker.patch(
        "backplane.diary.service.utc_now",
        return_value=NOW + dt.timedelta(minutes=10),
    )
    assert await diary.reserve(AVAILABLE) is None

    clock.return_value = NOW + dt.timedelta(minutes=95)
    assert await diary.reserve(AVAILABLE) == original


async def test_expired_scheduled_review_is_not_returned(diary: DiaryService) -> None:
    """An expired scheduled claim cannot be sent or replaced for the same day."""
    await diary.store_snapshot(snapshot())
    original = await diary.reserve(AVAILABLE)
    assert original is not None

    async with diary._session_factory() as session, session.begin():
        row = await session.get(CapturePromptRow, original.prompt.id)
        assert row is not None
        row.expires_at = NOW

    assert await diary.reserve(AVAILABLE) is None


async def test_contextual_question_identity_is_pinned(diary: DiaryService) -> None:
    """Later source changes cannot change which event the notification asked about."""
    current = snapshot()
    meeting = current.entries[0].model_copy(
        update={
            "started_at": NOW - dt.timedelta(hours=2),
            "ended_at": NOW - dt.timedelta(hours=1),
        },
    )
    await diary.store_snapshot(current.model_copy(update={"entries": [meeting]}))
    review = await diary.reserve(AVAILABLE)
    assert review is not None
    assert review.focus_entry_id == "meeting"
    assert review.prompt.wording is not None
    assert "Did you attend" in review.prompt.wording

    await diary.store_snapshot(snapshot(2000, 1))
    assert await diary.reserve(AVAILABLE) == review
    assert await diary.get_review(review.prompt.id) == review


@pytest.mark.parametrize(
    "response",
    [
        DiaryReviewResponse(
            request_id="bad",
            decisions=[DiaryDecision(entry_id="unknown", outcome="confirmed")],
        ),
        DiaryReviewResponse(
            request_id="bad",
            decisions=[DiaryDecision(entry_id="meeting", outcome="dog_walk")],
        ),
        DiaryReviewResponse(
            request_id="bad",
            decisions=[
                DiaryDecision(entry_id="walk", outcome="confirmed"),
                DiaryDecision(entry_id="walk", outcome="dismissed"),
            ],
        ),
        DiaryReviewResponse(request_id="bad"),
    ],
)
async def test_invalid_confirmation_rejected(
    diary: DiaryService,
    response: DiaryReviewResponse,
) -> None:
    """Only valid, explicit decisions about exact review entries are accepted."""
    await diary.store_snapshot(snapshot())
    review = await diary.reserve(AVAILABLE)
    assert review is not None
    _ = await diary.submitted(review.prompt.id)
    with pytest.raises(exc.BadRequestError):
        _ = await diary.save_review(review.prompt.id, response)


async def test_missing_and_unavailable_reviews(
    diary: DiaryService,
    mocker: MockerFixture,
) -> None:
    """Missing data, unavailable owner and daytime collection cannot prompt."""
    assert await diary.reserve(AVAILABLE) is None
    with pytest.raises(exc.NotFoundError):
        _ = await diary.render(DATE)
    await diary.narrate(DATE)
    missing = uuid.uuid4()
    assert await diary.get_review(missing) is None
    for operation in (diary.submitted, diary.dismiss_review):
        with pytest.raises(exc.NotFoundError):
            _ = await operation(missing)
    with pytest.raises(exc.NotFoundError):
        _ = await diary.save_review(
            missing,
            DiaryReviewResponse(request_id="missing", note="Test"),
        )
    await diary.store_snapshot(snapshot())
    assert await diary.reserve(FollowupAvailability()) is None
    _ = mocker.patch("backplane.diary.service.utc_now", return_value=NOW.replace(hour=10))
    assert await diary.reserve(AVAILABLE) is None


async def test_preserves_manual_sections_and_multiline_notes(diary: DiaryService) -> None:
    """Repeated generated writes leave unrelated sections and properties intact."""
    async with ObsidianService().daily_note(
        date=DATE,
        create_if_not_exists=True,
        read_only=False,
    ) as note:
        section = note.get_section(
            (format_human_date(DATE), "Diary"),
            create_if_not_exists=True,
        )
        section.replace_content("A handwritten memory.")
        note.frontmatter["personal"] = "keep"
    await diary.store_snapshot(snapshot())
    review = await diary.reserve(AVAILABLE)
    assert review is not None
    _ = await diary.submitted(review.prompt.id)
    _ = await diary.save_review(
        review.prompt.id,
        DiaryReviewResponse(
            request_id="notes",
            note="My words.\nSecond line.",
            decisions=[DiaryDecision(entry_id="walk", outcome="dog_walk")],
        ),
    )
    _ = await diary.render(DATE)
    async with ObsidianService().daily_note(date=DATE, read_only=True) as note:
        assert note.frontmatter["personal"] == "keep"
        assert note.frontmatter["diary_steps"] == 1000
        assert (
            note.get_section((format_human_date(DATE), "Diary")).content
            == "A handwritten memory."
        )
        generated = note.get_section((
            format_human_date(DATE),
            "Automatic diary",
        )).render()
        assert generated.count("### Qwen narrative") == 1
        assert "Dog walk" in generated
        assert "My words." in generated
        assert "Second line." in generated


async def test_authenticated_api_and_mcp_review_flow(
    diary: DiaryService,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """HA HTTP callbacks and Assist tools share the same durable workflow."""
    api_app = create_api_app()
    api_app.dependency_overrides[get_diary_service] = lambda: diary
    monkeypatch.setattr(SETTINGS, "context_api_token", SecretStr("test-token"))
    _ = mocker.patch("backplane.mcp.diary.DiaryService", return_value=diary)
    _ = mocker.patch("backplane.diary.service.collect_day", return_value=snapshot())
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=api_app),
        base_url="http://test",
    ) as client:
        assert (await client.post("/diary/reserve", json={})).status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        result = await client.post(
            "/diary/sync",
            json={"date": DATE.isoformat(), "narrative": True},
        )
        assert result.status_code == 200
        result = await client.post("/diary/reserve", json=AVAILABLE.model_dump())
        review = DiaryReview.model_validate(result.json())
        assert (
            await client.post(f"/diary/{review.prompt.id}/delivered")
        ).status_code == 200
        assert await get_diary_review() is not None
        assert "saved" in await save_diary_review(
            review.prompt.id,
            DiaryReviewResponse(request_id="voice", note="A good day."),
        )
        assert (
            await client.post(f"/diary/{review.prompt.id}/dismiss")
        ).status_code == 200
