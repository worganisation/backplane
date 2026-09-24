"""Behavioral tests for the canonical context-capture service."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

import pytest

from backplane.context.schemas import (
    CaptureBudgetClass,
    CaptureDecisionReason,
    CapturePolicyUpdate,
    CapturePromptDeliveryRequest,
    CapturePromptDismissRequest,
    CapturePromptEvaluationRequest,
    CapturePromptExpireRequest,
    CapturePromptResponseRequest,
    CapturePromptStatus,
    ContextEventBatchCreate,
    ContextEventCreate,
    ContextEventStatus,
)
from backplane.context.tables import CapturePolicyRow
from backplane.utils import exc

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.services.context_capture import ContextCaptureService


OCCURRED_AT = dt.datetime(2026, 9, 2, 8, tzinfo=dt.UTC)


def _event(
    key: str,
    *,
    source: str = "appdaemon",
    correlation_key: str | None = None,
    supersedes_event_id: uuid.UUID | None = None,
    confidence: float = 1.0,
    status: ContextEventStatus = ContextEventStatus.OBSERVED,
    timezone: str = "Europe/London",
) -> ContextEventCreate:
    return ContextEventCreate(
        user_id="will",
        source=source,
        source_event_id=f"source-{key}",
        correlation_key=correlation_key,
        idempotency_key=key,
        kind="calendar.event.ended",
        occurred_at=OCCURRED_AT,
        timezone=timezone,
        confidence=confidence,
        status=status,
        summary=f"Event {key}",
        payload={"key": key},
        provenance={"adapter": source},
        supersedes_event_id=supersedes_event_id,
    )


def _prompt(
    key: str,
    event_id: uuid.UUID,
    *,
    budget_class: CaptureBudgetClass = CaptureBudgetClass.CONTEXT,
    scheduled_for: dt.datetime | None = None,
    expires_at: dt.datetime | None = None,
    kind: str = "mood.capture",
) -> CapturePromptEvaluationRequest:
    return CapturePromptEvaluationRequest(
        user_id="will",
        source="appdaemon",
        idempotency_key=key,
        kind=kind,
        budget_class=budget_class,
        event_ids=[event_id],
        reason="A useful transition just ended.",
        priority=70,
        wording="How are you feeling now?",
        scheduled_for=scheduled_for,
        expires_at=expires_at,
        provenance={"rule": "calendar_end"},
    )


async def _events(
    service: ContextCaptureService,
    count: int,
    *,
    prefix: str,
) -> list[uuid.UUID]:
    return [
        (await service.ingest_event(_event(f"{prefix}-{index}"))).event.id
        for index in range(count)
    ]


async def test__ingest_event__is_idempotent_and_rejects_changed_content(
    context_service: ContextCaptureService,
) -> None:
    """An ingestion key denotes exactly one immutable source request."""
    request = _event("same")

    created = await context_service.ingest_event(request)
    retried = await context_service.ingest_event(request)

    assert created.created is True
    assert retried.created is False
    assert retried.event.id == created.event.id
    with pytest.raises(exc.ConflictError):
        _ = await context_service.ingest_event(
            request.model_copy(update={"summary": "Changed"}),
        )


def test__context_event__rejects_unknown_iana_timezone() -> None:
    """Event ingestion contracts require an IANA timezone."""
    with pytest.raises(ValueError, match="Unknown event timezone"):
        _ = _event("bad-timezone", timezone="Mars/Olympus_Mons")


async def test__ingest_events__rolls_back_an_invalid_batch(
    context_service: ContextCaptureService,
) -> None:
    """Batch ingestion is atomic when a later member conflicts."""
    existing = _event("existing")
    _ = await context_service.ingest_event(existing)

    with pytest.raises(exc.ConflictError):
        _ = await context_service.ingest_events(
            ContextEventBatchCreate(
                events=[
                    _event("rolled-back"),
                    existing.model_copy(update={"summary": "Different"}),
                ],
            ),
        )

    events = await context_service.list_events(user_id="will")
    assert [event.idempotency_key for event in events] == ["existing"]


async def test__ingest_event__marks_the_replaced_event_superseded(
    context_service: ContextCaptureService,
) -> None:
    """A correction preserves history while superseding its predecessor."""
    original = await context_service.ingest_event(_event("original"))
    replacement = await context_service.ingest_event(
        _event("replacement", supersedes_event_id=original.event.id),
    )

    events = await context_service.list_events(user_id="will")
    by_id = {event.id: event for event in events}
    assert by_id[original.event.id].status is ContextEventStatus.SUPERSEDED
    assert by_id[replacement.event.id].supersedes_event_id == original.event.id

    replayed = await context_service.ingest_event(_event("original"))
    assert replayed.created is False
    assert replayed.event.status is ContextEventStatus.SUPERSEDED


async def test__ingest_event__concurrent_retries_are_deterministic(
    context_service: ContextCaptureService,
) -> None:
    """Concurrent identical requests converge and divergent requests conflict."""
    request = _event("concurrent-event")
    identical = await asyncio.gather(
        context_service.ingest_event(request),
        context_service.ingest_event(request),
    )

    assert {result.event.id for result in identical} == {identical[0].event.id}
    assert sorted(result.created for result in identical) == [False, True]

    divergent = await asyncio.gather(
        context_service.ingest_event(_event("divergent-event")),
        context_service.ingest_event(
            _event("divergent-event").model_copy(update={"summary": "Different"}),
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, BaseException) for result in divergent) == 1
    assert sum(isinstance(result, exc.ConflictError) for result in divergent) == 1


async def test__get_policy__is_race_safe_on_first_creation(
    context_service: ContextCaptureService,
    context_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Concurrent first reads converge on one default policy row."""
    policies = await asyncio.gather(
        *(context_service.get_policy("concurrent") for _ in range(4)),
    )

    async with context_session_factory() as session:
        rows = list(await session.scalars(CapturePolicyRow.__table__.select()))
    assert all(policy.user_id == "concurrent" for policy in policies)
    assert len(rows) == 1


