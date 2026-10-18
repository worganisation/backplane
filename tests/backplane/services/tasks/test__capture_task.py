"""Fast captures persist tasks without model calls and remain safe to retry."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from backplane.mcp.tasks import capture_task
from backplane.services.tasks import TaskMetadata, TaskService
from backplane.utils import VAULT_PATHS, enums, exc

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from backplane.utils import AsyncPath


async def test__capture_task__persists_once_without_inference(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Concurrent retries preserve content and explicit fields with one board card."""
    extraction = mocker.patch("backplane.services.tasks._extract_metadata")
    matching = mocker.patch("backplane.services.tasks._select_task_capture")
    description = (
        "Check the rain sensor battery tomorrow, including the spare in the garage."
    )
    board_path = obsidian_vault / VAULT_PATHS.task_board_path
    await board_path.parent.mkdir(parents=True, exist_ok=True)
    _ = await board_path.write_text("## Backlog\n\n")

    first, second = await asyncio.gather(
        *(
            capture_task(
                description=description,
                title="Check rain sensor",
                due="2026-10-18",
                priority=enums.Priority.HIGH,
                idempotency_key="voice-1",
            )
            for _ in range(2)
        ),
    )

    extraction.assert_not_called()
    matching.assert_not_called()
    assert first.metadata.path == second.metadata.path
    assert first.replayed != second.replayed
    note = await (obsidian_vault / first.metadata.path).read_text()
    assert description in note
    assert "2026-10-18" in note
    assert "priority: high" in note
    board = await (obsidian_vault / VAULT_PATHS.task_board_path).read_text()
    assert board.count(first.metadata.canonical_link) == 1

    with pytest.raises(exc.ConflictError):
        _ = await capture_task(description="Different task", idempotency_key="voice-1")

    with pytest.raises(exc.ConflictError):
        _ = await TaskService.create_task(
            description,
            title="Check rain sensor",
            due="2026-10-18",
            priority=enums.Priority.HIGH,
            idempotency_key="voice-1",
        )


async def test__capture_task__reports_saved_note_when_board_fails(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """A secondary failure returns a saved task and can be repaired by retry."""
    board_update = mocker.patch(
        "backplane.services.tasks._ensure_task_board_card",
        side_effect=OSError("Board unavailable"),
    )
    saved = await capture_task(description="Check battery", idempotency_key="voice-2")
    assert await (obsidian_vault / saved.metadata.path).exists()
    assert len(saved.warnings) == 1

    board_update.side_effect = None
    retried = await capture_task(description="Check battery", idempotency_key="voice-2")
    assert retried.replayed
    assert retried.metadata.path == saved.metadata.path
    assert not retried.warnings


@pytest.mark.parametrize(
    ("description", "title", "link_capture_id"),
    [
        ("  ", None, None),
        ("Check battery", "  ", None),
        ("Check battery", None, "idea-1"),
    ],
)
async def test__capture_task__rejects_invalid_input_before_writing(
    obsidian_vault: AsyncPath,
    description: str,
    title: str | None,
    link_capture_id: str | None,
) -> None:
    """Blank tasks and unsupported capture linking never create a task note."""
    with pytest.raises(exc.BadRequestError):
        _ = await TaskService.create_task(
            description,
            title=title,
            link_capture_id=link_capture_id,
            enrich_metadata=False,
        )

    assert not await (obsidian_vault / VAULT_PATHS.task_notes_dir).exists()


async def test__explicit_project_uses_existing_note_and_retries_preserve_assignment(
    obsidian_vault: AsyncPath,
) -> None:
    """A case-insensitive project name links to its real filename without inference."""
    path = obsidian_vault / VAULT_PATHS.projects_dir / "solar-plan.md"
    await path.parent.mkdir(parents=True, exist_ok=True)
    await path.write_text("# Solar Plan\n\n## Related Tasks\n")
    first = await capture_task(
        "Check roof",
        project="solar plan",
        idempotency_key="roof-1",
    )
    second = await capture_task(
        "Check roof",
        project="solar plan",
        idempotency_key="roof-1",
    )
    assert first.metadata.path == second.metadata.path
    assert (
        "[[Projects/solar-plan|Solar Plan]]"
        in await (obsidian_vault / first.metadata.path).read_text()
    )
    with pytest.raises(exc.ConflictError):
        await capture_task(
            "Check roof",
            project="Another Project",
            idempotency_key="roof-1",
        )


async def test__explicit_new_project_creates_stub_and_blank_project_is_rejected(
    obsidian_vault: AsyncPath,
) -> None:
    """A named new project gets a stub; accidental blank assignment never saves a task."""
    await capture_task("Check roof", project="Solar Plan", idempotency_key="roof-2")
    assert await (obsidian_vault / VAULT_PATHS.projects_dir / "Solar Plan.md").exists()
    with pytest.raises(exc.BadRequestError):
        await capture_task("Check roof", project=" ")


async def test__explicit_project_overrides_model_assignment(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Enrichment cannot replace the user's explicitly selected project."""
    _ = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        return_value=TaskMetadata(
            title="Check roof",
            projects=["Wrong project"],
            domains=[],
            resources=[],
            people=[],
        ),
    )
    saved = await TaskService.create_task(
        "Check roof",
        project="Solar Plan",
        idempotency_key="roof-3",
    )
    note = await (obsidian_vault / saved.metadata.path).read_text()
    assert "[[Projects/Solar Plan|Solar Plan]]" in note
    assert "Wrong project" not in note
