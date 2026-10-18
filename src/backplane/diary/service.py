"""Durable daily snapshots, retryable exports and one bounded daily review."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import TYPE_CHECKING

import aiohttp
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from backplane.context.schemas import (
    CaptureBudgetClass,
    CaptureDecisionReason,
    CapturePrompt,
    CapturePromptDeliveryRequest,
    CapturePromptDismissRequest,
    CapturePromptEvaluationRequest,
    CapturePromptResponseRequest,
    CapturePromptStatus,
    ContextEventCreate,
    ContextEventStatus,
    utc_now,
)
from backplane.context.tables import (
    CapturePromptEventRow,
    CapturePromptRow,
    CaptureResponseRow,
    ContextEventRow,
)
from backplane.diary.collector import collect_day, day_bounds
from backplane.diary.models import (
    DiaryReviewResponse,
    DiarySnapshot,
    DiarySyncResult,
    retain_entry_aliases,
)
from backplane.diary.questions import review_question
from backplane.diary.render import export_day, facts_text, generate_narrative
from backplane.services.context_capture import ContextCaptureService
from backplane.utils import SETTINGS, exc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backplane.services.idea_followup import FollowupAvailability

_USER = "will"
_SOURCE = "automatic_diary"


class DiaryReview(BaseModel):
    """The exact day and observations associated with one notification."""

    prompt: CapturePrompt
    snapshot: DiarySnapshot
    responses: list[DiaryReviewResponse]
    focus_entry_id: str | None = None


class DiaryService(ContextCaptureService):
    """Single-owner diary operations sharing the existing context ledger and policy lock."""

    @staticmethod
    async def _latest(
        session: AsyncSession,
        date: dt.date,
        kind: str,
    ) -> ContextEventRow | None:
        return await session.scalar(
            select(ContextEventRow)
            .where(
                ContextEventRow.user_id == _USER,
                ContextEventRow.source == _SOURCE,
                ContextEventRow.correlation_key == date.isoformat(),
                ContextEventRow.kind == kind,
                ContextEventRow.status != ContextEventStatus.SUPERSEDED.value,
            )
            .order_by(ContextEventRow.created_at.desc())
            .limit(1),
        )

    @staticmethod
    async def _responses(
        session: AsyncSession,
        date: dt.date,
    ) -> list[DiaryReviewResponse]:
        rows = (
            await session.scalars(
                select(CaptureResponseRow)
                .join(
                    CapturePromptRow,
                    CaptureResponseRow.prompt_id == CapturePromptRow.id,
                )
                .where(
                    CapturePromptRow.source == _SOURCE,
                    CapturePromptRow.user_id == _USER,
                    CapturePromptRow.idempotency_key == date.isoformat(),
                    CaptureResponseRow.response_kind == "diary_review",
                )
                .order_by(
                    CaptureResponseRow.responded_at,
                    CaptureResponseRow.created_at,
                    CaptureResponseRow.id,
                ),
            )
        ).all()
        return [DiaryReviewResponse.model_validate(row.payload) for row in rows]

    async def store_snapshot(self, snapshot: DiarySnapshot) -> None:
        """Commit a complete revision before attempting any vault or inference I/O."""
        async with self._session_factory() as session, session.begin():
            _ = await self._policy_row(session, _USER, lock=True)
            previous = await self._latest(session, snapshot.date, "diary_snapshot")
            if previous:
                saved = DiarySnapshot.model_validate(previous.payload)
                snapshot = retain_entry_aliases(snapshot, saved)
                if (
                    saved.collected_at > snapshot.collected_at
                    or saved.fingerprint() == snapshot.fingerprint()
                ):
                    return
            key = f"{snapshot.date}:{previous.id if previous else 'initial'}:{snapshot.fingerprint()}"
            _ = await self._ingest_event(
                session,
                ContextEventCreate(
                    user_id=_USER,
                    source=_SOURCE,
                    idempotency_key=key,
                    correlation_key=snapshot.date.isoformat(),
                    kind="diary_snapshot",
                    occurred_at=day_bounds(snapshot.date)[0],
                    timezone=str(SETTINGS.local_timezone),
                    payload=snapshot.model_dump(mode="json"),
                    supersedes_event_id=previous.id if previous else None,
                ),
            )

    async def render(self, date: dt.date) -> DiarySyncResult:
        """Serialize exports across workers and always render the current committed view.

        Returns:
            Export status and narrative readiness.

        Raises:
            NotFoundError: The requested diary or review does not exist.
        """
        async with self._session_factory() as session, session.begin():
            _ = await self._policy_row(session, _USER, lock=True)
            row = await self._latest(session, date, "diary_snapshot")
            if row is None:
                message = "No collected diary exists for that date."
                raise exc.NotFoundError(message)
            snapshot = DiarySnapshot.model_validate(row.payload)
            responses = await self._responses(session, date)
            facts = facts_text(snapshot, responses)
            narrative = await self._latest(session, date, "diary_narrative")
            text = None
            if (
                narrative
                and narrative.payload.get("fingerprint")
                == hashlib.sha256(facts.encode()).hexdigest()
            ):
                candidate = narrative.payload.get("text")
                text = candidate if isinstance(candidate, str) else None
            await export_day(snapshot, responses, text)
            return DiarySyncResult(
                date=date,
                entries=len(snapshot.entries),
                missing=snapshot.missing,
                narrative_ready=text is not None,
            )

    async def narrate(self, date: dt.date) -> None:
        """Cache a narrative by exact factual input; failures leave saved facts usable."""
        async with self._session_factory() as session:
            row = await self._latest(session, date, "diary_snapshot")
            if row is None:
                return
            facts = facts_text(
                DiarySnapshot.model_validate(row.payload),
                await self._responses(session, date),
            )
            fingerprint = hashlib.sha256(facts.encode()).hexdigest()
            existing = await self._latest(session, date, "diary_narrative")
            if existing and existing.payload.get("fingerprint") == fingerprint:
                return
        try:
            text = await generate_narrative(facts)
        except aiohttp.ClientError, TimeoutError, ValueError:
            logger.warning(
                "Diary narrative generation failed for {}; facts are retained",
                date,
            )
            return
        async with self._session_factory() as session, session.begin():
            _ = await self._policy_row(session, _USER, lock=True)
            row = await self._latest(session, date, "diary_snapshot")
            if (
                row is None
                or facts_text(
                    DiarySnapshot.model_validate(row.payload),
                    await self._responses(session, date),
                )
                != facts
            ):
                return
            previous = await self._latest(session, date, "diary_narrative")
            if previous and previous.payload.get("fingerprint") == fingerprint:
                return
            _ = await self._ingest_event(
                session,
                ContextEventCreate(
                    user_id=_USER,
                    source=_SOURCE,
                    idempotency_key=f"narrative:{date}:{previous.id if previous else 'initial'}:{fingerprint}",
                    correlation_key=date.isoformat(),
                    kind="diary_narrative",
                    occurred_at=day_bounds(date)[0],
                    timezone=str(SETTINGS.local_timezone),
                    payload={"fingerprint": fingerprint, "text": text},
                    supersedes_event_id=previous.id if previous else None,
                ),
            )

    async def sync(self, date: dt.date, *, narrative: bool = False) -> DiarySyncResult:
        """Collect and export one day, optionally generating its local-model narrative.

        Returns:
            Export status after collection and optional inference.
        """
        await self.store_snapshot(await collect_day(date))
        result = await self.render(date)
        if narrative:
            await self.narrate(date)
            result = await self.render(date)
        return result

    async def reserve(self, availability: FollowupAvailability) -> DiaryReview | None:
        """Reserve a single evening review per local day, shared-budget and cooldown aware.

        Returns:
            A new or unsubmitted daily claim, or None when unavailable or completed.
        """
        now = utc_now()
        local = now.astimezone(SETTINGS.local_timezone)
        if local.time() < dt.time(20, 30) or not all((
            availability.home,
            availability.receptive,
            availability.outside_quiet_hours,
        )):
            return None
        async with self._session_factory() as session, session.begin():
            policy = await self._policy_row(session, _USER, lock=True)
            existing = await session.scalar(
                select(CapturePromptRow).where(
                    CapturePromptRow.source == _SOURCE,
                    CapturePromptRow.user_id == _USER,
                    CapturePromptRow.idempotency_key == local.date().isoformat(),
                ),
            )
            if existing is not None:
                return (
                    await self.get_review(existing.id)
                    if existing.status == CapturePromptStatus.SCHEDULED.value
                    and existing.expires_at is not None
                    and existing.expires_at > now
                    and await self._next_allowed_schedule(
                        session,
                        policy,
                        _USER,
                        now,
                        excluded_prompt_id=existing.id,
                    )
                    <= now
                    else None
                )

            row = await self._latest(session, local.date(), "diary_snapshot")
            if row is None:
                return None

            snapshot = DiarySnapshot.model_validate(row.payload)
            responses = await self._responses(session, local.date())
            wording, focus_entry_id = review_question(snapshot, responses)
            request = CapturePromptEvaluationRequest(
                user_id=_USER,
                source=_SOURCE,
                idempotency_key=local.date().isoformat(),
                kind="diary_review",
                budget_class=CaptureBudgetClass.BASELINE,
                event_ids=[row.id],
                reason="One daily diary review while home and receptive",
                wording=wording,
                expires_at=now + dt.timedelta(hours=18),
                provenance={
                    "date": local.date().isoformat(),
                    "snapshot_id": str(row.id),
                    "focus_entry_id": focus_entry_id,
                },
            )
            start, end = self._local_day_bounds(now, policy.timezone)
            if (
                await self._next_allowed_schedule(session, policy, _USER, now) > now
                or await self._reserved_prompt_count(session, request, start, end)
                >= policy.baseline_prompt_limit
            ):
                return None
            prompt_id = uuid.uuid4()
            prompt, created = await self._persist_prompt(
                session,
                request,
                prompt_id=prompt_id,
                values=self._prompt_insert_values(
                    request,
                    prompt_id=prompt_id,
                    request_fingerprint=self._prompt_request_fingerprint(request),
                    reason=CaptureDecisionReason.ALLOWED,
                    scheduled_for=now,
                    now=now,
                ),
            )
            if not created:
                return None
            session.add(CapturePromptEventRow(prompt_id=prompt_id, event_id=row.id))
            self._record_prompt_status(
                session,
                prompt_id=prompt_id,
                status=CapturePromptStatus.SCHEDULED,
                occurred_at=now,
            )
            await session.flush()
            return DiaryReview(
                prompt=await self._prompt_from_row(session, prompt),
                snapshot=snapshot,
                responses=responses,
                focus_entry_id=focus_entry_id,
            )

    async def get_review_for_date(self, date: dt.date) -> DiaryReview | None:
        """Return the existing exact review for a date without creating a notification."""
        async with self._session_factory() as session:
            prompt_id = await session.scalar(
                select(CapturePromptRow.id).where(
                    CapturePromptRow.source == _SOURCE,
                    CapturePromptRow.user_id == _USER,
                    CapturePromptRow.idempotency_key == date.isoformat(),
                ),
            )

        return await self.get_review(prompt_id) if prompt_id is not None else None

    async def get_review(self, prompt_id: uuid.UUID | None = None) -> DiaryReview | None:
        """Read the exact notification snapshot, never silently select another day's data.

        Returns:
            The pinned snapshot and prior user responses, or None.

        Raises:
            NotFoundError: The requested diary or review does not exist.
        """
        async with self._session_factory() as session:
            query = select(CapturePromptRow).where(
                CapturePromptRow.source == _SOURCE,
                CapturePromptRow.user_id == _USER,
            )
            if prompt_id:
                query = query.where(CapturePromptRow.id == prompt_id)
            else:
                query = query.where(
                    CapturePromptRow.status.in_(["delivered", "responded"]),
                    CapturePromptRow.expires_at > utc_now(),
                )
            prompt = await session.scalar(
                query.order_by(CapturePromptRow.created_at.desc()).limit(1),
            )
            if prompt is None:
                return None
            row = await session.get(
                ContextEventRow,
                uuid.UUID(str(prompt.provenance["snapshot_id"])),
            )
            if row is None:
                message = "The diary review snapshot is missing."
                raise exc.NotFoundError(message)
            snapshot = DiarySnapshot.model_validate(row.payload)
            responses = await self._responses(session, snapshot.date)
            return DiaryReview(
                prompt=await self._prompt_from_row(session, prompt),
                snapshot=snapshot,
                responses=responses,
                focus_entry_id=(
                    focus
                    if isinstance(focus := prompt.provenance.get("focus_entry_id"), str)
                    else None
                ),
            )

    async def submitted(self, prompt_id: uuid.UUID) -> CapturePrompt:
        """Record HA submission only for a diary-owned prompt.

        Returns:
            The prompt with submission recorded.

        Raises:
            NotFoundError: The requested diary or review does not exist.
        """
        if await self.get_review(prompt_id) is None:
            message = "Diary review not found."
            raise exc.NotFoundError(message)
        return await self.mark_delivered(
            prompt_id,
            CapturePromptDeliveryRequest(
                delivery_context={
                    "transport": "script.notify_will",
                    "receipt_confirmed": False,
                },
            ),
        )

    async def dismiss_review(self, prompt_id: uuid.UUID) -> CapturePrompt:
        """Dismiss the exact daily review without marking any observations confirmed.

        Returns:
            The dismissed diary prompt.

        Raises:
            NotFoundError: The requested diary or review does not exist.
        """
        if await self.get_review(prompt_id) is None:
            message = "Diary review not found."
            raise exc.NotFoundError(message)
        return await self.dismiss(prompt_id, CapturePromptDismissRequest())

    async def save_review(
        self,
        prompt_id: uuid.UUID,
        response: DiaryReviewResponse,
        *,
        responded_at: dt.datetime | None = None,
    ) -> str:
        """Persist explicit decisions before export; identical retries repair the note.

        Returns:
            Acknowledgement after storage and export.

        Raises:
            NotFoundError: The requested diary or review does not exist.
        """
        review = await self.get_review(prompt_id)
        if review is None:
            message = "Diary review not found."
            raise exc.NotFoundError(message)

        self.validate_response(review, response)

        _ = await self.respond(
            prompt_id,
            CapturePromptResponseRequest(
                idempotency_key=response.request_id,
                response_kind="diary_review",
                text=response.note,
                payload=response.model_dump(mode="json"),
                responded_at=responded_at,
            ),
        )
        _ = await self.render(review.snapshot.date)
        await self.narrate(review.snapshot.date)
        _ = await self.render(review.snapshot.date)
        return f"Diary review saved for {review.snapshot.date}."

    @staticmethod
    def validate_response(review: DiaryReview, response: DiaryReviewResponse) -> None:
        """Validate decisions against the exact pinned notification before persistence.

        Raises:
            BadRequestError: Decisions reference invalid entries or contain no response.
        """
        entries = {e.id: e for e in review.snapshot.entries}
        if len({d.entry_id for d in response.decisions}) != len(response.decisions):
            message = "Each diary entry may have only one decision per response."
            raise exc.BadRequestError(message)
        for decision in response.decisions:
            entry = entries.get(decision.entry_id)
            if entry is None or (
                entry.kind not in {"calendar", "outing"} or not entry.needs_confirmation
            ):
                message = "Use an exact review entry ID for a calendar event or outing."
                raise exc.BadRequestError(message)
            if decision.outcome == "dog_walk" and entry.kind != "outing":
                message = "Only an outing can be confirmed as a dog walk."
                raise exc.BadRequestError(message)
        if not response.decisions and not response.note.strip():
            message = "A diary response needs a decision or a note."
            raise exc.BadRequestError(message)
