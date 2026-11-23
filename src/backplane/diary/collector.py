"""Collect the owner's allowlisted HA sources without inferring lived experiences."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections import Counter
from typing import Annotated

import aiohttp
from pydantic import AwareDatetime, BaseModel, Field, JsonValue, TypeAdapter

from backplane.diary.models import DiaryEntry, DiarySnapshot, HabitMeasurement, entry_id
from backplane.utils import SETTINGS, exc

PERSON = "person.will"
ACTIVITY = "sensor.will_s_pixel_6_pro_detected_activity"
MUSIC = "binary_sensor.will_listening_to_music"
STEPS = "sensor.will_s_pixel_6_pro_daily_steps"
DISTANCE = "sensor.will_s_pixel_6_pro_daily_distance"
WEIGHT = "sensor.wger_will_body_weight"
MOOD = "sensor.will_mood_summary"
CALENDARS = ("calendar.will_personal", "calendar.will_garside_yantratech_com_2")
_MINIMUM_VISIT_SECONDS = 180
_MINIMUM_OUTING_SECONDS = 600
_MINIMUM_WALKING_SECONDS = 300
_INVALID = {"unknown", "unavailable", "none", ""}
_MAX_MOOD_SCORE = 5


class HAState(BaseModel):
    """The state and source attributes needed for diary collection."""

    entity_id: str
    state: str
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    last_updated: AwareDatetime
    last_changed: AwareDatetime


class CalendarBoundary(BaseModel):
    """Home Assistant REST calendar time, or an all-day date."""

    date_time: Annotated[str | None, Field(alias="dateTime")] = None
    date: dt.date | None = None


class CalendarEvent(BaseModel):
    """Calendar metadata deliberately excluding descriptions and attendee addresses."""

    start: CalendarBoundary
    end: CalendarBoundary
    summary: str
    status: str | None = "confirmed"
    uid: str | None = None
    recurrence_id: str | None = None
    rrule: str | None = None


class CalendarEvents(BaseModel):
    """A complete calendar query result."""

    events: list[CalendarEvent]


def day_bounds(date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Return explicit local midnights, including DST-short and DST-long days."""
    return (
        dt.datetime.combine(date, dt.time(), SETTINGS.local_timezone).astimezone(dt.UTC),
        dt.datetime.combine(
            date + dt.timedelta(days=1),
            dt.time(),
            SETTINGS.local_timezone,
        ).astimezone(dt.UTC),
    )


def _timestamp(value: JsonValue | None) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo else None