async def test__evaluate_prompt__uses_separate_baseline_and_context_budgets(
    context_service: ContextCaptureService,
) -> None:
    """The baseline reservation cannot be consumed by contextual prompts."""
    _ = await context_service.update_policy(
        "will",
        CapturePolicyUpdate(
            timezone="Europe/London",
            baseline_prompt_limit=1,
            context_prompt_limit=2,
            cooldown_seconds=0,
        ),
    )
    event_ids = await _events(context_service, 5, prefix="budget")
    schedule = dt.datetime(2026, 9, 2, 10, tzinfo=dt.UTC)

    baseline = await context_service.evaluate_prompt(
        _prompt(
            "baseline-1",
            event_ids[0],
            budget_class=CaptureBudgetClass.BASELINE,
            scheduled_for=schedule,
        ),
    )
    context_one = await context_service.evaluate_prompt(
        _prompt("context-1", event_ids[1], scheduled_for=schedule),
    )
    context_two = await context_service.evaluate_prompt(
        _prompt("context-2", event_ids[2], scheduled_for=schedule),
    )
    baseline_over = await context_service.evaluate_prompt(
        _prompt(
            "baseline-2",
            event_ids[3],
            budget_class=CaptureBudgetClass.BASELINE,
            scheduled_for=schedule,
        ),
    )
    context_over = await context_service.evaluate_prompt(
        _prompt("context-3", event_ids[4], scheduled_for=schedule),
    )

    assert baseline.allowed is True
    assert context_one.allowed is True
    assert context_two.allowed is True
    assert baseline_over.reason is CaptureDecisionReason.DAILY_BUDGET
    assert context_over.reason is CaptureDecisionReason.DAILY_BUDGET


