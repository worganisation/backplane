"""Durable automation observations exported independently of HA snapshot refreshes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import select

from backplane.context.schemas import ContextEventCreate, ContextEventResult
from backplane.context.tables import ContextEventRow
from backplane.diary.render import plain
from backplane.services.context_capture import ContextCaptureService
from backplane.services.obsidian import ObsidianService
from backplane.utils import SETTINGS, format_human_date

if TYPE_CHECKING:
    import datetime as dt


class DiaryObservationCreate(BaseModel, frozen=True):
    """Exact source observation with caller-owned identity and explicit certainty."""

    source: Annotated[str, Field(min_length=1, max_length=64)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    occurred_at: AwareDatetime
    text: Annotated[str, Field(min_length=1, max_length=10000)]
    certainty: Literal["candidate", "confirmed"]

    @field_validator("source", "idempotency_key", "text")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        """Reject blank fields without rewriting the original observation.

        Returns:
            Original nonblank field value.

        Raises:
            ValueError: The field contains only whitespace.
        """
        if not value.strip():
            message = "Observation source, key and text must not be blank."
            raise ValueError(message)

        return value


class DiaryObservation(DiaryObservationCreate, frozen=True):
    """Stored observation and its stable ledger identity."""

    event_id: str


class DiaryObservationService(ContextCaptureService):
    """Retain observations before retryable projection into an owned note section."""

    async def list_day(self, date: dt.date) -> list[DiaryObservation]:
        """Return original observations for a local diary date in occurrence order."""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ContextEventRow)
                .where(
                    ContextEventRow.user_id == "will",
                    ContextEventRow.kind == "diary_observation",
                    ContextEventRow.correlation_key == date.isoformat(),
                    ContextEventRow.status != "superseded",
                )
                .order_by(
                    ContextEventRow.occurred_at,
                    ContextEventRow.created_at,
                    ContextEventRow.id,
                ),
            )
            return [
                DiaryObservation.model_validate({**row.payload, "event_id": str(row.id)})
                for row in rows
            ]

    async def record(self, request: DiaryObservationCreate) -> ContextEventResult:
        """Persist once then repair/export the day's activities without model inference.

        Returns:
            Canonical receipt only after the deterministic note export succeeds.
        """
        date = request.occurred_at.astimezone(SETTINGS.local_timezone).date()
        result = await self.ingest_event(
            ContextEventCreate(
                user_id="will",
                source=request.source,
                idempotency_key=f"diary-observation:{request.idempotency_key}",
                kind="diary_observation",
                correlation_key=date.isoformat(),
                occurred_at=request.occurred_at,
                timezone=str(SETTINGS.local_timezone),
                payload=request.model_dump(mode="json"),
                provenance={"certainty": request.certainty, "adapter": request.source},
            ),
        )

        async with self._session_factory() as session, session.begin():
            _ = await self._policy_row(session, "will", lock=True)
            observations = await self.list_day(date)
            lines = [
                "".join((
                    f"- {item.occurred_at.astimezone(SETTINGS.local_timezone):%H:%M} ",
                    f"— {plain(item.text)} ({item.certainty}; source: {plain(item.source)})",
                ))
                for item in observations
            ]
            async with ObsidianService().daily_note(
                date=date,
                create_if_not_exists=True,
                read_only=False,
            ) as note:
                section = note.get_section(
                    (format_human_date(date), "Recorded activities"),
                    create_if_not_exists=True,
                )
                section.sections.clear()
                section.replace_content("\n".join(lines))

        return result