def _number(value: JsonValue | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _intervals(
    states: list[HAState],
    start: dt.datetime,
    end: dt.datetime,
) -> list[tuple[str, dt.datetime, dt.datetime]]:
    if not states:
        return []

    ordered = sorted(states, key=lambda s: s.last_updated)
    intervals: list[tuple[str, dt.datetime, dt.datetime]] = []
    for state, following in zip(
        ordered,
        [item.last_updated for item in ordered[1:]] + [end],
        strict=True,
    ):
        began, finished = max(start, state.last_updated), min(end, following)
        if began >= finished:
            continue
        if intervals and intervals[-1][0] == state.state and intervals[-1][2] == began:
            intervals[-1] = (state.state, intervals[-1][1], finished)
        else:
            intervals.append((state.state, began, finished))
    return intervals


def _daily_measurement(
    states: list[HAState],
    date: dt.date,
) -> float | None:
    candidates = [
        state
        for state in states
        if (source_time := _timestamp(state.attributes.get("endTime")))
        and source_time.astimezone(SETTINGS.local_timezone).date() == date
        and _number(state.state) is not None
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda s: s.last_updated)
    return _number(latest.state)


def _locations(
    history: dict[str, list[HAState]],
    start: dt.datetime,
    end: dt.datetime,
) -> list[DiaryEntry]:
    entries: list[DiaryEntry] = []
    intervals = _intervals(history.get(PERSON, []), start, end)
    stable: list[tuple[str, dt.datetime, dt.datetime]] = []
    for place, began, ended in intervals:
        if (
            place not in _INVALID
            and (ended - began).total_seconds() < _MINIMUM_VISIT_SECONDS
        ):
            continue
        if (
            stable
            and stable[-1][0] == place
            and began - stable[-1][2] <= dt.timedelta(minutes=5)
        ):
            stable[-1] = (place, stable[-1][1], ended)
        else:
            stable.append((place, began, ended))

    for place, began, ended in stable:
        if place in _INVALID | {"not_home"}:
            continue
        entries.append(
            DiaryEntry(
                id=entry_id(PERSON, f"{place}:{began.isoformat()}:{ended.isoformat()}"),
                source=PERSON,
                kind="visit",
                text=f"At {place} (location estimate; interval within this day)",
                started_at=began,
                ended_at=ended,
            ),
        )

    return entries + _outings(stable, _intervals(history.get(ACTIVITY, []), start, end))


def _outings(
    stable: list[tuple[str, dt.datetime, dt.datetime]],
    walking: list[tuple[str, dt.datetime, dt.datetime]],
) -> list[DiaryEntry]:
    entries: list[DiaryEntry] = []
    away_since: dt.datetime | None = None
    home_seen = False
    for place, began, _ended in stable:
        if place in _INVALID:
            away_since = None
            home_seen = False
        elif place != "home" and away_since is None and home_seen:
            away_since = began
        elif place == "home" and away_since is not None:
            duration = (began - away_since).total_seconds()
            walking_seconds = sum(
                max(0, (min(began, finish) - max(away_since, begin)).total_seconds())
                for activity, begin, finish in walking
                if activity == "walking"
            )
            if (
                duration >= _MINIMUM_OUTING_SECONDS
                and walking_seconds >= _MINIMUM_WALKING_SECONDS
            ):
                entries.append(
                    DiaryEntry(
                        id=entry_id(
                            "outing",
                            f"{away_since.isoformat()}:{began.isoformat()}",
                        ),
                        source=f"{PERSON},{ACTIVITY}",
                        kind="outing",
                        text="Away from home with walking activity; was this a dog walk?",
                        started_at=away_since,
                        ended_at=began,
                        needs_confirmation=True,
                    ),
                )
            away_since = None
        if place == "home":
            home_seen = True
    return entries


def _mood_entries(
    states: dict[str, HAState],
    date: dt.date,
    missing: list[str],
    mood_scores: list[float],
) -> list[DiaryEntry]:
    entries: list[DiaryEntry] = []
    mood = states.get(MOOD)
    attributes = mood.attributes if mood else {}
    date_text = date.isoformat()
    if not (
        str(attributes.get("diary_history_start", "9999"))
        <= date_text
        <= str(attributes.get("diary_history_end", ""))
        and isinstance(check_ins := attributes.get("diary_checkins"), list)
    ):
        missing.append("Dated mood records")
    else:
        for check_in in check_ins:
            if (
                not isinstance(check_in, dict)
                or check_in.get("logical_date") != date_text
            ):
                continue
            text = f"Mood: {check_in.get('mood')} ({check_in.get('score')}/5)"
            if (
                score := _number(check_in.get("score"))
            ) is not None and 1 <= score <= _MAX_MOOD_SCORE:
                mood_scores.append(score)
            if note := check_in.get("note"):
                text += f" — {note}"
            entries.append(
                DiaryEntry(
                    id=entry_id(MOOD, str(check_in.get("id"))),
                    source=MOOD,
                    kind="mood",
                    text=text,
                    started_at=_timestamp(check_in.get("occurred_at")),
                ),
            )

    return entries


def _habit_entries(
    states: dict[str, HAState],
    date: dt.date,
    missing: list[str],
    habits_by_source: dict[str, HabitMeasurement],
) -> list[DiaryEntry]:
    entries: list[DiaryEntry] = []
    date_text = date.isoformat()
    habits = [
        s
        for s in states.values()
        if s.entity_id.startswith("sensor.will_habit_")
        and s.entity_id.endswith("_status")
        and s.attributes.get("configured") is True
    ]
    if not habits:
        missing.append("Dated habit records")
    for habit in habits:
        history = habit.attributes.get("completion_history")
        if not isinstance(history, dict) or date_text not in history:
            missing.append(f"Dated habit records: {habit.attributes.get('habit_name')}")
            continue
        count = _number(history[date_text])
        if count is not None:
            habits_by_source[habit.entity_id] = HabitMeasurement(
                name=str(habit.attributes.get("habit_name", habit.entity_id)),
                count=count,
            )
        if count is not None and count > 0:
            entries.append(
                DiaryEntry(
                    id=entry_id(habit.entity_id, date_text),
                    source=habit.entity_id,
                    kind="habit",
                    text=f"Habit completed: {habit.attributes.get('habit_name')} ({count:g})",
                ),
            )
    return entries


def build_snapshot(
    date: dt.date,
    now: dt.datetime,
    states: list[HAState],
    history: list[list[HAState]],
    calendars: dict[str, CalendarEvents],
) -> DiarySnapshot:
    """Project source data into a complete, deterministic daily snapshot.

    Returns:
        The dated source projection, including missing-data indicators.
    """
    start, midnight = day_bounds(date)
    end = min(midnight, now)
    indexed = {s.entity_id: s for s in states}
    histories = {items[0].entity_id: items for items in history if items}
    missing: list[str] = []
    metrics: dict[str, float] = {}
    for entity, key, scale in ((STEPS, "steps", 1), (DISTANCE, "distance_km", 1000)):
        values = histories.get(entity, []) + (
            [indexed[entity]] if entity in indexed else []
        )
        if (value := _daily_measurement(values, date)) is not None:
            metrics[key] = round(value / scale, 3)
        else:
            missing.append(key)

    music = _intervals(histories.get(MUSIC, []), start, end)
    if music and music[0][1] <= start and all(s not in _INVALID for s, _, _ in music):
        metrics["music_minutes"] = round(
            sum(
                (finish - begin).total_seconds()
                for state, begin, finish in music
                if state == "on"
            )
            / 60,
        )
    else:
        missing.append("Spotify listening coverage")

    entries = _locations(histories, start, end)
    if not histories.get(PERSON):
        missing.append("Location history")
    mood_scores: list[float] = []
    habits: dict[str, HabitMeasurement] = {}
    entries.extend(_mood_entries(indexed, date, missing, mood_scores))
    entries.extend(_habit_entries(indexed, date, missing, habits))
    for state in sorted(
        histories.get(WEIGHT, []) + ([indexed[WEIGHT]] if WEIGHT in indexed else []),
        key=lambda item: item.last_updated,
    ):
        if (
            state.attributes.get("date") == date.isoformat()
            and (value := _number(state.state)) is not None
        ):
            key = str(state.attributes.get("id"))
            entries = [e for e in entries if e.id != entry_id(WEIGHT, key)]
            entries.append(
                DiaryEntry(
                    id=entry_id(WEIGHT, key),
                    source=WEIGHT,
                    kind="weight",
                    text=f"Weigh-in: {value:g} kg",
                ),
            )
            metrics["weight_kg"] = value

    entries.extend(_calendar_entries(calendars, date, now, midnight))
    entries.sort(key=lambda e: (e.started_at.isoformat() if e.started_at else "", e.id))
    return DiarySnapshot(
        date=date,
        collected_at=now,
        entries=entries,
        metrics=metrics,
        missing=sorted(set(missing)),
        mood_scores=None if "Dated mood records" in missing else mood_scores,
        habits=habits,
    )


def _calendar_entries(
    calendars: dict[str, CalendarEvents],
    date: dt.date,
    now: dt.datetime,
    midnight: dt.datetime,
) -> list[DiaryEntry]:
    entries: list[DiaryEntry] = []
    for calendar, result in sorted(calendars.items()):
        for event in result.events:
            if event.status == "cancelled":
                continue
            began = _timestamp(event.start.date_time)
            ended = _timestamp(event.end.date_time)
            if began is not None and began >= midnight:
                continue
            key = f"{event.start.model_dump_json()}:{event.end.model_dump_json()}:{event.summary}"
            legacy_id = entry_id(calendar, key)
            if event.uid:
                occurrence = event.recurrence_id
                if occurrence is None and event.rrule:
                    occurrence = began.isoformat() if began else str(event.start.date)
                key = json.dumps([event.uid, occurrence])
            entries.append(
                DiaryEntry(
                    id=entry_id(calendar, key),
                    aliases=[legacy_id] if event.uid else [],
                    source=calendar,
                    kind="calendar",
                    text=f"Scheduled: {event.summary}",
                    started_at=began,
                    ended_at=ended,
                    needs_confirmation=(ended is not None and ended <= now)
                    or (
                        ended is None
                        and date < now.astimezone(SETTINGS.local_timezone).date()
                    ),
                ),
            )
    alias_counts = Counter(alias for entry in entries for alias in entry.aliases)
    return [
        entry.model_copy(
            update={
                "aliases": [alias for alias in entry.aliases if alias_counts[alias] == 1],
            },
        )
        for entry in entries
    ]


async def collect_day(date: dt.date) -> DiarySnapshot:
    """Read allowlisted HA sources; request failures leave the durable snapshot intact.

    Returns:
        A complete source snapshot ready for persistence.

    Raises:
        BadRequestError: The date or explicit decisions are invalid.
        UserError: Required source configuration or dated exports are unavailable.
    """
    now = dt.datetime.now(SETTINGS.local_timezone)
    if date > now.date() or date < now.date() - dt.timedelta(days=27):
        message = "Diary collection requires a date in the last 28 days."
        raise exc.BadRequestError(message)
    url = SETTINGS.home_assistant_url
    if not url or not SETTINGS.home_assistant_token:
        message = "Home Assistant credentials are required for diary collection."
        raise exc.UserError(message)

    start, end = day_bounds(date)
    headers = {"Authorization": f"Bearer {SETTINGS.home_assistant_token}"}
    async with aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=25),
    ) as session:

        async def get(path: str, params: dict[str, str] | None = None) -> str:
            async with session.get(
                url / path,
                params=params,
            ) as response:
                response.raise_for_status()
                return await response.text()

        states = TypeAdapter(list[HAState]).validate_json(await get("api/states"))
        history = TypeAdapter(list[list[HAState]]).validate_json(
            await get(
                f"api/history/period/{start.isoformat()}",
                {
                    "filter_entity_id": f"{PERSON},{ACTIVITY},{MUSIC},{STEPS},{DISTANCE},{WEIGHT}",
                    "end_time": min(end, now).isoformat(),
                },
            ),
        )
        calendars: dict[str, CalendarEvents] = {}
        for calendar in CALENDARS:
            calendars[calendar] = CalendarEvents(
                events=TypeAdapter(list[CalendarEvent]).validate_json(
                    await get(
                        f"api/calendars/{calendar}",
                        {"start": start.isoformat(), "end": end.isoformat()},
                    ),
                ),
            )
    snapshot = build_snapshot(date, now, states, history, calendars)
    if any(item.startswith("Dated ") for item in snapshot.missing):
        message = "Dated mood and habit exports are unavailable; check AppDaemon before retrying."
        raise exc.UserError(message)
    return snapshot