async def test__evaluate_prompt__gates_event_status_and_confidence_centrally(
    context_service: ContextCaptureService,
) -> None:
    """Only reliable, active events can authorize an interruption."""
    low = await context_service.ingest_event(_event("low", confidence=0.6))
    tentative = await context_service.ingest_event(
        _event("tentative", status=ContextEventStatus.TENTATIVE),
    )
    superseded = await context_service.ingest_event(_event("superseded"))
    _ = await context_service.ingest_event(
        _event("replacement", supersedes_event_id=superseded.event.id),
    )

    low_result = await context_service.evaluate_prompt(
        _prompt("low", low.event.id, expires_at=OCCURRED_AT),
    )
    tentative_result = await context_service.evaluate_prompt(
        _prompt("tentative", tentative.event.id),
    )
    superseded_result = await context_service.evaluate_prompt(
        _prompt("superseded", superseded.event.id),
    )

    assert low_result.reason is CaptureDecisionReason.INELIGIBLE_EVENT
    assert tentative_result.reason is CaptureDecisionReason.INELIGIBLE_EVENT
    assert superseded_result.reason is CaptureDecisionReason.INELIGIBLE_EVENT
    assert all(
        result.prompt.status is CapturePromptStatus.CANCELLED
        for result in (low_result, tentative_result, superseded_result)
    )

    _ = await context_service.update_policy(
        "will",
        CapturePolicyUpdate(
            context_prompt_limit=2,
            cooldown_seconds=0,
            minimum_event_confidence=0.5,
        ),
    )
    admitted = await context_service.evaluate_prompt(
        _prompt("low-after-policy", low.event.id),
    )
    assert admitted.allowed is True


async def test__evaluate_prompt__delays_baseline_but_cancels_context_in_cooldown(
    context_service: ContextCaptureService,
) -> None:
    """One cooldown applies globally while preserving a delayed baseline slot."""
    event_ids = await _events(context_service, 3, prefix="cooldown")
    first_time = dt.datetime(2026, 9, 2, 10, tzinfo=dt.UTC)
    first = await context_service.evaluate_prompt(
        _prompt("context-first", event_ids[0], scheduled_for=first_time),
    )
    context = await context_service.evaluate_prompt(
        _prompt(
            "context-too-soon",
            event_ids[1],
            scheduled_for=first_time + dt.timedelta(minutes=10),
        ),
    )
    baseline = await context_service.evaluate_prompt(
        _prompt(
            "baseline-delayed",
            event_ids[2],
            budget_class=CaptureBudgetClass.BASELINE,
            scheduled_for=first_time + dt.timedelta(minutes=10),
        ),
    )

    assert first.allowed is True
    assert context.allowed is False
    assert context.reason is CaptureDecisionReason.COOLDOWN
    assert baseline.allowed is True
    assert baseline.prompt.scheduled_for == first_time + dt.timedelta(minutes=90)


async def test__evaluate_prompt__cancels_when_cooldown_shift_reaches_expiry(
    context_service: ContextCaptureService,
) -> None:
    """A delayed baseline fails closed if it would become stale first."""
    event_ids = await _events(context_service, 2, prefix="expiry")
    first_time = dt.datetime(2026, 9, 2, 10, tzinfo=dt.UTC)
    _ = await context_service.evaluate_prompt(
        _prompt("expiry-first", event_ids[0], scheduled_for=first_time),
    )
    result = await context_service.evaluate_prompt(
        _prompt(
            "expiry-baseline",
            event_ids[1],
            budget_class=CaptureBudgetClass.BASELINE,
            scheduled_for=first_time + dt.timedelta(minutes=10),
            expires_at=first_time + dt.timedelta(minutes=30),
        ),
    )

    assert result.allowed is False
    assert result.reason is CaptureDecisionReason.COOLDOWN
    assert result.prompt.status is CapturePromptStatus.CANCELLED


