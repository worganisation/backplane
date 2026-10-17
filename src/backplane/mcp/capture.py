"""Small private MCP surface for the dedicated Assist capture agent."""

from __future__ import annotations

from fastmcp import FastMCP

from backplane import __version__
from backplane.mcp.obsidian import record_diary, record_idea
from backplane.mcp.tasks import capture_task


def build_capture_mcp() -> FastMCP[None]:
    """Build the diary, idea and task capture server without device or vault-read tools.

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
            "If a write times out, report uncertainty rather than blindly repeating it."
        ),
    )
    _ = mcp.tool()(record_diary)
    _ = mcp.tool()(record_idea)
    _ = mcp.tool()(capture_task)
    return mcp
