"""Source-date, certainty and daylight-saving behavior of automatic diary collection."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

from backplane.diary.collector import (
    ACTIVITY,
    DISTANCE,
    MOOD,
    MUSIC,
    PERSON,
    STEPS,
    WEIGHT,
    CalendarEvent,
    CalendarEvents,
    HAState,
    _number,
    _timestamp,
    build_snapshot,
    day_bounds,
)
from backplane.utils import SETTINGS

if TYPE_CHECKING:
    from pydantic import JsonValue

DATE = dt.date(2026, 10, 17)
START = dt.datetime(2026, 10, 17, tzinfo=dt.UTC)
NOW = START + dt.timedelta(hours=21)


def state(entity: str, value: str, minutes: int = 0, **attributes: JsonValue) -> HAState:
    """Build a source state at an explicit time."""
    timestamp = START + dt.timedelta(minutes=minutes)
    return HAState(
        entity_id=entity,
        state=value,
        attributes=attributes,
        last_updated=timestamp,
        last_changed=timestamp,
    )


def mood_state() -> HAState:
    """Provide dated mood coverage with an exact multiline note."""
    return state(
        MOOD,
        "good",
        diary_history_start="2026-09-20",
        diary_history_end="2026-10-17",
        diary_checkins=[
            {
                "id": "checkin-1",
                "logical_date": "2026-10-17",
                "occurred_at": "2026-10-18T02:00:00+00:00",
                "mood": "good",
                "score": 4,
                "note": "First line.\nSecond line.",
            },
        ],
    )


def test_source_dates_corrections_and_calendar_certainty() -> None:
    """Latest corrected counters win; a scheduled meeting does not imply attendance."""
    history = [
        [
            state(STEPS, "1000", 1, endTime=NOW.isoformat()),
            state(STEPS, "980", 2, endTime=NOW.isoformat()),
        ],
        [state(DISTANCE, "1500", 2, endTime=NOW.isoformat())],
        [state(MUSIC, "off"), state(MUSIC, "on", 30), state(MUSIC, "off", 90)],
        [
            state(WEIGHT, "90.5", 20, date=DATE.isoformat(), id=59),
            state(WEIGHT, "90.3", 21, date=DATE.isoformat(), id=59),
        ],
    ]
    event = CalendarEvent.model_validate({
        "start": {"dateTime": "2026-10-17T10:00:00+00:00"},
        "end": {"dateTime": "2026-10-17T11:00:00+00:00"},
        "summary": "Project meeting",
        "description": "PRIVATE JOIN URL",
    })
    snapshot = build_snapshot(
        DATE,
        NOW,
        [
            mood_state(),
            state(
                "sensor.will_habit_1_status",
                "not_due",
                configured=True,
                habit_name="Water",
                completion_history={DATE.isoformat(): 2},
            ),
        ],
        history,
        {"calendar.work": CalendarEvents(events=[event])},
    )
    assert snapshot.metrics == {
        "steps": 980,
        "distance_km": 1.5,
        "music_minutes": 60,
        "weight_kg": 90.3,
    }
    assert len([e for e in snapshot.entries if e.kind == "weight"]) == 1
    assert next(e for e in snapshot.entries if e.kind == "calendar").needs_confirmation
    assert "PRIVATE" not in snapshot.model_dump_json()
    assert "First line.\nSecond line." in next(
        e.text for e in snapshot.entries if e.kind == "mood"
    )
    assert next(e for e in snapshot.entries if e.kind == "habit").text.endswith("(2)")


@pytest.mark.parametrize(
    ("date", "hours"),
    [(dt.date(2026, 3, 29), 23), (dt.date(2026, 10, 25), 25)],
)
def test_dst_duration_is_elapsed_time(
    date: dt.date,
    hours: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full day of listening counts real elapsed hours on both DST transitions."""
    monkeypatch.setattr(SETTINGS, "local_timezone", ZoneInfo("Europe/London"))
    start, end = day_bounds(date)
    music = HAState(entity_id=MUSIC, state="on", last_updated=start, last_changed=start)
    result = build_snapshot(date, end, [], [[music]], {})
    assert result.metrics["music_minutes"] == hours * 60


def test_location_attribute_updates_coalesce_before_jitter_filtering() -> None:
    """Frequent updates keep a real visit and produce only a tentative outing."""
    places = [state(PERSON, "home")]
    places += [state(PERSON, "Park", minute) for minute in range(10, 30)]
    places += [state(PERSON, "home", 30)]
    result = build_snapshot(DATE, NOW, [], [places, [state(ACTIVITY, "walking")]], {})
    assert any(e.text.startswith("At home") for e in result.entries)
    assert any(e.text.startswith("At Park") for e in result.entries)
    outing = next(e for e in result.entries if e.kind == "outing")
    assert outing.started_at == START + dt.timedelta(minutes=10)
    assert outing.needs_confirmation
    assert "was this a dog walk?" in outing.text


@pytest.mark.parametrize("initial", ["unavailable", "not_home"])
def test_missing_home_boundary_never_invents_outing(initial: str) -> None:
    """Unknown history and day-clipped departures cannot prove an outing."""
    history = [
        [
            state(PERSON, initial),
            state(PERSON, "not_home", 10),
            state(PERSON, "home", 40),
        ],
        [state(ACTIVITY, "walking")],
    ]
    result = build_snapshot(DATE, NOW, [], history, {})
    assert not any(e.kind == "outing" for e in result.entries)


def test_unknown_gap_breaks_outing_and_music_coverage() -> None:
    """Unknown intervals are not silently bridged or counted as no activity."""
    history = [
        [
            state(PERSON, "home"),
            state(PERSON, "not_home", 10),
            state(PERSON, "unavailable", 15),
            state(PERSON, "home", 40),
        ],
        [state(ACTIVITY, "walking")],
        [state(MUSIC, "on"), state(MUSIC, "unavailable", 10)],
    ]
    result = build_snapshot(DATE, NOW, [], history, {})
    assert not any(e.kind == "outing" for e in result.entries)
    assert "music_minutes" not in result.metrics
    assert "Spotify listening coverage" in result.missing


def test_all_day_and_future_calendar_entries_remain_scheduled() -> None:
    """All-day dates and future appointments have no invented completion time."""
    events = [
        CalendarEvent.model_validate({
            "start": {"date": "2026-10-17"},
            "end": {"date": "2026-10-18"},
            "summary": "Holiday",
        }),
        CalendarEvent.model_validate({
            "start": {"dateTime": "2026-10-17T23:00:00Z"},
            "end": {"dateTime": "2026-10-17T23:30:00Z"},
            "summary": "Call",
        }),
    ]
    result = build_snapshot(
        DATE,
        NOW,
        [],
        [],
        {"calendar.personal": CalendarEvents(events=events)},
    )
    assert all(
        not e.needs_confirmation and e.text.startswith("Scheduled:")
        for e in result.entries
    )
    assert next(e for e in result.entries if "Holiday" in e.text).started_at is None


@pytest.mark.parametrize("value", [None, True, "nan", "inf", "-1", "no", {}, []])
def test_invalid_quantities_are_missing(value: JsonValue) -> None:
    """Invalid or unavailable measurements never become zero totals."""
    assert _number(value) is None


@pytest.mark.parametrize("value", [None, 1, "wrong", "2026-10-17T10:00:00"])
def test_ambiguous_timestamps_are_missing(value: JsonValue) -> None:
    """Naive times cannot be silently assigned a timezone."""
    assert _timestamp(value) is None
