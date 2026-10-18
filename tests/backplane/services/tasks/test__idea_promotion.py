"""Exact idea promotion persists provenance before secondary writes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from backplane.api.routers.tasks import capture_task as capture_task_route
from backplane.api.schemas import CreateTaskRequest
from backplane.mcp.tasks import capture_task
from backplane.services.ideas import IdeaService
from backplane.services.task_catalog import list_tasks
from backplane.utils import VAULT_PATHS, exc

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from backplane.utils import AsyncPath


async def test__promotion_is_exact_concurrent_and_without_inference(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Concurrent retry records one task with its source and leaves the idea unchanged."""
    idea = await IdeaService.record(
        "Maybe automate plant watering", idempotency_key="plant-idea",
    )
    original = await (obsidian_vault / idea.path).read_text()
    extraction = mocker.patch("backplane.services.tasks._extract_metadata")
    matching = mocker.patch("backplane.services.tasks._select_task_capture")
    first, second = await asyncio.gather(
        *(
            capture_task(
                "Research watering options",
                link_capture_id=idea.id,
                idempotency_key="plant-task",
            )
            for _ in range(2)
        ),
    )
    extraction.assert_not_called()
    matching.assert_not_called()
    assert first.metadata.path == second.metadata.path
    task = (await list_tasks())[0]
    assert task.source_capture == idea.id
    assert "Maybe automate plant watering" in task.body
    assert await (obsidian_vault / idea.path).read_text() == original
    with pytest.raises(exc.ConflictError):
        await capture_task("Research watering options", idempotency_key="plant-task")


async def test__promotion_rejects_unknown_source_before_any_task_write(
    obsidian_vault: AsyncPath,
) -> None:
    """A misspelled idea ID cannot silently create an unlinked task."""
    with pytest.raises(exc.NotFoundError):
        await capture_task(
            "Do this", link_capture_id="idea-missing", idempotency_key="missing",
        )
    assert not await (obsidian_vault / VAULT_PATHS.task_notes_dir).exists()


async def test__promotion_repairs_backlink_after_task_save(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Retried API promotion repairs secondary writes using the pinned source."""
    idea = await IdeaService.record("Maybe solar", idempotency_key="solar")
    failure = mocker.patch(
        "backplane.services.tasks._annotate_capture", side_effect=OSError("link failed"),
    )
    request = CreateTaskRequest(
        description="Research solar",
        link_capture_id=idea.id,
        idempotency_key="solar-task",
    )
    first = await capture_task_route(request)
    assert first.matched_capture_id == idea.id
    assert any("capture backlink failed" in warning for warning in first.warnings)
    task = (await list_tasks())[0]
    assert task.source_capture == idea.id
    mocker.stop(failure)
    second = await capture_task_route(request)
    assert second.replayed
    assert second.metadata.path == first.metadata.path
    assert await (obsidian_vault / second.metadata.path).exists()
    assert not any("capture backlink failed" in warning for warning in second.warnings)
