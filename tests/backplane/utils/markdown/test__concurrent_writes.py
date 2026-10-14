"""Regression coverage for cooperating vault writers and lock lifetime."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import TYPE_CHECKING

import pytest

from backplane.utils import kanban
from backplane.utils.async_path import AsyncPath
from backplane.utils.helpers.files import vault_write_lock
from backplane.utils.kanban import append_board_card
from backplane.utils.markdown import MarkdownDocument
from backplane.utils.settings import SETTINGS

if TYPE_CHECKING:
    from pathlib import Path


async def _append_capture(label: str) -> None:
    async with MarkdownDocument(
        vault_path=AsyncPath("Daily/captures.md"),
        create_if_not_exists=True,
        initial_content="## Ideas\n",
    ) as document:
        document.get_section(("Ideas",)).append_content(label)
        await asyncio.sleep(0.01)


async def test_concurrent_capture_creation_preserves_every_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent first writes also create a missing vault and note directory."""
    root = AsyncPath(tmp_path / "new-vault")
    monkeypatch.setattr(SETTINGS, "obsidian_vault_path", root)

    async with asyncio.timeout(5):
        _ = await asyncio.gather(*(_append_capture(f"capture-{i}") for i in range(4)))

    text = await (root / "Daily/captures.md").read_text()
    assert all(text.count(f"capture-{i}") == 1 for i in range(4))


async def test_concurrent_board_cards_preserve_every_card(
    obsidian_vault: AsyncPath,
) -> None:
    """Board read/modify/write operations serialize alongside document edits."""
    board = obsidian_vault / "board.md"
    _ = await board.write_text("## Backlog\n\n## Done\n")

    async with asyncio.timeout(5):
        _ = await asyncio.gather(
            *(
                append_board_card(board, AsyncPath(f"Tasks/task-{i}.md"))
                for i in range(4)
            ),
        )

    text = await board.read_text()
    assert all(text.count(f"[[Tasks/task-{i}|task-{i}]]") == 1 for i in range(4))


async def test_nested_writes_and_cancelled_child_waiter(
    obsidian_vault: AsyncPath,
) -> None:
    """A child cannot inherit ownership, and cancelling a waiter leaves no orphan lock."""
    started = asyncio.Event()
    acquired = asyncio.Event()

    async def wait_for_lock() -> None:
        started.set()
        async with vault_write_lock():
            acquired.set()

    async with asyncio.timeout(5):
        async with vault_write_lock():
            await _append_capture("nested")
            child = asyncio.create_task(wait_for_lock())
            await started.wait()
            await asyncio.sleep(0.03)
            assert not acquired.is_set()
            _ = child.cancel()
            with pytest.raises(asyncio.CancelledError):
                await child

        await _append_capture("after-cancellation")

    assert (
        "after-cancellation" in await (obsidian_vault / "Daily/captures.md").read_text()
    )


@pytest.mark.parametrize("failure", ["load", "edit", "save", "cancel"])
async def test_document_releases_lock_on_failure(
    obsidian_vault: AsyncPath,
    failure: str,
) -> None:
    """Load errors, user errors, external changes and cancellation all release the lock."""
    path = obsidian_vault / "note.md"
    if failure != "load":
        _ = await path.write_text("## Ideas\n\noriginal\n")

    async def failed_edit() -> None:
        async with MarkdownDocument(vault_path=AsyncPath("note.md")) as document:
            document.get_section(("Ideas",)).append_content("discarded")
            if failure == "edit":
                msg = "edit failed"
                raise RuntimeError(msg)
            if failure == "cancel":
                raise asyncio.CancelledError
            if failure == "save":
                _ = await path.write_text("## Ideas\n\nexternal edit\n")

    expected = {
        "load": FileNotFoundError,
        "edit": RuntimeError,
        "save": ValueError,
        "cancel": asyncio.CancelledError,
    }[failure]
    with pytest.raises(expected):
        await failed_edit()

    async with asyncio.timeout(5):
        await _append_capture("successful")

    if failure != "load":
        text = await path.read_text()
        assert "discarded" not in text
        assert ("external edit" if failure == "save" else "original") in text


async def test_separate_processes_serialize_first_capture_writes(
    obsidian_vault: AsyncPath,
) -> None:
    """Separate private/public-style processes retain both first-note captures."""
    script = """
import asyncio
import pathlib
import sys
from backplane.utils.async_path import AsyncPath
from backplane.utils.markdown import MarkdownDocument
from backplane.utils.settings import SETTINGS

async def main():
    SETTINGS.obsidian_vault_path = AsyncPath(sys.argv[1])
    print("ready", flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    async with MarkdownDocument(
        vault_path=AsyncPath("Daily/processes.md"),
        create_if_not_exists=True,
        initial_content="## Ideas\\n",
    ) as document:
        document.get_section(("Ideas",)).append_content(sys.argv[2])
        await asyncio.sleep(0.1)

asyncio.run(main())
"""
    processes: list[asyncio.subprocess.Process] = []
    try:
        async with asyncio.timeout(15):
            for label in ("process-one", "process-two"):
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    script,
                    str(obsidian_vault),
                    label,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                processes.append(process)
                assert process.stdout is not None
                assert await process.stdout.readline() == b"ready\n"

            results = await asyncio.gather(
                *(process.communicate(b"go\n") for process in processes),
            )
            assert all(process.returncode == 0 for process in processes), results
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
                _ = await process.wait()

    text = await (obsidian_vault / "Daily/processes.md").read_text()
    assert text.count("process-one") == 1
    assert text.count("process-two") == 1


async def test_board_rejects_external_edit_and_releases_lock(
    obsidian_vault: AsyncPath,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nonparticipating writer's detected change is preserved without leaking the lock."""
    board = obsidian_vault / "board.md"
    original = "## Backlog\n\noriginal\n"
    external = "## Backlog\n\nexternal edit\n"
    _ = await board.write_text(original)
    add_card = kanban.add_card_to_list

    def replace_during_edit(
        text: str,
        note_path: AsyncPath,
        section: str,
        *,
        due: object = None,
    ) -> str:
        assert due is None
        _ = pathlib.Path(str(board)).write_text(external, encoding="utf-8")
        return add_card(text, note_path, section)

    with monkeypatch.context() as patch:
        patch.setattr(kanban, "add_card_to_list", replace_during_edit)
        with pytest.raises(ValueError, match="modified externally"):
            await append_board_card(board, AsyncPath("Tasks/discarded.md"))

    assert await board.read_text() == external
    async with asyncio.timeout(5):
        await append_board_card(board, AsyncPath("Tasks/successful.md"))
