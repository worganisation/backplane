"""Automation observations survive export failures and source reconciliation."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

from backplane.diary.history import DiaryHistoryService
from backplane.diary.models import DiarySnapshot
from backplane.diary.observations import DiaryObservationCreate, DiaryObservationService
from backplane.diary.service import DiaryService
from backplane.operations.daily_notes import read_daily_note
from backplane.utils import SETTINGS, exc

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.utils import AsyncPath


async def test_observation_survives_retry_and_automatic_resync(
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Receipt persistence precedes export and automatic diary refresh preserves activities."""
    _ = obsidian_vault
    _ = mocker.patch.object(SETTINGS, "local_timezone", ZoneInfo("Europe/London"))
    service = DiaryObservationService(context_session_factory)
    request = DiaryObservationCreate(
        source="dog-walk-automation",
        idempotency_key="walk-1",
        occurred_at=dt.datetime(2026, 7, 1, 23, 30, tzinfo=dt.UTC),
        text="Possible dog walk with Will",
        certainty="candidate",
    )
    mock_export = mocker.patch(
        "backplane.diary.observations.ObsidianService.daily_note",
        side_effect=OSError("disk full"),
    )
    with pytest.raises(OSError, match="disk full"):
        _ = await service.record(request)

    date = dt.date(2026, 7, 2)
    assert len(await service.list_day(date)) == 1
    mocker.stop(mock_export)
    result = await service.record(request)
    assert result.created is False
    assert result.event.status == "tentative"
    assert (await service.record(request)).event.id == result.event.id
    day = await DiaryHistoryService(context_session_factory).get_day(date)
    assert day is not None
    assert day.observations[0].certainty == "candidate"
    assert day.observations[0].text == request.text

    diary = DiaryService(context_session_factory)
    await diary.store_snapshot(
        DiarySnapshot(
            date=date,
            collected_at=request.occurred_at + dt.timedelta(days=1),
            metrics={"steps": 500},
        ),
    )
    _ = await diary.render(date)
    note = await read_daily_note(date)
    assert "Recorded activities" in note
    assert "Possible dog walk with Will" in note
    assert "candidate; source: dog-walk-automation" in note
    assert "Automatic diary" in note
    assert len(await service.list_day(date)) == 1


async def test_observation_key_is_scoped_to_source_and_rejects_changed_text(
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
) -> None:
    """Different producers may reuse keys but one producer cannot silently rewrite a receipt."""
    _ = obsidian_vault
    service = DiaryObservationService(context_session_factory)
    request = DiaryObservationCreate(
        source="calendar",
        idempotency_key="event-1",
        occurred_at=dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC),
        text="Will confirmed attending",
        certainty="confirmed",
    )
    first = await service.record(request)
    assert first.event.status == "confirmed"
    with pytest.raises(exc.ConflictError):
        _ = await service.record(request.model_copy(update={"text": "Different event"}))

    second = await service.record(request.model_copy(update={"source": "voice"}))
    assert second.event.id != first.event.id
    assert len(await service.list_day(request.occurred_at.date())) == 2
