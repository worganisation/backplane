"""Typed diary observations and explicit user confirmations."""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field


class DiaryEntry(BaseModel, frozen=True):
    """One source observation; identifiers remain stable across retries."""

    id: str
    aliases: list[str] = Field(default_factory=list)
    source: str
    kind: Literal["calendar", "visit", "outing", "mood", "habit", "weight"]
    text: str
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    needs_confirmation: bool = False


class DiarySnapshot(BaseModel, frozen=True):
    """Complete source projection for one London diary day."""

    date: dt.date
    collected_at: AwareDatetime
    entries: list[DiaryEntry] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)

    def fingerprint(self) -> str:
        """Return a content fingerprint independent of polling time."""
        return hashlib.sha256(
            self.model_dump_json(exclude={"collected_at"}).encode(),
        ).hexdigest()


class DiaryDecision(BaseModel, frozen=True):
    """An explicit response to one exact item from the daily review."""

    entry_id: str
    outcome: Literal["confirmed", "dog_walk", "dismissed"]


class DiaryReviewResponse(BaseModel, frozen=True):
    """User-confirmed decisions and verbatim additional diary detail."""

    request_id: Annotated[str, Field(min_length=1, max_length=200)]
    decisions: Annotated[list[DiaryDecision], Field(max_length=100)] = Field(
        default_factory=list,
    )
    note: Annotated[str, Field(max_length=10000)] = ""


class DiarySyncRequest(BaseModel, frozen=True):
    """One bounded daily reconciliation request from HA."""

    date: dt.date
    narrative: bool = False


class DiarySyncResult(BaseModel, frozen=True):
    """Persistence and export result; missing source data stays explicit."""

    date: dt.date
    entries: int
    missing: list[str]
    narrative_ready: bool


def entry_id(source: str, key: str) -> str:
    """Return an opaque ID for a source record or completed interval."""
    return hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:24]


def retain_entry_aliases(
    snapshot: DiarySnapshot,
    previous: DiarySnapshot,
) -> DiarySnapshot:
    """Carry exact legacy review identities across revisions of the same source record.

    Returns:
        A snapshot retaining aliases only where identity matches unambiguously.
    """
    entries: list[DiaryEntry] = []
    for entry in snapshot.entries:
        matches = [
            old for old in previous.entries if old.id in {entry.id, *entry.aliases}
        ]
        aliases: list[str] = []
        if len(matches) == 1:
            aliases = sorted({*matches[0].aliases, matches[0].id} - {entry.id})
        entries.append(entry.model_copy(update={"aliases": aliases}))

    return snapshot.model_copy(update={"entries": entries})
