"""Canonical context-event, prompt-policy, and response service."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
import zoneinfo
from typing import TYPE_CHECKING, final

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backplane.context.database import AsyncSessionFactory, context_session_factory
from backplane.context.schemas import (
    CaptureBudgetClass,
    CaptureDecisionReason,
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
    CapturePromptStatus,
    CapturePromptStatusChange,
    CaptureResponse,
    ContextEvent,
    ContextEventBatchCreate,
    ContextEventBatchResult,
    ContextEventCreate,
    ContextEventResult,
    ContextEventStatus,
    PrivacyClass,
    utc_now,
)
from backplane.context.tables import (
    CapturePolicyRow,
    CapturePromptEventRow,
    CapturePromptRow,
    CapturePromptStatusRow,
    CaptureResponseRow,
    ContextEventRow,
)
from backplane.utils import exc

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


_POLICY_ALLOWED_PROMPT_STATUSES = frozenset(
    {
        CapturePromptStatus.SCHEDULED.value,
        CapturePromptStatus.DELIVERED.value,
        CapturePromptStatus.RESPONDED.value,
        CapturePromptStatus.DISMISSED.value,
        CapturePromptStatus.EXPIRED.value,
    },
)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """Normalize SQLite-returned naive UTC values for portable tests.

    Returns:
        A timezone-aware value, or ``None`` when the input is null.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def _required_aware(value: dt.datetime) -> dt.datetime:
    """Normalize a required database timestamp.

    Returns:
        Timezone-aware timestamp.

    Raises:
        ValueError: If the required timestamp is unexpectedly null.
    """
    normalized = _aware(value)
    if normalized is None:  # pragma: no cover - guarded by the type contract
        msg = "Required timestamp was unexpectedly null."
        raise ValueError(msg)
    return normalized