async def test__evaluate_prompt__cooldown_ignores_undelivered_terminal_prompts(
    context_service: ContextCaptureService,
) -> None:
    """Only scheduled reservations and actual deliveries consume cooldown."""
    _ = await context_service.update_policy(
        "will",
        CapturePolicyUpdate(context_prompt_limit=10, cooldown_seconds=5400),
    )
    event_ids = await _events(context_service, 4, prefix="terminal-cooldown")
    start = dt.datetime(2026, 9, 2, 10, tzinfo=dt.UTC)
    expired_candidate = await context_service.evaluate_prompt(
        _prompt("undelivered-expiry", event_ids[0], scheduled_for=start),
    )
    _ = await context_service.expire(
        expired_candidate.prompt.id,
        CapturePromptExpireRequest(expired_at=start + dt.timedelta(minutes=1)),
    )
    duplicate = await context_service.evaluate_prompt(
        _prompt(
            "expired-duplicate",
            event_ids[0],
            scheduled_for=start + dt.timedelta(minutes=5),
        ),
    )
    dismissed_candidate = await context_service.evaluate_prompt(
        _prompt(
            "undelivered-dismissal",
            event_ids[1],
            scheduled_for=start + dt.timedelta(minutes=10),
        ),
    )
    _ = await context_service.dismiss(
        dismissed_candidate.prompt.id,
        CapturePromptDismissRequest(
            dismissed_at=start + dt.timedelta(minutes=11),
        ),
    )
    delivered_candidate = await context_service.evaluate_prompt(
        _prompt(
            "delivered-terminal",
            event_ids[2],
            scheduled_for=start + dt.timedelta(minutes=20),
        ),
    )
    _ = await context_service.mark_delivered(
        delivered_candidate.prompt.id,
        CapturePromptDeliveryRequest(
            delivered_at=start + dt.timedelta(minutes=20),
        ),
    )
    _ = await context_service.dismiss(
        delivered_candidate.prompt.id,
        CapturePromptDismissRequest(
            dismissed_at=start + dt.timedelta(minutes=21),
        ),
    )
    blocked = await context_service.evaluate_prompt(
        _prompt(
            "after-delivered-terminal",
            event_ids[3],
            scheduled_for=start + dt.timedelta(minutes=30),
        ),
    )

    assert duplicate.reason is CaptureDecisionReason.DUPLICATE_EVENT
    assert dismissed_candidate.allowed is True
    assert delivered_candidate.allowed is True
    assert blocked.reason is CaptureDecisionReason.COOLDOWN


async def test__evaluate_prompt__budgets_by_scheduled_local_day_across_dst(
    context_service: ContextCaptureService,
) -> None:
    """A Europe/London DST day uses its 23-hour local-day boundary."""
    _ = await context_service.update_policy(
        "will",
        CapturePolicyUpdate(
            timezone="Europe/London",
            baseline_prompt_limit=1,
            context_prompt_limit=1,
            cooldown_seconds=0,
        ),
    )
    event_ids = await _events(context_service, 3, prefix="dst")
    first = await context_service.evaluate_prompt(
        _prompt(
            "dst-first",
            event_ids[0],
            scheduled_for=dt.datetime(2026, 3, 29, 0, 30, tzinfo=dt.UTC),
        ),
    )
    same_local_day = await context_service.evaluate_prompt(
        _prompt(
            "dst-same-day",
            event_ids[1],
            scheduled_for=dt.datetime(2026, 3, 29, 22, 30, tzinfo=dt.UTC),
        ),
    )
    next_local_day = await context_service.evaluate_prompt(
        _prompt(
            "dst-next-day",
            event_ids[2],
            scheduled_for=dt.datetime(2026, 3, 29, 23, 30, tzinfo=dt.UTC),
        ),
    )

    assert first.allowed is True
    assert same_local_day.reason is CaptureDecisionReason.DAILY_BUDGET
    assert next_local_day.allowed is True


