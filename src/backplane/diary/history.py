"""Read collected diary history without collecting sources or invoking a model."""

from __future__ import annotations

import datetime as dt

from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select

from backplane.context.schemas import ContextEventStatus
from backplane.context.tables import ContextEventRow
from backplane.diary.models import DiaryEntry, DiarySnapshot, HabitMeasurement
from backplane.diary.observations import DiaryObservation, DiaryObservationService
from backplane.diary.render import reviewed_entries
from backplane.diary.service import DiaryService
from backplane.utils import exc, today

_MAX_DAYS = 366


class DiaryDay(BaseModel):
    """Latest automatic observations and explicit review notes for one collected day."""

    date: dt.date
    collected_at: AwareDatetime
    entries: list[DiaryEntry]
    metrics: dict[str, float]
    missing: list[str]
    review_notes: list[str]
    partial_day: bool
    mood_scores: list[float] | None
    habits: dict[str, HabitMeasurement]
    observations: list[DiaryObservation] = Field(default_factory=list)


class MoodSummary(BaseModel):
    """Mood coverage and sample-weighted score; no score is inferred for silence."""

    covered_days: int
    samples: int
    average: float | None


class HabitSummary(BaseModel):
    """Completion coverage for one stable source identity."""

    name: str
    observed_days: int
    missing_days: int
    completed_days: int
    completions: float


class MetricSummary(BaseModel):
    """Observed measurements with coverage; absent measurements never count as zero."""

    observed_days: int
    missing_days: int
    total: float | None
    average: float
    minimum: float
    maximum: float
    first: float
    last: float


class DiaryPeriod(BaseModel):
    """Inclusive date-range coverage and deterministic quantitative summaries."""

    start: dt.date
    end: dt.date
    collected_dates: list[dt.date]
    missing_dates: list[dt.date]
    partial_dates: list[dt.date]
    source_gaps: dict[dt.date, list[str]]
    metrics: dict[str, MetricSummary] = Field(default_factory=dict)
    mood: MoodSummary
    habits: dict[str, HabitSummary] = Field(default_factory=dict)


class DiaryHistoryService(DiaryService):
    """Query the durable latest snapshots independently of notification availability."""

    async def get_day(self, date: dt.date) -> DiaryDay | None:
        """Return the latest collected day, or null when no snapshot exists."""
        observations = await DiaryObservationService(self._session_factory).list_day(date)
        async with self._session_factory() as session:
            if (row := await self._latest(session, date, "diary_snapshot")) is None:
                if not observations:
                    return None
                snapshot = DiarySnapshot(
                    date=date,
                    collected_at=max(o.occurred_at for o in observations),
                    missing=["Automatic diary sources have not been collected"],
                )
            else:
                snapshot = DiarySnapshot.model_validate(row.payload)

            responses = await self._responses(session, date)

        return DiaryDay(
            date=date,
            collected_at=snapshot.collected_at,
            entries=reviewed_entries(snapshot, responses),
            metrics=snapshot.metrics,
            missing=snapshot.missing,
            review_notes=list(dict.fromkeys(r.note for r in responses if r.note.strip())),
            partial_day=date >= today(),
            mood_scores=snapshot.mood_scores,
            habits=snapshot.habits,
            observations=observations,
        )

    async def summarize(self, start: dt.date, end: dt.date) -> DiaryPeriod:
        """Summarize up to 366 inclusive days without interpreting missing values.

        Returns:
            Coverage and measurements from the latest revision of each collected date.

        Raises:
            BadRequestError: The date range is reversed or exceeds one leap year.
        """
        days = (end - start).days + 1
        if not 1 <= days <= _MAX_DAYS:
            raise exc.BadRequestError(
                message="Choose an inclusive range of 1 to 366 days.",
            )

        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ContextEventRow)
                .where(
                    ContextEventRow.user_id == "will",
                    ContextEventRow.source == "automatic_diary",
                    ContextEventRow.kind == "diary_snapshot",
                    ContextEventRow.status != ContextEventStatus.SUPERSEDED.value,
                    ContextEventRow.correlation_key >= start.isoformat(),
                    ContextEventRow.correlation_key <= end.isoformat(),
                )
                .order_by(ContextEventRow.correlation_key, ContextEventRow.created_at),
            )
            snapshots = {
                snapshot.date: snapshot
                for row in rows
                if (snapshot := DiarySnapshot.model_validate(row.payload))
            }

        values: dict[str, list[float]] = {}
        for snapshot in snapshots.values():
            for key, value in snapshot.metrics.items():
                values.setdefault(key, []).append(value)

        moods = [score for s in snapshots.values() for score in (s.mood_scores or [])]
        habits: dict[str, HabitSummary] = {}
        for snapshot in snapshots.values():
            for source, habit in snapshot.habits.items():
                summary = habits.setdefault(
                    source,
                    HabitSummary(
                        name=habit.name,
                        observed_days=0,
                        missing_days=days,
                        completed_days=0,
                        completions=0,
                    ),
                )
                summary.name = habit.name
                summary.observed_days += 1
                summary.missing_days -= 1
                summary.completed_days += int(habit.count > 0)
                summary.completions += habit.count

        return DiaryPeriod(
            start=start,
            end=end,
            collected_dates=list(snapshots),
            missing_dates=[
                date
                for offset in range(days)
                if (date := start + dt.timedelta(days=offset)) not in snapshots
            ],
            partial_dates=[date for date in snapshots if date >= today()],
            source_gaps={date: s.missing for date, s in snapshots.items() if s.missing},
            mood=MoodSummary(
                covered_days=sum(s.mood_scores is not None for s in snapshots.values()),
                samples=len(moods),
                average=sum(moods) / len(moods) if moods else None,
            ),
            habits=habits,
            metrics={
                key: MetricSummary(
                    observed_days=len(samples),
                    missing_days=days - len(samples),
                    total=sum(samples)
                    if key in {"steps", "distance_km", "music_minutes"}
                    else None,
                    average=sum(samples) / len(samples),
                    minimum=min(samples),
                    maximum=max(samples),
                    first=samples[0],
                    last=samples[-1],
                )
                for key, samples in values.items()
            },
        )
