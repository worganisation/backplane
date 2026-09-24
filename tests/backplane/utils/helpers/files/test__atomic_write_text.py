"""Tests for atomic text file writes."""

from __future__ import annotations

import errno
from typing import TYPE_CHECKING

import pytest

from backplane.utils.async_path import AsyncPath
from backplane.utils.helpers.files import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


async def test__atomic_write_text_writes_content(tmp_path: Path) -> None:
    """Destination file receives the full written content."""
    target = AsyncPath(tmp_path) / "Tasks" / "note.md"
    await atomic_write_text(target, "hello\n")
    assert await target.read_text(encoding="utf-8") == "hello\n"


async def test__atomic_write_text_leaves_no_tmp_in_destination_dir(
    tmp_path: Path,
) -> None:
    """No temporary siblings remain after the write."""
    parent = AsyncPath(tmp_path) / "Tasks"
    target = parent / "note.md"
    await atomic_write_text(target, "hello\n")
    names = [entry.name async for entry in parent.iterdir()]
    assert names == ["note.md"]


async def test__atomic_write_text_overwrites_existing_file(tmp_path: Path) -> None:
    """An existing destination file is replaced atomically."""
    target = AsyncPath(tmp_path) / "note.md"
    _ = await target.write_text("old\n", encoding="utf-8")
    await atomic_write_text(target, "new\n")
    assert await target.read_text(encoding="utf-8") == "new\n"


async def test__atomic_write_text_supports_separate_temp_filesystem(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """A simulated mount boundary rejects non-sibling temporary files."""
    target = AsyncPath(tmp_path) / "Daily Notes" / "note.md"
    original_replace = AsyncPath.replace

    async def same_filesystem_replace(
        source: AsyncPath,
        destination: AsyncPath,
    ) -> AsyncPath:
        if source.parent != destination.parent:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        assert await source.read_text(encoding="utf-8") == "music total\n"
        return await original_replace(source, destination)

    replace = mocker.patch.object(
        AsyncPath,
        "replace",
        side_effect=same_filesystem_replace,
        autospec=True,
    )
    await atomic_write_text(target, "music total\n")
    replace.assert_awaited_once()
    assert await target.read_text(encoding="utf-8") == "music total\n"


async def test__atomic_write_text_cleans_up_after_replace_failure(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """A failed replacement preserves the old note and removes the temporary file."""
    target = AsyncPath(tmp_path) / "note.md"
    _ = await target.write_text("old\n", encoding="utf-8")
    mocker.patch.object(AsyncPath, "replace", side_effect=PermissionError("denied"))
    with pytest.raises(PermissionError, match="denied"):
        await atomic_write_text(target, "new\n")
    assert await target.read_text(encoding="utf-8") == "old\n"
    assert sorted([p.name async for p in AsyncPath(tmp_path).iterdir()]) == ["note.md"]
