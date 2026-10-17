"""Diary timestamps and dates are resolved by the server, independent of the model."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Self
from zoneinfo import ZoneInfo

import pytest

from backplane.mcp.obsidian import record_diary
from backplane.operations.daily_notes import read_daily_note
from backplane.utils import SETTINGS, exc

if TYPE_CHECKING:
    from backplane.utils import AsyncPath


class _Clock(dt.datetime):
    @classmethod
    def now(cls, tz: dt.tzinfo | None = None) -> Self:
        return cls(2026, 10, 18, 0, 1, tzinfo=tz)


async def test__record_diary__timestamps_past_day_and_preserves_entries(
    obsidian_vault: AsyncPath,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past-day captures retain actual capture time and append without losing earlier text."""
    _ = obsidian_vault
    monkeypatch.setattr("backplane.operations.daily_notes.dt.datetime", _Clock)
    monkeypatch.setattr(SETTINGS, "local_timezone", ZoneInfo("Europe/London"))
    previous_day = dt.date(2026, 10, 17)

    result = await record_diary("Walked for 25 minutes at 16:00.", previous_day)
    _ = await record_diary("Felt good afterward.", previous_day)
    note = await read_daily_note(previous_day)

    assert result == "Diary entry saved to 2026-10-17."
    assert "Recorded 2026-10-18 00:01 +0100 — Walked for 25 minutes at 16:00." in note
    assert "Recorded 2026-10-18 00:01 +0100 — Felt good afterward." in note

    _ = await record_diary("Today's capture.")
    assert "Today's capture." in await read_daily_note(dt.date(2026, 10, 18))


async def test__record_diary__rejects_blank_content(obsidian_vault: AsyncPath) -> None:
    """Whitespace does not create a timestamp-only note."""
    _ = obsidian_vault
    with pytest.raises(exc.BadRequestError):
        _ = await record_diary("  \n ")
