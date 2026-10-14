"""Kanban board markdown manipulation for Obsidian vault boards."""

from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from loguru import logger

from .exceptions import SectionNotFoundError
from .helpers.files import atomic_write_text, vault_write_lock
from .helpers.obsidian import build_obsidian_link
from .settings import SETTINGS

if TYPE_CHECKING:
    from .async_path import AsyncPath

_NEXT_SECTION_RE: Final = re.compile(r"^## ", re.MULTILINE)


def _format_card_line(
    note_path: AsyncPath,
    *,
    due: dt.date | dt.datetime | None = None,
) -> str:
    """Build a markdown Kanban task line with a wiki link and optional due metadata.

    Parameters:
        due (date | datetime | None): Optional due date or datetime.
            Timezone-aware datetimes are converted to local time. Dates format as
            `@{YYYY-MM-DD}`; datetimes add time as `@@{HH:MM}`.

    Returns:
        str: A markdown checkbox line with the note link and optional due metadata.
    """
    line = f"- [ ] {build_obsidian_link(note_path)}"
    if due is None:
        return line

    if isinstance(due, dt.datetime):
        if due.tzinfo is not None:
            due = due.astimezone(SETTINGS.local_timezone)

        due = due.replace(microsecond=0)
        return f"{line} @{{{due.date().isoformat()}}} @@{{{due.strftime('%H:%M')}}}"

    return f"{line} @{{{due.isoformat()}}}"


@lru_cache(maxsize=1024)
def _section_heading_re(section: str) -> re.Pattern[str]:
    return re.compile(rf"^## {re.escape(section)}\s*$", re.MULTILINE)


def add_card_to_list(
    text: str,
    note_path: AsyncPath,
    section: str,
    *,
    due: dt.date | dt.datetime | None = None,
) -> str:
    """Append a Kanban card at the end of a ``##`` section.

    Args:
        text: Full board markdown contents.
        note_path: Vault-relative path to the note (e.g. ``Projects/Foo.md``).
        section: Heading text after ``##`` (e.g. ``Backlog``, ``Todo``).
        due: Optional due date or datetime rendered as Obsidian Kanban ``@{…}`` metadata.

    Returns:
        Updated board markdown.

    Raises:
        SectionNotFoundError: If the section heading is not found in the board file.
    """
    if (match := _section_heading_re(section).search(text)) is None:
        raise SectionNotFoundError(section)

    card_line = _format_card_line(note_path, due=due)
    after_header = text[match.end() :]

    if (next_section := _NEXT_SECTION_RE.search(after_header)) is None:
        return f"{text.rstrip()}\n{card_line}\n"

    insert_pos = match.end() + next_section.start()
    before = text[:insert_pos].rstrip()
    after = text[insert_pos:]

    return f"{before}\n{card_line}\n{after}"


async def append_board_card(
    board_path: AsyncPath,
    note_path: AsyncPath,
    *,
    section: str = "Backlog",
    due: dt.date | dt.datetime | None = None,
) -> None:
    """Append a Kanban card at the end of a board column section.

    Args:
        board_path: Absolute path to a vault Kanban board markdown file.
        note_path: Vault-relative path to the note (e.g. ``Projects/Foo.md``).
        section: Heading text after ``##`` (e.g. ``Backlog``, ``Todo``).
        due: Optional due date or datetime rendered as Obsidian Kanban ``@{…}`` metadata.

    Raises:
        ValueError: If an external board modification is detected before writing.
    """
    async with vault_write_lock():
        text = await board_path.read_text(encoding="utf-8")
        new_text = add_card_to_list(text, note_path, section, due=due)
        if await board_path.read_text(encoding="utf-8") != text:
            msg = "Board was modified externally since it was loaded."
            raise ValueError(msg)

        await atomic_write_text(board_path, new_text)

    logger.info(
        "Appended Kanban card: board={} section={} note_path={}",
        board_path,
        section,
        note_path,
    )
