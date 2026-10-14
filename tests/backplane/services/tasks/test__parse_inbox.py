"""Tests for voice inbox capture parsing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backplane.utils.async_path import AsyncPath

import datetime as dt

from backplane.services.ideas import parse_inbox as _parse_inbox
from backplane.services.obsidian import ObsidianService
from backplane.utils import today
from backplane.utils.markdown import MarkdownDocument


async def test__parse_inbox_returns_recent_captures(obsidian_vault: AsyncPath) -> None:
    """Captures within the lookback window are parsed with stable IDs."""
    base_date = today()
    today_iso = base_date.isoformat()
    yesterday = (base_date - dt.timedelta(days=1)).isoformat()
    old = (base_date - dt.timedelta(days=40)).isoformat()
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        f"""# {today_iso}

## 09:15

Today's capture

# {yesterday}

## 10:00

Yesterday's capture

# {old}

## 11:00

Too old
""",
        encoding="utf-8",
    )

    async with MarkdownDocument(
        vault_path=ObsidianService.IDEA_INBOX_PATH,
        read_only=True,
    ) as doc:
        captures = _parse_inbox(doc, days=30)

    assert [c.id for c in captures] == [
        f"{today_iso}T09:15",
        f"{yesterday}T10:00",
    ]
    assert captures[0].text == "Today's capture"


async def test__parse_inbox_strips_task_backlink_annotations(
    obsidian_vault: AsyncPath,
) -> None:
    """Generated task back-links are not treated as capture text."""
    today_iso = today().isoformat()
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        f"""# {today_iso}

## 09:15

Update the Open Banking integration.

↗ [[open-banking]]

↗ \\[[escaped-task-link]\\]
""",
        encoding="utf-8",
    )

    async with MarkdownDocument(
        vault_path=ObsidianService.IDEA_INBOX_PATH,
        read_only=True,
    ) as doc:
        captures = _parse_inbox(doc, days=30)

    assert captures[0].text == "Update the Open Banking integration."


async def test__parse_inbox_skips_invalid_dates_and_empty_captures(
    obsidian_vault: AsyncPath,
) -> None:
    """Non-date headings and empty capture sections are ignored."""
    today_iso = today().isoformat()
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        f"""# Not a date

## 09:15

Ignored capture

# {today_iso}

## 10:00

## 11:00

Included capture
""",
        encoding="utf-8",
    )

    async with MarkdownDocument(
        vault_path=ObsidianService.IDEA_INBOX_PATH,
        read_only=True,
    ) as doc:
        captures = _parse_inbox(doc, days=30)

    assert [c.id for c in captures] == [f"{today_iso}T11:00"]
