"""Tests for shared daily-note operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from backplane.operations.daily_notes import record_idea, update_daily_note_section
from backplane.utils import exc

if TYPE_CHECKING:
    from backplane.utils.async_path import AsyncPath


async def test__update_daily_note_section__creates_and_updates_section(
    obsidian_vault: AsyncPath,
) -> None:
    """The operation creates the requested daily-note section and writes its content."""
    _ = obsidian_vault

    markdown = await update_daily_note_section(
        heading_path=("Tasks",),
        content="Buy milk",
        create_section_if_not_exists=True,
    )

    assert markdown == "## Tasks\n\nBuy milk"


async def test__update_daily_note_section__wraps_missing_section_error(
    obsidian_vault: AsyncPath,
) -> None:
    """The operation reports missing sections as information required."""
    _ = obsidian_vault

    with pytest.raises(exc.InformationRequiredError) as error:
        _ = await update_daily_note_section(
            heading_path=("Tasks",),
            content="Buy milk",
        )

    detail = cast("dict[str, object]", error.value.detail)
    assert detail.get("siblings") == []


async def test__record_idea__returns_confirmation(
    obsidian_vault: AsyncPath,
) -> None:
    """The operation records an idea and returns its confirmation."""
    ideas_path = obsidian_vault / "Inbox" / "Ideas.md"
    _ = await ideas_path.parent.mkdir(parents=True)
    _ = await ideas_path.write_text("", encoding="utf-8")

    result = await record_idea("Automate rain alerts")

    assert result == "Idea recorded successfully."