async def test__evaluate_prompt__deduplicates_cross_source_correlations(
    context_service: ContextCaptureService,
) -> None:
    """Equivalent observations from distinct adapters produce one prompt."""
    _ = await context_service.update_policy(
        "will",
        CapturePolicyUpdate(context_prompt_limit=2, cooldown_seconds=0),
    )
    calendar = await context_service.ingest_event(
        _event("calendar", source="home_assistant", correlation_key="event:123"),
    )
    appdaemon = await context_service.ingest_event(
        _event("adapter", source="appdaemon", correlation_key="event:123"),
    )
    first = await context_service.evaluate_prompt(_prompt("dedupe-1", calendar.event.id))
    duplicate = await context_service.evaluate_prompt(
        _prompt("dedupe-2", appdaemon.event.id),
    )

    assert first.allowed is True
    assert duplicate.allowed is False
    assert duplicate.reason is CaptureDecisionReason.DUPLICATE_EVENT


async def test__evaluate_prompt__idempotency_requires_equivalent_request(
    context_service: ContextCaptureService,
) -> None:
    """Prompt retries are canonicalized while changed content conflicts."""
    first_id, second_id = await _events(context_service, 2, prefix="idempotency")
    request = _prompt("prompt-idempotent", first_id).model_copy(
        update={"event_ids": [first_id, second_id]},
    )
    reordered = request.model_copy(update={"event_ids": [second_id, first_id]})

    created = await context_service.evaluate_prompt(request)
    retried = await context_service.evaluate_prompt(reordered)

    assert created.created is True
    assert retried.created is False
    assert retried.allowed is True
    assert retried.reason is CaptureDecisionReason.IDEMPOTENT
    with pytest.raises(exc.ConflictError):
        _ = await context_service.evaluate_prompt(
            request.model_copy(update={"wording": "Different wording"}),
        )


async def test__evaluate_prompt__terminal_retry_is_not_safe_to_deliver(
    context_service: ContextCaptureService,
) -> None:
    """An idempotent retry reports delivery safety, not the historic decision."""
    event_id = (await context_service.ingest_event(_event("terminal"))).event.id
    request = _prompt("terminal-prompt", event_id)
    created = await context_service.evaluate_prompt(request)
    delivery_request = CapturePromptDeliveryRequest(
        delivery_context={"device": "phone"},
    )
    delivered = await context_service.mark_delivered(
        created.prompt.id,
        delivery_request,
    )
    delivery_retry = await context_service.mark_delivered(
        created.prompt.id,
        delivery_request,
    )

    retried = await context_service.evaluate_prompt(request)

    assert [change.status for change in delivered.status_history] == [
        CapturePromptStatus.SCHEDULED,
        CapturePromptStatus.DELIVERED,
    ]
    assert delivery_retry.status_history == delivered.status_history
    assert retried.created is False
    assert retried.allowed is False
    assert retried.prompt.status is CapturePromptStatus.DELIVERED
    with pytest.raises(exc.ConflictError):
        _ = await context_service.mark_delivered(
            created.prompt.id,
            CapturePromptDeliveryRequest(delivery_context={"device": "tablet"}),
        )


async def test__evaluate_prompt__concurrent_retries_are_deterministic(
    context_service: ContextCaptureService,
) -> None:
    """Concurrent prompt retries return the canonical outcome or a domain conflict."""
    event_id = (await context_service.ingest_event(_event("prompt-race"))).event.id
    request = _prompt("prompt-race", event_id)
    identical = await asyncio.gather(
        context_service.evaluate_prompt(request),
        context_service.evaluate_prompt(request),
    )

    assert {result.prompt.id for result in identical} == {identical[0].prompt.id}
    assert sorted(result.created for result in identical) == [False, True]

    second_event = (await context_service.ingest_event(_event("prompt-race-2"))).event.id
    divergent_request = _prompt("divergent-prompt", second_event)
    divergent = await asyncio.gather(
        context_service.evaluate_prompt(divergent_request),
        context_service.evaluate_prompt(
            divergent_request.model_copy(update={"wording": "Different"}),
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, BaseException) for result in divergent) == 1
    assert sum(isinstance(result, exc.ConflictError) for result in divergent) == 1


