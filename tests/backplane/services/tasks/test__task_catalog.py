"""Task browsing retains identity across note edits and rejects ambiguous IDs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backplane.api.routers.tasks import get_task as get_task_route
from backplane.api.routers.tasks import list_tasks as list_tasks_route
from backplane.services.task_catalog import get_task, list_tasks
from backplane.services.tasks import TaskService
from backplane.utils import VAULT_PATHS, exc

if TYPE_CHECKING:
    from backplane.utils import AsyncPath


async def test__browse_filters_and_reads_renamed_task(obsidian_vault: AsyncPath) -> None:
    """Filters distinguish assigned tasks and identity survives a filename change."""
    first = await TaskService.create_task(
        "Keep exact original wording.",
        title="Roof",
        project="Solar",
        enrich_metadata=False,
    )
    await TaskService.create_task("Other task", title="Boiler", enrich_metadata=False)
    tasks = await list_tasks(project="solar", status="backlog")
    assert len(tasks) == 1
    assert tasks[0].path == first.path
    assert "Keep exact original wording." in tasks[0].body
    assert [task.title for task in await list_tasks(project="")] == ["Boiler"]
    assert [task.title for task in await list_tasks(limit=1, offset=1)] == ["Roof"]
    assert not await list_tasks(status="done")

    renamed = obsidian_vault / VAULT_PATHS.task_notes_dir / "Renamed.md"
    await (obsidian_vault / first.path).rename(renamed)
    found = await get_task(tasks[0].id)
    assert found.path.name == "Renamed.md"
    assert found.body == tasks[0].body
    with pytest.raises(exc.NotFoundError):
        await get_task("Roof")


async def test__catalog_rejects_duplicate_identity(obsidian_vault: AsyncPath) -> None:
    """Duplicate task IDs cannot silently select whichever file was scanned first."""
    result = await TaskService.create_task("A task", enrich_metadata=False)
    text = await (obsidian_vault / result.path).read_text()
    await (obsidian_vault / VAULT_PATHS.task_notes_dir / "Duplicate.md").write_text(text)
    with pytest.raises(exc.ConflictError, match="Duplicate task identity"):
        await list_tasks()


async def test__empty_catalog_and_invalid_limits(obsidian_vault: AsyncPath) -> None:
    """An empty vault is valid; unreasonable pagination is rejected."""
    assert await list_tasks() == []
    assert await obsidian_vault.exists()
    for limit, offset in [(0, 0), (101, 0), (20, -1)]:
        with pytest.raises(exc.BadRequestError):
            await list_tasks(limit=limit, offset=offset)


async def test__catalog_ignores_other_notes_and_reports_invalid_tasks(
    obsidian_vault: AsyncPath,
) -> None:
    """Non-task notes are harmless but broken task metadata must be repaired."""
    directory = obsidian_vault / VAULT_PATHS.task_notes_dir
    await directory.mkdir(parents=True)
    await (directory / "Plain.md").write_text("# Plain note\n")
    await (directory / "Project.md").write_text("---\ntype: project\n---\n# Project\n")
    assert not await list_tasks()
    await (directory / "Broken.md").write_text("---\ntype: task\n---\n# Missing ID\n")
    with pytest.raises(exc.UserError, match="Invalid task metadata"):
        await list_tasks()


async def test__rest_browsing_uses_same_identity_and_filters(
    obsidian_vault: AsyncPath,
) -> None:
    """REST projections retain the domain task identity and pagination."""
    await TaskService.create_task("Water garden", enrich_metadata=False)
    tasks = await list_tasks_route(project="", task_status="backlog", limit=1, offset=0)
    assert len(tasks) == 1
    assert await get_task_route(tasks[0].id) == tasks[0]
    assert await (obsidian_vault / tasks[0].path).exists()


@pytest.mark.parametrize("header", ["- not a mapping", "a scalar", "type: [invalid"])
async def test__invalid_yaml_is_reported_as_a_domain_error(
    obsidian_vault: AsyncPath,
    header: str,
) -> None:
    """Broken frontmatter cannot leak an attribute/parser error from task discovery."""
    path = obsidian_vault / VAULT_PATHS.task_notes_dir / "Broken.md"
    await path.parent.mkdir(parents=True)
    await path.write_text(f"---\n{header}\n---\n# Task\n")
    with pytest.raises(exc.UserError, match="Invalid task metadata"):
        await list_tasks()


async def test__yaml_native_date_is_valid_task_metadata(
    obsidian_vault: AsyncPath,
) -> None:
    """Obsidian-authored unquoted dates remain readable without rewriting the note."""
    path = obsidian_vault / VAULT_PATHS.task_notes_dir / "Dated.md"
    await path.parent.mkdir(parents=True)
    text = "---\nid: task-dated\ntype: task\ndue: 2026-10-20\n---\n# Dated\n"
    await path.write_text(text)
    assert (await get_task("task-dated")).due == "2026-10-20"
    assert await path.read_text() == text
