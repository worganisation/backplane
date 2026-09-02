"""MCP tools and resources for the Obsidian vault."""

from __future__ import annotations

import datetime as dt  # ruff: ignore[typing-only-standard-library-import]  # used at runtime by FastMCP schema introspection
from typing import TYPE_CHECKING, Annotated, Literal

from loguru import logger
from pydantic import Field

from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs
from backplane.operations.daily_notes import (
    read_daily_note,
    update_daily_note_section,
)
from backplane.operations.daily_notes import (
    record_idea as record_idea_operation,
)
from backplane.services.obsidian import ObsidianService
from backplane.utils import AsyncPath, today

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ADD_DESCRIPTION = """Add content to a section of the user's Obsidian daily note.

Use when the user wants to capture something "today", "in my daily note", or into a daily-note section.

When the target section is unknown or ambiguous, call `get_daily_note` first to inspect the note's
headings. If a section lookup fails, the error includes available sections at that level.

If the user explicitly asks for another section, create it with `create_section_if_not_exists=true`.
If a section is missing and the tool returns available sections, retry with the closest
matching path or create the requested section when appropriate."""

_GET_DAILY_NOTE_DESCRIPTION = """Read the user's Obsidian daily note.

Use when the user asks what is in the daily note, wants to review captured tasks/ideas/notes,
or needs daily-note context for a follow-up."""

_RECORD_IDEA_DESCRIPTION = """Record a loose, non-actionable idea in the Obsidian idea inbox.

Use for speculative captures such as:
- "maybe…"
- "I could…"
- "I wonder if…"
- "worth investigating…"
- possible automations, improvements, or future projects the user has not committed to doing

Do not use this for tasks or action items. If the user says they need to do something, should do
something, wants to remember to act on something, or asks for a task/reminder/list item,
use `create_task`.

Convert spoken phrasing to a written sentence while preserving the user's wording as closely as possible."""

_MOVE_NOTE_DESCRIPTION = """Move or rename an Obsidian markdown note.

Use when the user wants to relocate, reorganise, or rename a note.

Paths are vault-relative. Missing destination parent folders are created automatically.
The source note must exist. The destination must not already exist."""


async def add_to_daily_note(
    *,
    heading_path: Annotated[
        tuple[str, ...],
        Field(
            description=(
                "Section path relative to the daily note body. Do not include the "
                "top-level date heading."
            ),
            min_length=1,
        ),
    ],
    content: Annotated[str, Field(description="Text to add to the section.")],
    mode: Annotated[
        Literal["append", "prepend", "replace"],
        Field(
            description=(
                "How to combine content with the existing section. Prefer `append`; "
                "use `replace` only when explicitly requested."
            ),
        ),
    ] = "append",
    create_section_if_not_exists: Annotated[
        bool,
        Field(
            description=(
                "Create the requested section and any missing ancestors if they do not exist."
            ),
        ),
    ] = False,
    date: Annotated[
        dt.date | None,
        Field(
            description="Daily note date in YYYY-MM-DD. Defaults to today's local date.",
        ),
    ] = None,
) -> str:
    """Add content to a section of the user's Obsidian daily note.

    Args:
        heading_path: The headings to traverse to the section to update.
        content: The text to add to the section.
        mode: How to combine ``content`` with any existing section text.
        create_section_if_not_exists: Set true to create the section (and any missing
            ancestors) if it doesn't exist; false returns an error listing available
            sections.
        date: The date of the daily note. Defaults to today's local date.

    Returns:
        The updated section, rendered as markdown.

    """
    logger.info(
        "add_to_daily_note: date={} heading={} mode={} create={}",
        date,
        heading_path,
        mode,
        create_section_if_not_exists,
    )

    return await update_daily_note_section(
        heading_path=heading_path,
        content=content,
        mode=mode,
        create_section_if_not_exists=create_section_if_not_exists,
        date=date,
    )


async def get_daily_note(
    date: Annotated[
        dt.date | None,
        Field(
            description="Daily note date in YYYY-MM-DD. Defaults to today's local date.",
        ),
    ] = None,
) -> str:
    """Read the user's Obsidian daily note.

    Args:
        date: The date of the daily note. Defaults to today's local date.

    Returns:
        The daily note, rendered as markdown.
    """
    logger.info("get_daily_note: date={}", date)
    return await read_daily_note(date)


async def record_idea(
    *,
    idea: Annotated[
        str,
        Field(
            description=(
                "The loose, non-actionable idea to record. Preserve the user's wording as "
                "closely as possible."
            ),
        ),
    ],
) -> str:
    """Record a new idea in the Obsidian idea inbox.

    Returns:
        The string "Idea recorded successfully."
    """
    logger.info("record_idea")
    return await record_idea_operation(idea)


async def move_note(
    source_path: Annotated[
        AsyncPath,
        Field(description="Existing vault-relative note path."),
    ],
    destination_path: Annotated[
        AsyncPath,
        Field(description="New vault-relative note path."),
    ],
) -> str:
    """Move a vault note to a new location.

    Returns:
        str: Confirmation message including the destination path.
    """
    logger.info(
        "move_note: source={!r} destination={!r}",
        source_path,
        destination_path,
    )
    path = await ObsidianService.move_note(source_path, destination_path)
    return f"Moved note to {path}."


# ------------------------------------------------------------
# Resources


async def daily_note_today_resource() -> str:
    """Return today's daily note as rendered markdown."""
    return await read_daily_note(today())


async def daily_note_by_date_resource(
    date: Annotated[
        dt.date,
        Field(description="Daily note date in YYYY-MM-DD."),
    ],
) -> str:
    """Fetch the daily note for a given date.

    Returns:
        The daily note content as rendered markdown.
    """
    return await read_daily_note(date)


def register_obsidian_tools(mcp: FastMCP[None], *, require_oauth: bool = False) -> None:
    """Register Obsidian tools and resources on a FastMCP server instance.

    If require_oauth is true, OAuth authentication is applied to all registered tools and resources.

    Parameters:
        require_oauth: If true, OAuth authentication is required for all registered tools and resources.
    """
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()

    _ = mcp.tool(description=_ADD_DESCRIPTION, **auth_kwargs)(add_to_daily_note)
    _ = mcp.tool(description=_GET_DAILY_NOTE_DESCRIPTION, **auth_kwargs)(get_daily_note)
    _ = mcp.tool(description=_RECORD_IDEA_DESCRIPTION, **auth_kwargs)(record_idea)
    _ = mcp.tool(description=_MOVE_NOTE_DESCRIPTION, **auth_kwargs)(move_note)
    _ = mcp.resource(
        uri="obsidian://daily-note/today",
        name="Today's Daily Note",
        description="The user's Obsidian daily note for today's local date.",
        mime_type="text/markdown",
        **auth_kwargs,
    )(daily_note_today_resource)
    _ = mcp.resource(
        uri="obsidian://daily-note/{date}",
        name="Daily Note by Date",
        description="The user's Obsidian daily note for a given ISO date.",
        mime_type="text/markdown",
        **auth_kwargs,
    )(daily_note_by_date_resource)
