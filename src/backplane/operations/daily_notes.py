"""Shared daily-note and idea-capture operations."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from backplane.services.ideas import IdeaService
from backplane.services.obsidian import ObsidianService
from backplane.utils import SETTINGS, exc, format_human_date, today

if TYPE_CHECKING:
    from backplane.services.vault_entities import UpdateMode


async def record_diary(content: str, date: dt.date | None = None) -> str:
    """Append a diary entry with a server-generated capture timestamp.

    Returns:
        A short confirmation after the note is saved.

    Raises:
        BadRequestError: If the entry contains no text.
    """
    if not content.strip():
        msg = "Diary content must not be blank."
        raise exc.BadRequestError(msg)

    captured_at = dt.datetime.now(SETTINGS.local_timezone)
    resolved_date = date or captured_at.date()
    _ = await update_daily_note_section(
        heading_path=("Diary",),
        content=f"Recorded {captured_at:%Y-%m-%d %H:%M %z} — {content}",
        create_section_if_not_exists=True,
        date=resolved_date,
    )
    return f"Diary entry saved to {resolved_date.isoformat()}."


async def read_daily_note(date: dt.date | None = None) -> str:
    """Read and render a daily note.

    Returns:
        Rendered Markdown for the requested daily note.

    Raises:
        NotFoundError: If the requested daily note does not exist.
    """
    resolved_date = date or today()
    try:
        async with ObsidianService().daily_note(
            date=resolved_date,
            read_only=True,
        ) as daily_note:
            return daily_note.render()
    except FileNotFoundError as error:
        raise exc.NotFoundError(
            message=f"Daily note for {resolved_date.isoformat()} not found.",
            detail={"date": resolved_date.isoformat()},
        ) from error


async def update_daily_note_section(
    *,
    heading_path: tuple[str, ...],
    content: str,
    mode: UpdateMode = "append",
    create_section_if_not_exists: bool = False,
    date: dt.date | None = None,
) -> str:
    """Update and render a section in a daily note.

    Returns:
        Rendered Markdown for the updated section.

    Raises:
        InformationRequiredError: If the requested section is missing and creation was not requested.
    """
    resolved_date = date or today()
    resolved_heading_path = heading_path
    if resolved_heading_path[0] != (
        top_level_heading := format_human_date(resolved_date)
    ):
        resolved_heading_path = (top_level_heading, *resolved_heading_path)

    async with ObsidianService().daily_note(
        date=resolved_date,
        create_if_not_exists=True,
        read_only=False,
    ) as daily_note:
        try:
            section = daily_note.get_section(
                resolved_heading_path,
                create_if_not_exists=create_section_if_not_exists,
            )
        except exc.SectionNotFoundError as error:
            raise exc.InformationRequiredError(
                message=(
                    f"{error} Retry with an existing section, or set "
                    "`create_section_if_not_exists=true` to create it."
                ),
                detail=error.detail,
            ) from error

        if not section.content or mode == "replace":
            section.replace_content(content)
        elif mode == "append":
            section.append_content(content)
        else:
            section.prepend_content(content)

    return section.render()


async def record_idea(idea: str) -> str:
    """Record an idea in the timestamped idea inbox.

    Returns:
        Confirmation message for the capture.
    """
    capture = await IdeaService.record(idea)
    return f"Idea recorded successfully. ID: {capture.id}"
