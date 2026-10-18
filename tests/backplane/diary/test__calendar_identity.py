"""Calendar review decisions survive edits without conflating recurring occurrences."""

from __future__ import annotations

import datetime as dt

import pytest

from backplane.diary.collector import CalendarEvent, CalendarEvents, build_snapshot
from backplane.diary.models import (
    DiaryDecision,
    DiaryReviewResponse,
    retain_entry_aliases,
)
from backplane.diary.render import reviewed_entries


@pytest.mark.parametrize("all_day", [False, True])
def test__calendar_source_identity_survives_title_and_time_edits(
    *,
    all_day: bool,
) -> None:
    """Source UID and recurrence identity remain stable across mutable calendar fields."""
    date = dt.date(2026, 10, 17)
    now = dt.datetime(2026, 10, 18, tzinfo=dt.UTC)
    event = CalendarEvent.model_validate({
        "uid": "meeting-1",
        "recurrence_id": "20261017",
        "status": None,
        "summary": "Original title",
        "start": {"date": "2026-10-17"}
        if all_day
        else {"dateTime": "2026-10-17T10:00:00+00:00"},
        "end": {"date": "2026-10-18"}
        if all_day
        else {"dateTime": "2026-10-17T11:00:00+00:00"},
    })
    legacy = build_snapshot(
        date,
        now,
        [],
        [],
        {
            "calendar.test": CalendarEvents(
                events=[event.model_copy(update={"uid": None})],
            ),
        },
    )
    first = retain_entry_aliases(
        build_snapshot(
            date,
            now,
            [],
            [],
            {"calendar.test": CalendarEvents(events=[event])},
        ),
        legacy,
    )
    edited = CalendarEvent.model_validate(
        event.model_dump(by_alias=True)
        | {
            "summary": "Edited title",
            "end": {"date": "2026-10-19"}
            if all_day
            else {"dateTime": "2026-10-17T12:00:00+00:00"},
        },
    )
    second = retain_entry_aliases(
        build_snapshot(
            date,
            now,
            [],
            [],
            {"calendar.test": CalendarEvents(events=[edited])},
        ),
        first,
    )
    assert first.entries[0].id == second.entries[0].id
    responses = [
        DiaryReviewResponse(
            request_id="review-1",
            decisions=[DiaryDecision(entry_id=legacy.entries[0].id, outcome="confirmed")],
        ),
    ]
    reviewed = reviewed_entries(second, responses)
    assert reviewed[0].text == "Attended: Edited title (confirmed by Will)"
    assert not reviewed[0].needs_confirmation
    responses.append(
        DiaryReviewResponse(
            request_id="correction-1",
            decisions=[DiaryDecision(entry_id=second.entries[0].id, outcome="dismissed")],
        ),
    )
    assert reviewed_entries(second, responses) == []


@pytest.mark.parametrize("use_recurrence_id", [False, True])
def test__recurrences_with_shared_uid_have_distinct_identities(
    *,
    use_recurrence_id: bool,
) -> None:
    """Recurrence identifiers or explicit recurring start boundaries distinguish instances."""
    events = [
        CalendarEvent.model_validate({
            "uid": "series-1",
            "recurrence_id": f"occurrence-{hour}" if use_recurrence_id else None,
            "rrule": "FREQ=DAILY",
            "summary": "Recurring appointment",
            "start": {"dateTime": f"2026-10-17T{hour}:00:00+00:00"},
            "end": {"dateTime": f"2026-10-17T{hour}:30:00+00:00"},
        })
        for hour in ("10", "11")
    ]
    snapshot = build_snapshot(
        dt.date(2026, 10, 17),
        dt.datetime(2026, 10, 18, tzinfo=dt.UTC),
        [],
        [],
        {"calendar.test": CalendarEvents(events=events)},
    )
    assert len({entry.id for entry in snapshot.entries}) == 2


def test__identical_calendar_descriptions_do_not_share_legacy_confirmations() -> None:
    """Two source IDs with identical titles and times never inherit an ambiguous decision."""
    events = [
        CalendarEvent.model_validate({
            "uid": uid,
            "summary": "Meeting",
            "start": {"dateTime": "2026-10-17T10:00:00+00:00"},
            "end": {"dateTime": "2026-10-17T11:00:00+00:00"},
        })
        for uid in ("one", "two")
    ]
    snapshot = build_snapshot(
        dt.date(2026, 10, 17),
        dt.datetime(2026, 10, 18, tzinfo=dt.UTC),
        [],
        [],
        {"calendar.test": CalendarEvents(events=events)},
    )
    assert len({entry.id for entry in snapshot.entries}) == 2
    assert all(not entry.aliases for entry in snapshot.entries)


@pytest.mark.parametrize("original_state", ["renamed", "removed", "absent_revision"])
def test__new_event_cannot_claim_another_events_legacy_confirmation(
    original_state: str,
) -> None:
    """Legacy confirmation stays with its UID even when another event reuses its wording."""
    date = dt.date(2026, 10, 17)
    now = dt.datetime(2026, 10, 18, tzinfo=dt.UTC)
    original = CalendarEvent.model_validate({
        "summary": "Meeting",
        "start": {"dateTime": "2026-10-17T10:00:00+00:00"},
        "end": {"dateTime": "2026-10-17T11:00:00+00:00"},
    })
    snapshot = build_snapshot(
        date,
        now,
        [],
        [],
        {"calendar.test": CalendarEvents(events=[original])},
    )
    response = DiaryReviewResponse(
        request_id="legacy-review",
        decisions=[DiaryDecision(entry_id=snapshot.entries[0].id, outcome="confirmed")],
    )
    identified = original.model_copy(update={"uid": "original"})
    renamed = identified.model_copy(update={"summary": "Renamed meeting"})
    replacement = original.model_copy(update={"uid": "replacement"})
    revisions = [[identified]]
    if original_state == "absent_revision":
        revisions.append([])
    elif original_state == "renamed":
        revisions.append([renamed])

    revisions.append(
        [renamed, replacement] if original_state == "renamed" else [replacement],
    )
    for events in revisions:
        snapshot = retain_entry_aliases(
            build_snapshot(
                date,
                now,
                [],
                [],
                {"calendar.test": CalendarEvents(events=events)},
            ),
            snapshot,
        )

    reviewed = reviewed_entries(snapshot, [response])
    assert [(entry.text, entry.needs_confirmation) for entry in reviewed] == (
        [("Attended: Renamed meeting (confirmed by Will)", False)]
        if original_state == "renamed"
        else []
    ) + [("Scheduled: Meeting", True)]
