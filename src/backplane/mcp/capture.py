"""Small private MCP surface requiring retry keys for every voice capture."""

from __future__ import annotations

import datetime as dt  # ruff: ignore[typing-only-standard-library-import] -- FastMCP resolves annotations at runtime.
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from backplane import __version__
from backplane.mcp import obsidian, tasks
from backplane.operations.tasks import (
    TaskCreationOutcome,  # ruff: ignore[typing-only-first-party-import] -- FastMCP resolves the response schema.
)
from backplane.utils.enums import (
    Priority,  # ruff: ignore[typing-only-first-party-import] -- FastMCP resolves enum arguments.
)


async def record_diary(
    content: str,
    idempotency_key: Annotated[str, Field(min_length=1)],
    date: dt.date | None = None,
) -> str:
    """Save an experience verbatim; omit date for today. Reuse key and fields on retry.

    Returns:
        Confirmation with the saved diary date.
    """
    return await obsidian.record_diary(content, date, idempotency_key=idempotency_key)


async def record_idea(
    idea: str,
    idempotency_key: Annotated[str, Field(min_length=1)],
) -> str:
    """Save a possibility verbatim. Reuse the same key and text on retry.

    Returns:
        Confirmation with the stable idea identity.
    """
    return await obsidian.record_idea(idea=idea, idempotency_key=idempotency_key)


async def capture_task(
    description: str,
    idempotency_key: Annotated[str, Field(min_length=1)],
    title: str | None = None,
    due: str | None = None,
    priority: Priority | None = None,
    project: Annotated[
        str | None,
        Field(
            description="Explicit project name; creates a stub if missing. Omit for projectless capture.",
        ),
    ] = None,
) -> TaskCreationOutcome:
    """Save an action without inference. Only pass explicit fields; reuse key and fields on retry.

    Returns:
        Saved task and warnings for any secondary writes needing repair.
    """
    return await tasks.capture_task(
        description,
        title=title,
        due=due,
        priority=priority,
        project=project,
        idempotency_key=idempotency_key,
    )


def build_capture_mcp() -> FastMCP[None]:
    """Build the three capture tools with required non-null operation keys.

    Returns:
        The capture-only MCP server.
    """
    mcp: FastMCP[None] = FastMCP(
        "Backplane Capture",
        version=__version__,
        instructions=(
            "Save completed experiences with record_diary, possibilities with record_idea, "
            "and actions to do with capture_task. Preserve the user's words. "
            "Confirm only successful saves; report warnings. No device control or reminders. "
            "Supply a unique idempotency_key before every save. Retry only with the same "
            "key and identical fields; never invent a new key to retry an uncertain save."
        ),
    )
    _ = mcp.tool()(record_diary)
    _ = mcp.tool()(record_idea)
    _ = mcp.tool()(capture_task)
    return mcp
