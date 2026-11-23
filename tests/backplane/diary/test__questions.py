"""Contextual questions retain exact identity and never imply attendance."""

from __future__ import annotations

import datetime as dt

from backplane.diary.models import (
    DiaryDecision,
    DiaryEntry,
    DiaryReviewResponse,
    DiarySnapshot,
)
from backplane.diary.questions import review_question

NOW = dt.datetime(2026, 10, 18, 21, tzinfo=dt.UTC)


def test_question_focuses_latest_completed_unanswered_event() -> None:
    """Future, all-day, confirmed and dismissed entries cannot become questions."""
    meeting = DiaryEntry(
        id="meeting",
        source="calendar.will_personal",
        kind="calendar",
        text="Scheduled: Project\nmeeting",
        started_at=NOW - dt.timedelta(hours=3),
        ended_at=NOW - dt.timedelta(hours=2),
        needs_confirmation=True,
    )
    walk = DiaryEntry(
        id="walk",
        source="person.will",
        kind="outing",
        text="Possible walk",
        started_at=NOW - dt.timedelta(hours=2),
        ended_at=NOW - dt.timedelta(hours=1),
        needs_confirmation=True,
    )
    snapshot = DiarySnapshot(
        date=NOW.date(),
        collected_at=NOW,
        entries=[
            meeting,
            walk,
            meeting.model_copy(
                update={"id": "future", "ended_at": NOW + dt.timedelta(hours=1)},
            ),
            meeting.model_copy(
                update={"id": "all-day", "started_at": None, "ended_at": None},
            ),
        ],
    )
    question, focus = review_question(snapshot, [])
    assert focus == "walk"
    assert "dog walk?" in question
    responses = [
        DiaryReviewResponse(
            request_id="reply",
            decisions=[
                DiaryDecision(entry_id="walk", outcome="dismissed"),
            ],
        ),
    ]
    question, focus = review_question(snapshot, responses)
    assert focus == "meeting"
    assert "Did you attend 'Project meeting'" in question
    responses.append(
        DiaryReviewResponse(
            request_id="reply2",
            decisions=[
                DiaryDecision(entry_id="meeting", outcome="confirmed"),
            ],
        ),
    )
    question, focus = review_question(snapshot, responses)
    assert focus is None
    assert question.startswith("Anything to add")
