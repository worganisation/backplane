"""Task intake survives secondary failures and caller retries."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

import pytest

from backplane.api.routers.tasks import create_task as rest_create_task
from backplane.api.schemas import CreateTaskRequest
from backplane.mcp.tasks import create_task as mcp_create_task
from backplane.services import tasks
from backplane.services.tasks import TaskMetadata, TaskService
from backplane.utils import VAULT_PATHS, MarkdownDocument, exc
from backplane.utils.helpers.files import vault_write_lock

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from backplane.utils.async_path import AsyncPath


@pytest.fixture(autouse=True)
def task_metadata(mocker: MockerFixture) -> None:
    """Keep intake tests deterministic without calling the metadata model."""
    _ = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        new=mocker.AsyncMock(
            return_value=TaskMetadata(
                title="Review backups",
                domains=["Backups"],
                resources=[],
                projects=[],
                people=[],
            ),
        ),
    )


async def _install_board(vault: AsyncPath) -> AsyncPath:
    board = vault / VAULT_PATHS.task_board_path
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await board.write_text("## Backlog\n\n## Done\n", encoding="utf-8")
    return board


async def test__missing_board_reports_saved_task_and_retry_repairs_it(
    obsidian_vault: AsyncPath,
) -> None:
    """Missing board cannot hide the saved note, and recovery creates one card."""
    first = await TaskService.create_task("Review backups", idempotency_key="request-1")
    assert await (obsidian_vault / first.path).exists()
    assert any("board update failed" in warning for warning in first.warnings)
    assert first.domains_created == ["Backups"]
    async with MarkdownDocument(vault_path=first.path, read_only=True) as document:
        assert document.frontmatter["type"] == "task"
        assert isinstance(document.frontmatter["backplane_task_intake"], str)
    original = await (obsidian_vault / first.path).read_text() + "\nUser-added detail.\n"
    _ = await (obsidian_vault / first.path).write_text(original)
    board = await _install_board(obsidian_vault)

    second = await TaskService.create_task("Review backups", idempotency_key="request-1")
    _ = await board.write_text(
        f"## Backlog\n\n## Done\n- [x] {first.metadata.canonical_link}\n",
    )
    third = await TaskService.create_task("Review backups", idempotency_key="request-1")

    assert first.path == second.path == third.path
    assert second.replayed
    assert third.replayed
    assert not second.warnings
    assert not third.warnings
    assert second.domains_created == []
    assert await (obsidian_vault / first.path).read_text() == original
    assert (await board.read_text()).count(first.metadata.canonical_link) == 1


async def test__stub_failure_preserves_task_and_existing_card(
    obsidian_vault: AsyncPath,
) -> None:
    """A missing entity template is repairable without duplicating the task/card."""
    board = await _install_board(obsidian_vault)
    template = obsidian_vault / "Templates/Domain.md"
    original = await template.read_text()
    await template.unlink()

    first = await TaskService.create_task("Review backups", idempotency_key="request-1")
    assert await (obsidian_vault / first.path).exists()
    assert any("entity creation failed" in warning for warning in first.warnings)
    _ = await template.write_text(original)

    second = await TaskService.create_task("Review backups", idempotency_key="request-1")
    assert second.path == first.path
    assert second.domains_created == ["Backups"]
    assert not second.warnings
    assert (await board.read_text()).count(first.metadata.canonical_link) == 1


async def test__concurrent_requests_use_key_and_preserve_distinct_operations(
    obsidian_vault: AsyncPath,
) -> None:
    """Same-key races coalesce; identical unkeyed and differently keyed tasks survive."""
    board = await _install_board(obsidian_vault)
    async with asyncio.timeout(10):
        first, second = await asyncio.gather(
            TaskService.create_task("Review backups", idempotency_key="request-1"),
            TaskService.create_task("Review backups", idempotency_key="request-1"),
        )
        independent = await asyncio.gather(
            TaskService.create_task("Review backups"),
            TaskService.create_task("Review backups"),
            TaskService.create_task("Review backups", idempotency_key="request-2"),
        )

    assert first.path == second.path
    assert first.replayed != second.replayed
    assert len({first.path, *(result.path for result in independent)}) == 4
    assert (await board.read_text()).count("- [ ]") == 4
    assert all(not result.warnings for result in [first, second, *independent])


async def test__key_reuse_with_changed_input_conflicts(obsidian_vault: AsyncPath) -> None:
    """A retry key cannot silently discard changed task fields."""
    _ = await _install_board(obsidian_vault)
    _ = await TaskService.create_task("Review backups", idempotency_key="request-1")

    with pytest.raises(exc.ConflictError, match="different task input"):
        _ = await TaskService.create_task(
            "Review backups",
            due="2026-10-20",
            idempotency_key="request-1",
        )


async def test__cancelled_intake_resumes_after_note_was_saved(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Cancellation after atomic persistence leaves retry identity available."""
    _ = await _install_board(obsidian_vault)
    reached_board = asyncio.Event()

    async def pause_board(_note_path: AsyncPath) -> None:
        reached_board.set()
        await asyncio.Event().wait()

    mock_board = mocker.patch(
        "backplane.services.tasks._ensure_task_board_card",
        side_effect=pause_board,
    )
    pending = asyncio.create_task(
        TaskService.create_task("Review backups", idempotency_key="request-1"),
    )
    await asyncio.wait_for(reached_board.wait(), timeout=10)
    _ = pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        _ = await pending
    mocker.stop(mock_board)

    async with asyncio.timeout(10):
        result = await TaskService.create_task(
            "Review backups",
            idempotency_key="request-1",
        )
    assert result.replayed
    assert not result.warnings


