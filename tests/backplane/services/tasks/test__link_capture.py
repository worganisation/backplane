"""Tests for linking existing tasks to inbox captures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from backplane.utils.async_path import AsyncPath

from backplane.services.obsidian import ObsidianService
from backplane.services.tasks import TaskService
from backplane.utils import VAULT_PATHS, exc, today
from backplane.utils.markdown import MarkdownDocument


async def test__link_capture_sets_task_frontmatter_and_annotates_capture(
    obsidian_vault: AsyncPath,
) -> None:
    """A confirmed capture link updates the task and capture notes."""
    capture_date = today().isoformat()
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    task_path = obsidian_vault / VAULT_PATHS.task_notes_dir / "review-backup-logs.md"
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await task_path.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        f"""# {capture_date}

## 09:15

Review backup logs
""",
        encoding="utf-8",
    )
    _ = await task_path.write_text(
        """---
type: task
source_capture:
---
# Review backup logs
""",
        encoding="utf-8",
    )

    result = await TaskService.link_capture(
        "review-backup-logs",
        f"{capture_date}T09:15",
    )

    assert result == f"Task review-backup-logs linked to capture {capture_date}T09:15."
    async with MarkdownDocument(
        vault_path=ObsidianService.IDEA_INBOX_PATH,
        read_only=True,
    ) as inbox_doc:
        capture_section = inbox_doc.get_section((capture_date, "09:15"))
        assert capture_section.content == (
            "Review backup logs\n\n↗ [[Tasks/Tasks/review-backup-logs|review-backup-logs]]"
        )

    async with MarkdownDocument(
        vault_path=VAULT_PATHS.task_notes_dir / "review-backup-logs.md",
        read_only=True,
    ) as task_doc:
        assert task_doc.frontmatter["source_capture"] == f"{capture_date}T09:15"


async def test__link_capture_unknown_capture_raises_not_found(
    obsidian_vault: AsyncPath,
) -> None:
    """An unknown capture ID raises the established not-found error."""
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    task_path = obsidian_vault / VAULT_PATHS.task_notes_dir / "review-backup-logs.md"
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await task_path.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        """# 2026-05-25

## 20:00

Rotate the hallway camera battery.
""",
        encoding="utf-8",
    )
    _ = await task_path.write_text(
        """---
type: task
source_capture:
---
# Review backup logs
""",
        encoding="utf-8",
    )

    with pytest.raises(exc.NotFoundError, match="Capture '2026-05-25T21:15' not found"):
        _ = await TaskService.link_capture(
            "review-backup-logs",
            "2026-05-25T21:15",
        )


async def test__link_capture_unknown_task_raises_not_found(
    obsidian_vault: AsyncPath,
) -> None:
    """An unknown task slug raises the established not-found error."""
    capture_date = today().isoformat()
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        f"""# {capture_date}

## 09:15

Review backup logs
""",
        encoding="utf-8",
    )

    with pytest.raises(exc.NotFoundError, match="Task 'missing-task' not found"):
        _ = await TaskService.link_capture(
            "missing-task",
            f"{capture_date}T09:15",
        )
