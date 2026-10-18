"""One concrete question grounded in the exact daily review snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backplane.diary.render import reviewed_entries
from backplane.utils import SETTINGS

if TYPE_CHECKING:
    from backplane.diary.models import DiaryReviewResponse, DiarySnapshot


def review_question(
    snapshot: DiarySnapshot,
    responses: list[DiaryReviewResponse],
) -> tuple[str, str | None]:
    """Return one unresolved completed-event question and its exact entry identity."""
    entries = [
        (entry, start, end)
        for entry in reviewed_entries(snapshot, responses)
        if entry.needs_confirmation
        and entry.kind in {"calendar", "outing"}
        and (start := entry.started_at) is not None
        and (end := entry.ended_at) is not None
        and end <= snapshot.collected_at
    ]
    if not entries:
        return (
            f"Anything to add to your diary for {snapshot.date:%A %d %B}?",
            None,
        )

    entry, began, ended = max(entries, key=lambda item: (item[2], item[0].id))
    start = began.astimezone(SETTINGS.local_timezone)
    end = ended.astimezone(SETTINGS.local_timezone)
    interval = f"{start:%H:%M}-{end:%H:%M}"
    if entry.kind == "calendar":
        title = " ".join(entry.text.removeprefix("Scheduled: ").split())[:180]
        question = f"Did you attend '{title}' ({interval})?"
    else:
        question = f"Was your {interval} walking outing a dog walk?"

    return f"For {snapshot.date:%A %d %B}: {question}", entry.id