@final
class ContextCaptureService:
    """Shared service behind context REST and MCP adapters."""

    def __init__(self, session_factory: AsyncSessionFactory | None = None) -> None:
        """Bind the service to an explicit or configured async session factory."""
        self._session_factory = session_factory or context_session_factory()

    @staticmethod
    def _event_from_row(row: ContextEventRow) -> ContextEvent:
        return ContextEvent(
            id=row.id,
            user_id=row.user_id,
            source=row.source,
            source_event_id=row.source_event_id,
            correlation_key=row.correlation_key,
            idempotency_key=row.idempotency_key,
            kind=row.kind,
            occurred_at=_required_aware(row.occurred_at),
            ended_at=_aware(row.ended_at),
            timezone=row.timezone,
            confidence=row.confidence,
            privacy_class=PrivacyClass(row.privacy_class),
            status=ContextEventStatus(row.status),
            summary=row.summary,
            payload=row.payload,
            provenance=row.provenance,
            supersedes_event_id=row.supersedes_event_id,
            created_at=_required_aware(row.created_at),
            updated_at=_required_aware(row.updated_at),
        )

    @staticmethod
    def _policy_from_row(row: CapturePolicyRow) -> CapturePolicy:
        return CapturePolicy(
            user_id=row.user_id,
            timezone=row.timezone,
            baseline_prompt_limit=row.baseline_prompt_limit,
            context_prompt_limit=row.context_prompt_limit,
            cooldown_seconds=row.cooldown_seconds,
            minimum_event_confidence=row.minimum_event_confidence,
            created_at=_required_aware(row.created_at),
            updated_at=_required_aware(row.updated_at),
        )

    @staticmethod
    async def _prompt_from_row(
        session: AsyncSession,
        row: CapturePromptRow,
    ) -> CapturePrompt:
        event_ids = list(
            (
                await session.scalars(
                    select(CapturePromptEventRow.event_id)
                    .where(CapturePromptEventRow.prompt_id == row.id)
                    .order_by(CapturePromptEventRow.event_id),
                )
            ).all(),
        )
        status_history = [
            CapturePromptStatusChange(
                id=change.id,
                prompt_id=change.prompt_id,
                status=CapturePromptStatus(change.status),
                occurred_at=_required_aware(change.occurred_at),
                recorded_at=_required_aware(change.recorded_at),
                reason=change.reason,
            )
            for change in (
                await session.scalars(
                    select(CapturePromptStatusRow)
                    .where(CapturePromptStatusRow.prompt_id == row.id)
                    .order_by(
                        CapturePromptStatusRow.recorded_at,
                        CapturePromptStatusRow.id,
                    ),
                )
            ).all()
        ]
        return CapturePrompt(
            id=row.id,
            user_id=row.user_id,
            source=row.source,
            idempotency_key=row.idempotency_key,
            kind=row.kind,
            budget_class=CaptureBudgetClass(row.budget_class),
            event_ids=event_ids,
            status_history=status_history,
            reason=row.reason,
            priority=row.priority,
            wording=row.wording,
            status=CapturePromptStatus(row.status),
            decision_reason=CaptureDecisionReason(row.decision_reason),
            scheduled_for=_aware(row.scheduled_for),
            expires_at=_aware(row.expires_at),
            delivered_at=_aware(row.delivered_at),
            responded_at=_aware(row.responded_at),
            dismissed_at=_aware(row.dismissed_at),
            dismissal_reason=row.dismissal_reason,
            expired_at=_aware(row.expired_at),
            expiration_reason=row.expiration_reason,
            cancelled_at=_aware(row.cancelled_at),
            cancellation_reason=row.cancellation_reason,
            delivery_context=row.delivery_context,
            provenance=row.provenance,
            created_at=_required_aware(row.created_at),
            updated_at=_required_aware(row.updated_at),
        )

    @staticmethod
    def _response_from_row(row: CaptureResponseRow) -> CaptureResponse:
        return CaptureResponse(
            id=row.id,
            prompt_id=row.prompt_id,
            idempotency_key=row.idempotency_key,
            response_kind=row.response_kind,
            text=row.text,
            payload=row.payload,
            response_context=row.response_context,
            provenance=row.provenance,
            responded_at=_required_aware(row.responded_at),
            created_at=_required_aware(row.created_at),
        )

    @staticmethod
    def _request_fingerprint(request: ContextEventCreate) -> str:
        encoded = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    async def _existing_event(
        session: AsyncSession,
        request: ContextEventCreate,
    ) -> ContextEventRow | None:
        filters = [
            and_(
                ContextEventRow.user_id == request.user_id,
                ContextEventRow.source == request.source,
                ContextEventRow.idempotency_key == request.idempotency_key,
            ),
        ]
        if request.source_event_id is not None:
            filters.append(
                and_(
                    ContextEventRow.user_id == request.user_id,
                    ContextEventRow.source == request.source,
                    ContextEventRow.source_event_id == request.source_event_id,
                ),
            )
        return await session.scalar(select(ContextEventRow).where(or_(*filters)))

    async def _ingest_event(
        self,
        session: AsyncSession,
        request: ContextEventCreate,
    ) -> ContextEventResult:
        request_fingerprint = self._request_fingerprint(request)
        if (existing := await self._existing_event(session, request)) is not None:
            if existing.request_fingerprint != request_fingerprint:
                msg = "Context event idempotency key was reused with different content."
                raise exc.ConflictError(
                    message=msg,
                    detail={"event_id": str(existing.id)},
                )
            return ContextEventResult(event=self._event_from_row(existing), created=False)

        superseded: ContextEventRow | None = None
        if request.supersedes_event_id is not None:
            superseded = await session.get(ContextEventRow, request.supersedes_event_id)
            if superseded is None or superseded.user_id != request.user_id:
                msg = f"Context event {request.supersedes_event_id} not found."
                raise exc.NotFoundError(message=msg)

        event_id = uuid.uuid4()
        values = {
            "id": event_id,
            "user_id": request.user_id,
            "source": request.source,
            "source_event_id": request.source_event_id,
            "correlation_key": request.correlation_key,
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": request_fingerprint,
            "kind": request.kind,
            "occurred_at": request.occurred_at,
            "ended_at": request.ended_at,
            "timezone": request.timezone,
            "confidence": request.confidence,
            "privacy_class": request.privacy_class.value,
            "status": request.status.value,
            "summary": request.summary,
            "payload": request.payload,
            "provenance": request.provenance,
            "supersedes_event_id": request.supersedes_event_id,
        }
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "postgresql":
            statement = (
                postgresql_insert(ContextEventRow)
                .values(**values)
                .on_conflict_do_nothing()
            )
        elif dialect_name == "sqlite":
            statement = (
                sqlite_insert(ContextEventRow).values(**values).on_conflict_do_nothing()
            )
        else:
            msg = f"Unsupported context database dialect {dialect_name!r}."
            raise exc.InternalServerError(message=msg)
        _ = await session.execute(statement)
        persisted = await self._existing_event(session, request)
        if persisted is None:
            msg = "Context event could not be persisted."
            raise exc.InternalServerError(message=msg)
        if persisted.request_fingerprint != request_fingerprint:
            msg = "Context event idempotency key was reused with different content."
            raise exc.ConflictError(
                message=msg,
                detail={"event_id": str(persisted.id)},
            )
        created = persisted.id == event_id
        if superseded is not None and created:
            superseded.status = ContextEventStatus.SUPERSEDED.value
            await session.flush()
        return ContextEventResult(event=self._event_from_row(persisted), created=created)

    async def ingest_event(self, request: ContextEventCreate) -> ContextEventResult:
        """Ingest one event idempotently.

        Returns:
            Canonical event and whether it was newly created.
        """
        async with self._session_factory() as session, session.begin():
            return await self._ingest_event(session, request)

    async def ingest_events(
        self,
        request: ContextEventBatchCreate,
    ) -> ContextEventBatchResult:
        """Ingest an event batch atomically.

        Returns:
            Ordered results for every event in the batch.
        """
        async with self._session_factory() as session, session.begin():
            results = [
                await self._ingest_event(session, event_request)
                for event_request in request.events
            ]
            return ContextEventBatchResult(results=results)

    async def list_events(
        self,
        *,
        user_id: str,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        kinds: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[ContextEvent]:
        """Return a bounded chronological context window."""
        statement = select(ContextEventRow).where(ContextEventRow.user_id == user_id)
        if start is not None:
            statement = statement.where(ContextEventRow.occurred_at >= start)
        if end is not None:
            statement = statement.where(ContextEventRow.occurred_at < end)
        if kinds:
            statement = statement.where(ContextEventRow.kind.in_(kinds))
        statement = statement.order_by(ContextEventRow.occurred_at).limit(limit)
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
            return [self._event_from_row(row) for row in rows]

    @staticmethod
    async def _policy_row(
        session: AsyncSession,
        user_id: str,
        *,
        lock: bool,
    ) -> CapturePolicyRow:
        values = {
            "user_id": user_id,
            "timezone": "UTC",
            "baseline_prompt_limit": 1,
            "context_prompt_limit": 2,
            "cooldown_seconds": 5400,
            "minimum_event_confidence": 0.7,
        }
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "postgresql":
            _ = await session.execute(
                postgresql_insert(CapturePolicyRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["user_id"]),
            )
        elif dialect_name == "sqlite":
            _ = await session.execute(
                sqlite_insert(CapturePolicyRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["user_id"]),
            )
        elif await session.get(CapturePolicyRow, user_id) is None:
            session.add(CapturePolicyRow(**values))
            await session.flush()

        statement = select(CapturePolicyRow).where(CapturePolicyRow.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        row = await session.scalar(statement)
        if row is None:
            msg = f"Capture policy for {user_id!r} could not be created."
            raise exc.InternalServerError(message=msg)
        return row

    async def get_policy(self, user_id: str) -> CapturePolicy:
        """Return the user's policy, creating defaults when absent."""
        async with self._session_factory() as session, session.begin():
            row = await self._policy_row(session, user_id, lock=False)
            return self._policy_from_row(row)

    async def update_policy(
        self,
        user_id: str,
        request: CapturePolicyUpdate,
    ) -> CapturePolicy:
        """Replace mutable per-user policy values.

        Returns:
            Updated canonical policy.

        Raises:
            UserError: If the timezone is not a valid IANA identifier.
        """
        try:
            _ = zoneinfo.ZoneInfo(request.timezone)
        except zoneinfo.ZoneInfoNotFoundError as error:
            msg = f"Unknown policy timezone {request.timezone!r}."
            raise exc.UserError(message=msg) from error
        async with self._session_factory() as session, session.begin():
            row = await self._policy_row(session, user_id, lock=True)
            row.timezone = request.timezone
            row.baseline_prompt_limit = request.baseline_prompt_limit
            row.context_prompt_limit = request.context_prompt_limit
            row.cooldown_seconds = request.cooldown_seconds
            row.minimum_event_confidence = request.minimum_event_confidence
            await session.flush()
            return self._policy_from_row(row)

    @staticmethod
    def _local_day_bounds(
        now: dt.datetime,
        timezone: str,
    ) -> tuple[dt.datetime, dt.datetime]:
        local_timezone = zoneinfo.ZoneInfo(timezone)
        local_now = now.astimezone(local_timezone)
        local_start = dt.datetime.combine(
            local_now.date(),
            dt.time(),
            tzinfo=local_timezone,
        )
        return local_start.astimezone(dt.UTC), (
            local_start + dt.timedelta(days=1)
        ).astimezone(dt.UTC)

    @staticmethod
    async def _prompt_event_decision(
        session: AsyncSession,
        request: CapturePromptEvaluationRequest,
        policy: CapturePolicyRow,
    ) -> CaptureDecisionReason:
        rows = (
            await session.scalars(
                select(ContextEventRow).where(ContextEventRow.id.in_(request.event_ids)),
            )
        ).all()
        found = {row.id for row in rows if row.user_id == request.user_id}
        missing = set(request.event_ids) - found
        if missing:
            msg = "One or more context events were not found for this user."
            raise exc.NotFoundError(
                message=msg,
                detail={"event_ids": sorted(str(event_id) for event_id in missing)},
            )
        eligible_statuses = {
            ContextEventStatus.OBSERVED.value,
            ContextEventStatus.CONFIRMED.value,
        }
        if any(
            row.status not in eligible_statuses
            or row.confidence < policy.minimum_event_confidence
            for row in rows
        ):
            return CaptureDecisionReason.INELIGIBLE_EVENT
        return CaptureDecisionReason.ALLOWED

    @staticmethod
    async def _has_duplicate_prompt(
        session: AsyncSession,
        request: CapturePromptEvaluationRequest,
    ) -> bool:
        correlation_keys = set(
            (
                await session.scalars(
                    select(ContextEventRow.correlation_key).where(
                        ContextEventRow.id.in_(request.event_ids),
                        ContextEventRow.correlation_key.is_not(None),
                    ),
                )
            ).all(),
        )
        event_match = CapturePromptEventRow.event_id.in_(request.event_ids)
        if correlation_keys:
            event_match = or_(
                event_match,
                ContextEventRow.correlation_key.in_(correlation_keys),
            )
        prompt_id = await session.scalar(
            select(CapturePromptEventRow.prompt_id)
            .join(
                CapturePromptRow,
                CapturePromptRow.id == CapturePromptEventRow.prompt_id,
            )
            .join(ContextEventRow, ContextEventRow.id == CapturePromptEventRow.event_id)
            .where(
                event_match,
                CapturePromptRow.user_id == request.user_id,
                CapturePromptRow.kind == request.kind,
                CapturePromptRow.status.in_(_POLICY_ALLOWED_PROMPT_STATUSES),
            )
            .limit(1),
        )
        return prompt_id is not None

    @staticmethod
    async def _reserved_prompt_count(
        session: AsyncSession,
        request: CapturePromptEvaluationRequest,
        day_start: dt.datetime,
        day_end: dt.datetime,
    ) -> int:
        value = await session.scalar(
            select(func.count(CapturePromptRow.id)).where(
                CapturePromptRow.user_id == request.user_id,
                CapturePromptRow.budget_class == request.budget_class,
                func.coalesce(
                    CapturePromptRow.scheduled_for,
                    CapturePromptRow.created_at,
                )
                >= day_start,
                func.coalesce(
                    CapturePromptRow.scheduled_for,
                    CapturePromptRow.created_at,
                )
                < day_end,
                CapturePromptRow.status.in_(_POLICY_ALLOWED_PROMPT_STATUSES),
                or_(
                    CapturePromptRow.status == CapturePromptStatus.SCHEDULED.value,
                    CapturePromptRow.delivered_at.is_not(None),
                ),
            ),
        )
        return int(value or 0)

    @staticmethod
    async def _next_allowed_schedule(
        session: AsyncSession,
        policy: CapturePolicyRow,
        user_id: str,
        proposed: dt.datetime,
    ) -> dt.datetime:
        if policy.cooldown_seconds == 0:
            return proposed
        references = (
            await session.scalars(
                select(
                    func.coalesce(
                        CapturePromptRow.delivered_at,
                        CapturePromptRow.scheduled_for,
                        CapturePromptRow.created_at,
                    ),
                )
                .where(
                    CapturePromptRow.user_id == user_id,
                    CapturePromptRow.status.in_(_POLICY_ALLOWED_PROMPT_STATUSES),
                    or_(
                        CapturePromptRow.status == CapturePromptStatus.SCHEDULED.value,
                        CapturePromptRow.delivered_at.is_not(None),
                    ),
                )
                .order_by(
                    func.coalesce(
                        CapturePromptRow.delivered_at,
                        CapturePromptRow.scheduled_for,
                        CapturePromptRow.created_at,
                    ),
                ),
            )
        ).all()
        candidate = proposed
        cooldown = dt.timedelta(seconds=policy.cooldown_seconds)
        for reference in references:
            reference_aware = _aware(reference)
            if reference_aware is None:
                continue
            if abs(candidate - reference_aware) < cooldown:
                candidate = reference_aware + cooldown
        return candidate

    @staticmethod
    def _prompt_request_fingerprint(request: CapturePromptEvaluationRequest) -> str:
        normalized = request.model_copy(
            update={"event_ids": sorted(request.event_ids, key=str)},
        )
        encoded = json.dumps(
            normalized.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _action_request_fingerprint(
        request: (
            CapturePromptDeliveryRequest
            | CapturePromptDismissRequest
            | CapturePromptExpireRequest
            | CapturePromptResponseRequest
        ),
    ) -> str:
        encoded = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _record_prompt_status(
        session: AsyncSession,
        *,
        prompt_id: uuid.UUID,
        status: CapturePromptStatus,
        occurred_at: dt.datetime,
        reason: str | None = None,
    ) -> None:
        session.add(
            CapturePromptStatusRow(
                prompt_id=prompt_id,
                status=status.value,
                occurred_at=occurred_at,
                reason=reason,
            ),
        )

    @staticmethod
    async def _existing_prompt(
        session: AsyncSession,
        request: CapturePromptEvaluationRequest,
    ) -> CapturePromptRow | None:
        return await session.scalar(
            select(CapturePromptRow).where(
                CapturePromptRow.user_id == request.user_id,
                CapturePromptRow.source == request.source,
                CapturePromptRow.idempotency_key == request.idempotency_key,
            ),
        )

    async def _idempotent_prompt_result(
        self,
        session: AsyncSession,
        row: CapturePromptRow,
        request_fingerprint: str,
    ) -> CapturePromptEvaluationResult:
        if row.request_fingerprint != request_fingerprint:
            msg = "Capture prompt idempotency key was reused with different content."
            raise exc.ConflictError(
                message=msg,
                detail={"prompt_id": str(row.id)},
            )
        return CapturePromptEvaluationResult(
            allowed=row.status == CapturePromptStatus.SCHEDULED.value,
            reason=CaptureDecisionReason.IDEMPOTENT,
            prompt=await self._prompt_from_row(session, row),
            created=False,
        )

    async def _prompt_decision(
        self,
        session: AsyncSession,
        request: CapturePromptEvaluationRequest,
        policy: CapturePolicyRow,
        proposed_schedule: dt.datetime,
    ) -> tuple[CaptureDecisionReason, dt.datetime]:
        reason = await self._prompt_event_decision(session, request, policy)
        scheduled_for = await self._next_allowed_schedule(
            session,
            policy,
            request.user_id,
            proposed_schedule,
        )
        if reason is not CaptureDecisionReason.ALLOWED:
            return reason, scheduled_for
        if await self._has_duplicate_prompt(session, request):
            return CaptureDecisionReason.DUPLICATE_EVENT, scheduled_for
        shifted_context = (
            request.budget_class is CaptureBudgetClass.CONTEXT
            and scheduled_for != proposed_schedule
        )
        stale_after_shift = (
            request.expires_at is not None and scheduled_for >= request.expires_at
        )
        if shifted_context or stale_after_shift:
            return CaptureDecisionReason.COOLDOWN, scheduled_for

        day_start, day_end = self._local_day_bounds(scheduled_for, policy.timezone)
        prompt_limit = (
            policy.baseline_prompt_limit
            if request.budget_class is CaptureBudgetClass.BASELINE
            else policy.context_prompt_limit
        )
        reserved = await self._reserved_prompt_count(
            session,
            request,
            day_start,
            day_end,
        )
        if reserved >= prompt_limit:
            return CaptureDecisionReason.DAILY_BUDGET, scheduled_for
        return CaptureDecisionReason.ALLOWED, scheduled_for

    @staticmethod
    def _prompt_insert_values(
        request: CapturePromptEvaluationRequest,
        *,
        prompt_id: uuid.UUID,
        request_fingerprint: str,
        reason: CaptureDecisionReason,
        scheduled_for: dt.datetime,
        now: dt.datetime,
    ) -> dict[str, object]:
        allowed = reason is CaptureDecisionReason.ALLOWED
        return {
            "id": prompt_id,
            "user_id": request.user_id,
            "source": request.source,
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": request_fingerprint,
            "kind": request.kind,
            "budget_class": request.budget_class.value,
            "reason": request.reason,
            "priority": request.priority,
            "wording": request.wording,
            "status": (
                CapturePromptStatus.SCHEDULED.value
                if allowed
                else CapturePromptStatus.CANCELLED.value
            ),
            "decision_reason": reason.value,
            "scheduled_for": scheduled_for,
            "expires_at": request.expires_at,
            "cancelled_at": None if allowed else now,
            "cancellation_reason": None if allowed else reason.value,
            "delivery_context": {},
            "provenance": request.provenance,
        }

    async def _persist_prompt(
        self,
        session: AsyncSession,
        request: CapturePromptEvaluationRequest,
        *,
        prompt_id: uuid.UUID,
        values: dict[str, object],
    ) -> tuple[CapturePromptRow, bool]:
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "postgresql":
            statement = (
                postgresql_insert(CapturePromptRow)
                .values(**values)
                .on_conflict_do_nothing()
            )
        elif dialect_name == "sqlite":
            statement = (
                sqlite_insert(CapturePromptRow).values(**values).on_conflict_do_nothing()
            )
        else:
            msg = f"Unsupported context database dialect {dialect_name!r}."
            raise exc.InternalServerError(message=msg)
        _ = await session.execute(statement)
        row = await self._existing_prompt(session, request)
        if row is None:
            msg = "Capture prompt could not be persisted."
            raise exc.InternalServerError(message=msg)
        return row, row.id == prompt_id

    async def evaluate_prompt(
        self,
        request: CapturePromptEvaluationRequest,
    ) -> CapturePromptEvaluationResult:
        """Evaluate and persist a candidate prompt under the global policy.

        Returns:
            Deterministic policy decision and canonical prompt.
        """
        now = utc_now()
        request_fingerprint = self._prompt_request_fingerprint(request)
        async with self._session_factory() as session, session.begin():
            policy = await self._policy_row(session, request.user_id, lock=True)
            existing = await self._existing_prompt(session, request)
            if existing is not None:
                return await self._idempotent_prompt_result(
                    session,
                    existing,
                    request_fingerprint,
                )

            reason, scheduled_for = await self._prompt_decision(
                session,
                request,
                policy,
                request.scheduled_for or now,
            )
            prompt_id = uuid.uuid4()
            row, created = await self._persist_prompt(
                session,
                request,
                prompt_id=prompt_id,
                values=self._prompt_insert_values(
                    request,
                    prompt_id=prompt_id,
                    request_fingerprint=request_fingerprint,
                    reason=reason,
                    scheduled_for=scheduled_for,
                    now=now,
                ),
            )
            if not created:
                return await self._idempotent_prompt_result(
                    session,
                    row,
                    request_fingerprint,
                )
            allowed = reason is CaptureDecisionReason.ALLOWED
            self._record_prompt_status(
                session,
                prompt_id=row.id,
                status=(
                    CapturePromptStatus.SCHEDULED
                    if allowed
                    else CapturePromptStatus.CANCELLED
                ),
                occurred_at=now,
                reason=reason.value,
            )
            session.add_all(
                CapturePromptEventRow(prompt_id=row.id, event_id=event_id)
                for event_id in request.event_ids
            )
            await session.flush()
            return CapturePromptEvaluationResult(
                allowed=allowed,
                reason=reason,
                prompt=await self._prompt_from_row(session, row),
                created=True,
            )

    @staticmethod
    async def _locked_prompt(
        session: AsyncSession,
        prompt_id: uuid.UUID,
    ) -> CapturePromptRow:
        row = await session.scalar(
            select(CapturePromptRow)
            .where(CapturePromptRow.id == prompt_id)
            .with_for_update(),
        )
        if row is None:
            msg = f"Capture prompt {prompt_id} not found."
            raise exc.NotFoundError(message=msg)
        return row

    async def mark_delivered(
        self,
        prompt_id: uuid.UUID,
        request: CapturePromptDeliveryRequest,
    ) -> CapturePrompt:
        """Record successful delivery idempotently.

        Returns:
            Updated canonical prompt.

        Raises:
            ConflictError: If the retry differs or the prompt cannot be delivered.
        """
        request_fingerprint = self._action_request_fingerprint(request)
        async with self._session_factory() as session, session.begin():
            row = await self._locked_prompt(session, prompt_id)
            if row.delivered_at is not None:
                if row.delivery_request_fingerprint != request_fingerprint:
                    msg = "Delivery retry content did not match the original request."
                    raise exc.ConflictError(message=msg)
                return await self._prompt_from_row(session, row)
            if row.status != CapturePromptStatus.SCHEDULED.value:
                msg = f"Cannot deliver a prompt in status {row.status!r}."
                raise exc.ConflictError(message=msg)
            delivered_at = request.delivered_at or utc_now()
            row.delivered_at = delivered_at
            row.delivery_request_fingerprint = request_fingerprint
            row.delivery_context = request.delivery_context
            row.status = CapturePromptStatus.DELIVERED.value
            self._record_prompt_status(
                session,
                prompt_id=row.id,
                status=CapturePromptStatus.DELIVERED,
                occurred_at=delivered_at,
            )
            await session.flush()
            return await self._prompt_from_row(session, row)

    async def respond(
        self,
        prompt_id: uuid.UUID,
        request: CapturePromptResponseRequest,
    ) -> CapturePromptResponseResult:
        """Attach one idempotent response to a delivered prompt.

        Returns:
            Updated prompt and immutable response.

        Raises:
            ConflictError: If the retry differs or the prompt cannot accept responses.
        """
        request_fingerprint = self._action_request_fingerprint(request)
        async with self._session_factory() as session, session.begin():
            prompt = await self._locked_prompt(session, prompt_id)
            existing = await session.scalar(
                select(CaptureResponseRow).where(
                    CaptureResponseRow.prompt_id == prompt_id,
                    CaptureResponseRow.idempotency_key == request.idempotency_key,
                ),
            )
            if existing is not None:
                if existing.request_fingerprint != request_fingerprint:
                    msg = "Capture response idempotency key was reused with different content."
                    raise exc.ConflictError(message=msg)
                return CapturePromptResponseResult(
                    prompt=await self._prompt_from_row(session, prompt),
                    response=self._response_from_row(existing),
                    created=False,
                )
            if prompt.status not in {
                CapturePromptStatus.DELIVERED.value,
                CapturePromptStatus.RESPONDED.value,
            }:
                msg = f"Cannot respond to a prompt in status {prompt.status!r}."
                raise exc.ConflictError(message=msg)
            responded_at = request.responded_at or utc_now()
            response = CaptureResponseRow(
                prompt_id=prompt_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
                response_kind=request.response_kind,
                text=request.text,
                payload=request.payload,
                response_context=request.response_context,
                provenance=request.provenance,
                responded_at=responded_at,
            )
            session.add(response)
            if prompt.status == CapturePromptStatus.DELIVERED.value:
                prompt.status = CapturePromptStatus.RESPONDED.value
                prompt.responded_at = responded_at
                self._record_prompt_status(
                    session,
                    prompt_id=prompt.id,
                    status=CapturePromptStatus.RESPONDED,
                    occurred_at=responded_at,
                    reason=request.response_kind,
                )
            await session.flush()
            return CapturePromptResponseResult(
                prompt=await self._prompt_from_row(session, prompt),
                response=self._response_from_row(response),
                created=True,
            )

    async def dismiss(
        self,
        prompt_id: uuid.UUID,
        request: CapturePromptDismissRequest,
    ) -> CapturePrompt:
        """Dismiss a scheduled or delivered prompt idempotently.

        Returns:
            Updated canonical prompt.

        Raises:
            ConflictError: If the retry differs or the prompt cannot be dismissed.
        """
        request_fingerprint = self._action_request_fingerprint(request)
        async with self._session_factory() as session, session.begin():
            row = await self._locked_prompt(session, prompt_id)
            if row.status == CapturePromptStatus.DISMISSED.value:
                if row.dismissal_request_fingerprint != request_fingerprint:
                    msg = "Dismissal retry content did not match the original request."
                    raise exc.ConflictError(message=msg)
                return await self._prompt_from_row(session, row)
            if row.status not in {
                CapturePromptStatus.SCHEDULED.value,
                CapturePromptStatus.DELIVERED.value,
            }:
                msg = f"Cannot dismiss a prompt in status {row.status!r}."
                raise exc.ConflictError(message=msg)
            row.status = CapturePromptStatus.DISMISSED.value
            dismissed_at = request.dismissed_at or utc_now()
            row.dismissed_at = dismissed_at
            row.dismissal_request_fingerprint = request_fingerprint
            row.dismissal_reason = request.reason
            self._record_prompt_status(
                session,
                prompt_id=row.id,
                status=CapturePromptStatus.DISMISSED,
                occurred_at=dismissed_at,
                reason=request.reason,
            )
            await session.flush()
            return await self._prompt_from_row(session, row)

    async def expire(
        self,
        prompt_id: uuid.UUID,
        request: CapturePromptExpireRequest,
    ) -> CapturePrompt:
        """Expire a scheduled or delivered prompt idempotently.

        Returns:
            Updated canonical prompt.

        Raises:
            ConflictError: If the retry differs or the prompt cannot be expired.
        """
        request_fingerprint = self._action_request_fingerprint(request)
        async with self._session_factory() as session, session.begin():
            row = await self._locked_prompt(session, prompt_id)
            if row.status == CapturePromptStatus.EXPIRED.value:
                if row.expiration_request_fingerprint != request_fingerprint:
                    msg = "Expiry retry content did not match the original request."
                    raise exc.ConflictError(message=msg)
                return await self._prompt_from_row(session, row)
            if row.status not in {
                CapturePromptStatus.SCHEDULED.value,
                CapturePromptStatus.DELIVERED.value,
            }:
                msg = f"Cannot expire a prompt in status {row.status!r}."
                raise exc.ConflictError(message=msg)
            row.status = CapturePromptStatus.EXPIRED.value
            expired_at = request.expired_at or utc_now()
            row.expired_at = expired_at
            row.expiration_request_fingerprint = request_fingerprint
            row.expiration_reason = request.reason
            self._record_prompt_status(
                session,
                prompt_id=row.id,
                status=CapturePromptStatus.EXPIRED,
                occurred_at=expired_at,
                reason=request.reason,
            )
            await session.flush()
            return await self._prompt_from_row(session, row)