async def test__prompt_lifecycle__keeps_multiple_immutable_responses(
    context_service: ContextCaptureService,
) -> None:
    """A notification action and later journal text remain separate responses."""
    event_id = (await context_service.ingest_event(_event("responses"))).event.id
    evaluated = await context_service.evaluate_prompt(
        _prompt("responses-prompt", event_id),
    )
    delivered = await context_service.mark_delivered(
        evaluated.prompt.id,
        CapturePromptDeliveryRequest(delivery_context={"receptive": True}),
    )
    mood_request = CapturePromptResponseRequest(
        idempotency_key="mood-action",
        response_kind="mood_rating",
        payload={"value": 7},
        response_context={"location": "home"},
    )
    mood = await context_service.respond(delivered.id, mood_request)
    mood_retry = await context_service.respond(delivered.id, mood_request)
    note = await context_service.respond(
        delivered.id,
        CapturePromptResponseRequest(
            idempotency_key="journal-note",
            response_kind="journal_text",
            text="Good focus after the meeting.",
        ),
    )

    assert mood.created is True
    assert mood_retry.created is False
    assert note.created is True
    assert note.response.id != mood.response.id
    assert note.prompt.responded_at == mood.prompt.responded_at
    assert [change.status for change in note.prompt.status_history] == [
        CapturePromptStatus.SCHEDULED,
        CapturePromptStatus.DELIVERED,
        CapturePromptStatus.RESPONDED,
    ]
    with pytest.raises(exc.ConflictError):
        _ = await context_service.respond(
            delivered.id,
            mood_request.model_copy(update={"payload": {"value": 3}}),
        )


async def test__prompt_lifecycle__records_terminal_timing_and_reasons(
    context_service: ContextCaptureService,
) -> None:
    """Dismissal and expiry retain explicit terminal provenance."""
    first_id, second_id = await _events(context_service, 2, prefix="terminal-reason")
    _ = await context_service.update_policy(
        "will",
        CapturePolicyUpdate(context_prompt_limit=2, cooldown_seconds=0),
    )
    first = await context_service.evaluate_prompt(_prompt("dismiss", first_id))
    second = await context_service.evaluate_prompt(_prompt("expire", second_id))
    dismissed_at = OCCURRED_AT + dt.timedelta(hours=1)
    expired_at = OCCURRED_AT + dt.timedelta(hours=2)

    dismissed = await context_service.dismiss(
        first.prompt.id,
        CapturePromptDismissRequest(dismissed_at=dismissed_at, reason="busy"),
    )
    expired = await context_service.expire(
        second.prompt.id,
        CapturePromptExpireRequest(expired_at=expired_at, reason="event_stale"),
    )

    assert dismissed.status is CapturePromptStatus.DISMISSED
    assert dismissed.dismissed_at == dismissed_at
    assert dismissed.dismissal_reason == "busy"
    assert [change.status for change in dismissed.status_history] == [
        CapturePromptStatus.SCHEDULED,
        CapturePromptStatus.DISMISSED,
    ]
    assert expired.status is CapturePromptStatus.EXPIRED
    assert expired.expired_at == expired_at
    assert expired.expiration_reason == "event_stale"
    assert [change.status for change in expired.status_history] == [
        CapturePromptStatus.SCHEDULED,
        CapturePromptStatus.EXPIRED,
    ]
    with pytest.raises(exc.ConflictError):
        _ = await context_service.dismiss(
            first.prompt.id,
            CapturePromptDismissRequest(dismissed_at=dismissed_at, reason="not_now"),
        )
