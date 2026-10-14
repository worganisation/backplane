"""Tests for task creation capture linking behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backplane.services.obsidian import ObsidianService
from backplane.services.tasks import (
    CaptureCandidate,
    TaskMetadata,
    TaskService,
)
from backplane.utils import VAULT_PATHS, enums, today

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from backplane.utils.async_path import AsyncPath


async def test__create_task_uses_explicit_capture_link(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """An explicit capture ID links the task without fuzzy matching."""
    capture_date = today().isoformat()
    capture_text = "Review backup logs before the maintenance window."
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await board.write_text("## Backlog\n\n", encoding="utf-8")
    _ = await inbox.write_text(
        f"""# {capture_date}

## 09:15

{capture_text}
""",
        encoding="utf-8",
    )
    metadata = TaskMetadata(
        title="Review backup logs",
        domains=[],
        resources=[],
        projects=[],
        people=[],
        priority=enums.Priority.MEDIUM,
        effort=enums.Effort.MEDIUM,
        next_action="Open the backup dashboard.",
    )
    mock_extract = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        new=mocker.AsyncMock(return_value=metadata),
    )
    mock_find_match = mocker.patch("backplane.services.tasks._find_match")

    result = await TaskService.create_task(
        "backup logs",
        link_capture_id=f"{capture_date}T09:15",
    )

    assert result.matched_capture_id == f"{capture_date}T09:15"
    assert result.candidate_captures == []
    _ = mock_extract.assert_awaited_once_with(
        "Current task request (authoritative):\nbackup logs\n\n"
        "Linked inbox capture (background context; the current request takes "
        f"precedence if details differ):\n{capture_text}",
        None,
        None,
    )
    mock_find_match.assert_not_called()


async def test__create_task_unknown_explicit_capture_link_creates_unlinked_task(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """An unknown explicit capture ID does not block task creation."""
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        """# 2026-05-25

## 20:00

Rotate the hallway camera battery.
""",
        encoding="utf-8",
    )
    _ = await board.write_text("## Backlog\n\n", encoding="utf-8")
    metadata = TaskMetadata(
        title="Review backup logs",
        domains=[],
        resources=[],
        projects=[],
        people=[],
        priority=enums.Priority.MEDIUM,
        effort=enums.Effort.MEDIUM,
        next_action="Open the backup dashboard.",
    )
    _ = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        new=mocker.AsyncMock(return_value=metadata),
    )

    result = await TaskService.create_task(
        "Review backup logs",
        link_capture_id="2026-05-25T21:15",
    )

    assert result.matched_capture_id is None
    assert result.candidate_captures == []


async def test__create_task_returns_candidates_without_blocking(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Borderline capture matches are returned while the task is still created."""
    capture_date = today().isoformat()
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await board.write_text("## Backlog\n\n", encoding="utf-8")
    _ = await inbox.write_text(
        f"""# {capture_date}

## 09:15

I need to create reminder notifications for the mood tracker

## 10:00

Track LLM usage and cost in Home Assistant.
""",
        encoding="utf-8",
    )
    metadata = TaskMetadata(
        title="Update rain alert notification",
        domains=["Home Assistant"],
        resources=[],
        projects=[],
        people=[],
        priority=enums.Priority.MEDIUM,
        effort=enums.Effort.MEDIUM,
        next_action="Inspect the current rain alert automation.",
    )
    _ = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        new=mocker.AsyncMock(return_value=metadata),
    )
    _ = mocker.patch(
        "backplane.services.tasks._fuzzy_score",
        side_effect=[60.0, 60.0],
    )

    result = await TaskService.create_task("Update rain alert notification")

    assert result.matched_capture_id is None
    assert result.candidate_captures == [
        CaptureCandidate(
            id=f"{capture_date}T09:15",
            text="I need to create reminder notifications for the mood tracker",
        ),
        CaptureCandidate(
            id=f"{capture_date}T10:00",
            text="Track LLM usage and cost in Home Assistant.",
        ),
    ]