async def test__metadata_extraction_does_not_hold_vault_lock(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """A slow model cannot block independent vault writers."""
    _ = await _install_board(obsidian_vault)
    extracting = asyncio.Event()
    release = asyncio.Event()

    async def extract(
        _description: str,
        _title: str | None,
        _priority: object,
    ) -> TaskMetadata:
        extracting.set()
        await release.wait()
        return TaskMetadata(
            title="Review backups",
            domains=[],
            resources=[],
            projects=[],
            people=[],
        )

    _ = mocker.patch("backplane.services.tasks._extract_metadata", side_effect=extract)
    pending = asyncio.create_task(
        TaskService.create_task("Review backups", idempotency_key="request-1"),
    )
    try:
        await asyncio.wait_for(extracting.wait(), timeout=10)
        async with asyncio.timeout(2), vault_write_lock():
            release.set()
    finally:
        release.set()
        _ = await pending


async def test__retry_in_new_process_uses_persisted_identity(
    obsidian_vault: AsyncPath,
) -> None:
    """Fresh server processes reuse the original note without invoking extraction."""
    first = await TaskService.create_task("Review backups", idempotency_key="request-1")
    board = await _install_board(obsidian_vault)
    script = """import asyncio
from backplane.services.tasks import TaskService
async def main():
    result = await TaskService.create_task("Review backups", idempotency_key="request-1")
    assert result.replayed and not result.warnings
    print(result.path)
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        env=dict(os.environ) | {"OBSIDIAN_VAULT_PATH": str(obsidian_vault)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    finally:
        if process.returncode is None:
            process.kill()
            _ = await process.wait()
    assert process.returncode == 0, stderr.decode()
    assert stdout.decode().strip() == str(first.path)
    assert (await board.read_text()).count(first.metadata.canonical_link) == 1


async def test__legacy_capture_backlink_is_idempotent(obsidian_vault: AsyncPath) -> None:
    """A resumed request cannot append duplicate backlinks to a legacy capture."""
    _ = await _install_board(obsidian_vault)
    inbox = obsidian_vault / tasks.ObsidianService.IDEA_INBOX_PATH
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text("# 2026-10-14\n\n## 10:00\n\nReview backups\n")

    for _ in range(2):
        result = await TaskService.create_task(
            "Review backups",
            link_capture_id="2026-10-14T10:00",
            idempotency_key="request-1",
        )
        assert not result.warnings

    assert (await inbox.read_text()).count("↗") == 1


async def test__rest_and_mcp_share_retry_identity_and_warnings(
    obsidian_vault: AsyncPath,
) -> None:
    """Both adapters project saved-task warnings and share the same caller identity."""
    first = await rest_create_task(
        CreateTaskRequest(description="Review backups", idempotency_key="request-1"),
    )
    assert first.warnings
    assert not first.replayed
    _ = await _install_board(obsidian_vault)

    second = await mcp_create_task(
        description="Review backups",
        idempotency_key="request-1",
    )
    assert second.metadata == first.metadata
    assert second.replayed
    assert not second.warnings

    third = await rest_create_task(
        CreateTaskRequest(description="Review backups", idempotency_key="request-1"),
    )
    assert third.replayed
    assert not third.warnings


async def test__unkeyed_partial_success_warns_against_creating_duplicate(
    obsidian_vault: AsyncPath,
) -> None:
    """Legacy callers see their saved task and explicit manual repair guidance."""
    result = await TaskService.create_task("Review backups")
    assert await (obsidian_vault / result.path).exists()
    assert any("do not repeat create_task" in warning for warning in result.warnings)
    assert not result.replayed
