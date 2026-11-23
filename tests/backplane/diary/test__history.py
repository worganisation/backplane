"""History queries retain latest revisions and honest metric coverage."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from backplane.diary.history import DiaryHistoryService
from backplane.diary.models import DiarySnapshot, HabitMeasurement
from backplane.utils import exc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_history_uses_latest_revisions_and_missing_days(
    context_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Superseded measurements and unobserved days never inflate period totals."""
    service = DiaryHistoryService(context_session_factory)
    start = dt.date(2026, 1, 1)
    now = dt.datetime(2026, 1, 4, tzinfo=dt.UTC)
    await service.store_snapshot(
        DiarySnapshot(date=start, collected_at=now, metrics={"steps": 100}),
    )
    await service.store_snapshot(
        DiarySnapshot(
            date=start,
            collected_at=now + dt.timedelta(seconds=1),
            metrics={"steps": 80, "weight_kg": 70},
        ),
    )
    await service.store_snapshot(
        DiarySnapshot(
            date=start + dt.timedelta(days=1),
            collected_at=now,
            metrics={"steps": 0},
            missing=["Weight"],
        ),
    )

    period = await service.summarize(start, start + dt.timedelta(days=2))

    assert period.missing_dates == [start + dt.timedelta(days=2)]
    assert period.metrics["steps"].model_dump() == {
        "observed_days": 2,
        "missing_days": 1,
        "total": 80,
        "average": 40,
        "minimum": 0,
        "maximum": 80,
        "first": 80,
        "last": 0,
    }
    assert period.metrics["weight_kg"].total is None
    assert period.metrics["weight_kg"].observed_days == 1
    assert period.source_gaps == {start + dt.timedelta(days=1): ["Weight"]}
    day = await service.get_day(start)
    assert day is not None
    assert day.metrics["steps"] == 80
    assert await service.get_day(start + dt.timedelta(days=2)) is None


@pytest.mark.parametrize("days", [-1, 366])
async def test_summary_rejects_unbounded_ranges(
    context_session_factory: async_sessionmaker[AsyncSession],
    days: int,
) -> None:
    """Reversed and overlarge ranges are rejected before querying storage."""
    service = DiaryHistoryService(context_session_factory)
    start = dt.date(2026, 1, 1)
    with pytest.raises(exc.BadRequestError):
        _ = await service.summarize(start, start + dt.timedelta(days=days))


async def test_structured_tracking_distinguishes_zero_and_missing(
    context_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Covered empty mood days and zero habit counts differ from missing source records."""
    service = DiaryHistoryService(context_session_factory)
    start = dt.date(2026, 1, 1)
    now = dt.datetime(2026, 1, 4, tzinfo=dt.UTC)
    for offset, scores, count in ((0, [2.0, 4.0], 2), (1, [], 0)):
        await service.store_snapshot(
            DiarySnapshot(
                date=start + dt.timedelta(days=offset),
                collected_at=now,
                mood_scores=scores,
                habits={"water": HabitMeasurement(name="Water", count=count)},
            ),
        )

    period = await service.summarize(start, start + dt.timedelta(days=2))
    assert period.mood.model_dump() == {"covered_days": 2, "samples": 2, "average": 3}
    assert period.habits["water"].model_dump() == {
        "name": "Water",
        "observed_days": 2,
        "missing_days": 1,
        "completed_days": 1,
        "completions": 2,
    }
    empty = await service.get_day(start + dt.timedelta(days=1))
    assert empty is not None
    assert empty.mood_scores == []
    assert empty.habits["water"].count == 0
