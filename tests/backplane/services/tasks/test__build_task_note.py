"""Tests for rendering task notes."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import datetime as dt

from backplane.services.tasks import (
    Capture,
    TaskFrontmatter,
    TaskMetadata,
    _build_task_note,
)
from backplane.utils import VAULT_PATHS, enums


def test__build_task_note_serializes_enum_frontmatter_as_strings() -> None:
    """Verify that enum frontmatter fields and wiki link references render correctly in task notes."""
    capture = Capture(
        id="2026-05-25T21:15",
        date="2026-05-25",
        time="21:15",
        text="Review backup logs",
        path=VAULT_PATHS.inbox_dir / "Ideas.md",
    )
    metadata = TaskMetadata(
        title="Review backup logs",
        domains=["Infrastructure"],
        resources=["Backups"],
        projects=["Backup Hardening"],
        people=[],
        priority=enums.Priority.HIGH,
        effort=enums.Effort.SMALL,
        next_action="Open the latest backup report.",
    )

    note = _build_task_note(
        title=metadata.title,
        now=dt.datetime(2026, 5, 25, 21, 30, tzinfo=dt.UTC),
        metadata=metadata,
        capture=capture,
        description="backup logs",
        due="2026-05-29",
    )

    assert "priority: high\n" in note
    assert "effort: small\n" in note
    assert "- '[[Domains/Infrastructure|Infrastructure]]'\n" in note
    assert "- '[[Resources/Backups|Backups]]'\n" in note
    assert "- '[[Projects/Backup Hardening|Backup Hardening]]'\n" in note
    assert "source_capture: 2026-05-25T21:15\n" in note
    assert "## Description\n\n> backup logs\n\n" in note
    assert (
        "## Source Capture\n\n[[Inbox/Ideas|Ideas]] (2026-05-25T21:15)\n\n"
        "> Review backup logs\n"
    ) in note


def test__task_frontmatter_defaults_fixed_task_fields() -> None:
    """Task frontmatter defaults the stable task note fields."""
    frontmatter = TaskFrontmatter(
        id="task-20260525-213000",
        created="2026-05-25T21:30:00",
        updated="2026-05-25T21:30:00",
        source_capture=None,
        domains=[],
        resources=[],
        projects=[],
        people=[],
        priority=enums.Priority.MEDIUM,
        effort=enums.Effort.SMALL,
        due=None,
    )

    assert frontmatter.model_dump(mode="python") == {
        "id": "task-20260525-213000",
        "type": "task",
        "status": "backlog",
        "created": "2026-05-25T21:30:00",
        "updated": "2026-05-25T21:30:00",
        "source_capture": None,
        "source_capture_link": None,
        "domains": [],
        "resources": [],
        "projects": [],
        "people": [],
        "priority": enums.Priority.MEDIUM,
        "effort": enums.Effort.SMALL,
        "due": None,
        "completed": None,
        "tags": ["task"],
    }
    assert "id: task-20260525-213000\n" in frontmatter.model_dump_yaml()


def test__task_ids_are_unique_with_identical_creation_times() -> None:
    """Distinct tasks created within one timestamp receive independent UUID identities."""
    notes = [
        _build_task_note(
            title="Check roof",
            now=dt.datetime(2026, 10, 18, tzinfo=dt.UTC),
            metadata=TaskMetadata(
                title="Check roof",
                domains=[],
                resources=[],
                projects=[],
                people=[],
            ),
            capture=None,
            description="Check roof",
            due=None,
        )
        for _ in range(2)
    ]
    identifiers = [
        next(line for line in note.splitlines() if line.startswith("id:"))
        for note in notes
    ]
    assert identifiers[0] != identifiers[1]
