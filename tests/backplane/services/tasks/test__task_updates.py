"""Explicit lifecycle updates preserve task wording and recover secondary writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backplane.api.routers.tasks import update_task as update_task_route
from backplane.services.task_catalog import list_tasks
from backplane.services.task_updates import TaskUpdate, update_task
from backplane.services.tasks import TaskService
from backplane.utils import VAULT_PATHS, exc

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from backplane.utils import AsyncPath


async def test__status_updates_move_one_card_and_preserve_body(
    obsidian_vault: AsyncPath,
) -> None:
    """Repeated updates are stable, completion is reversible and unrelated cards survive."""
    result = await TaskService.create_task("Original text", enrich_metadata=False)
    task = (await list_tasks())[0]
    board_path = obsidian_vault / VAULT_PATHS.task_board_path
    await board_path.parent.mkdir(parents=True, exist_ok=True)
    await board_path.write_text(
        f"## Backlog\n\n- [ ] {result.metadata.canonical_link} @{{2026-10-20}}\n"
        "- [ ] [[Tasks/Other]]\n\n%% kanban:settings\n{}\n%%\n",
    )
    first = await update_task(task.id, TaskUpdate(status="doing"))
    assert not first.warnings
    board = await board_path.read_text()
    second = await update_task(task.id, TaskUpdate(status="doing"))
    assert await board_path.read_text() == board
    assert second.task.body == task.body
    assert board.count(result.metadata.canonical_link) == 1
    assert "@{2026-10-20}" in board
    assert "[[Tasks/Other]]" in board
    assert board.index("## Doing") < board.index("%% kanban:settings")

    completed = await update_task(task.id, TaskUpdate(status="done"))
    assert completed.task.status == "done"
    assert f"- [x] {result.metadata.canonical_link}" in await board_path.read_text()
    await update_task(task.id, TaskUpdate(status="backlog"))
    assert f"- [ ] {result.metadata.canonical_link}" in await board_path.read_text()
    assert "completed:\n" in await (obsidian_vault / task.path).read_text()


async def test__project_assignment_and_removal_preserve_original_text(
    obsidian_vault: AsyncPath,
) -> None:
    """Explicit reassignment uses real project paths and unassignment clears only links."""
    await TaskService.create_task("Task text", project="Old", enrich_metadata=False)
    task = (await list_tasks())[0]
    project = obsidian_vault / VAULT_PATHS.projects_dir / "new-project.md"
    await project.write_text("# New Project\n")
    updated = await update_task(task.id, TaskUpdate(project="New Project"))
    assert updated.task.projects == ["[[Projects/new-project|New Project]]"]
    assert updated.task.body == task.body
    cleared = await update_task(task.id, TaskUpdate(clear_project=True))
    assert cleared.task.projects == []
    with pytest.raises(exc.BadRequestError):
        await update_task(task.id, TaskUpdate(clear_project=True, project="New Project"))
    with pytest.raises(exc.BadRequestError):
        await update_task(task.id, TaskUpdate(project=" "))
    with pytest.raises(exc.NotFoundError):
        await update_task(task.id, TaskUpdate(project="Missing"))


async def test__board_failure_can_be_repaired_without_changing_completed_time(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """A saved task remains authoritative when its board write fails."""
    result = await TaskService.create_task("Task", enrich_metadata=False)
    task = (await list_tasks())[0]
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await board.parent.mkdir(parents=True, exist_ok=True)
    await board.write_text("## Done\n")
    failure = mocker.patch(
        "backplane.services.task_updates.reconcile_task_board",
        side_effect=OSError("unavailable"),
    )
    first = await update_task(task.id, TaskUpdate(status="done"))
    assert first.task.status == "done"
    assert first.warnings
    text = await (obsidian_vault / task.path).read_text()
    mocker.stop(failure)
    repaired = await update_task(task.id, TaskUpdate(status="done"))
    assert not repaired.warnings
    assert await (obsidian_vault / task.path).read_text() == text
    assert result.metadata.canonical_link in await board.read_text()


async def test__duplicate_cards_and_crlf_body_are_preserved_safely(
    obsidian_vault: AsyncPath,
) -> None:
    """Reconciliation removes duplicate cards, while note body line endings remain exact."""
    result = await TaskService.create_task("Task", enrich_metadata=False)
    task = (await list_tasks())[0]
    path = obsidian_vault / task.path
    raw = await path.read_text()
    raw = raw.replace("\n", "\r\n")
    await path.write_bytes(raw.encode())
    task = (await list_tasks())[0]
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await board.parent.mkdir(parents=True, exist_ok=True)
    await board.write_text(
        f"## Backlog\n- [ ] {result.metadata.canonical_link}\n"
        f"## Doing\n- [ ] {result.metadata.canonical_link}\n",
    )
    updated = await update_task(task.id, TaskUpdate(status="doing"))
    assert updated.task.body == task.body
    assert (await board.read_text()).count(result.metadata.canonical_link) == 1


async def test__rest_update_reports_saved_state(obsidian_vault: AsyncPath) -> None:
    """The adapter returns persisted completion even when the optional board is absent."""
    await TaskService.create_task("Task", enrich_metadata=False)
    task = (await list_tasks())[0]
    updated = await update_task_route(task.id, TaskUpdate(status="done"))
    assert updated.task.completed is not None
    assert updated.warnings
    assert await (obsidian_vault / updated.task.path).exists()


async def test__capture_replay_repairs_card_using_current_task_status(
    obsidian_vault: AsyncPath,
) -> None:
    """Replaying an old capture cannot put a completed task back in Backlog."""
    created = await TaskService.create_task(
        "Task",
        idempotency_key="capture",
        enrich_metadata=False,
    )
    task = (await list_tasks())[0]
    completed = await update_task(task.id, TaskUpdate(status="done"))
    assert completed.warnings
    before = await (obsidian_vault / task.path).read_text()
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await board.parent.mkdir(parents=True, exist_ok=True)
    await board.write_text("## Backlog\n\n## Done\n")
    replay = await TaskService.create_task(
        "Task",
        idempotency_key="capture",
        enrich_metadata=False,
    )
    assert replay.replayed
    assert not replay.warnings
    text = await board.read_text()
    assert text.index(created.metadata.canonical_link) > text.index("## Done")
    assert f"- [x] {created.metadata.canonical_link}" in text
    assert await (obsidian_vault / task.path).read_text() == before


async def test__native_yaml_timestamps_survive_lifecycle_updates(
    obsidian_vault: AsyncPath,
) -> None:
    """Valid Obsidian-authored date and timestamp fields remain readable on update."""
    path = obsidian_vault / VAULT_PATHS.task_notes_dir / "Native.md"
    await path.parent.mkdir(parents=True)
    await path.write_text(
        "---\nid: task-native\ntype: task\nstatus: done\ndue: 2026-10-20\n"
        "completed: 2026-10-18T12:30:00+01:00\nupdated: 2026-10-18T12:30:00+01:00\n"
        "---\n# Native\n",
    )
    result = await update_task("task-native", TaskUpdate(status="backlog"))
    assert result.task.due == "2026-10-20"
    assert result.task.completed is None
