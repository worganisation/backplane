"""Capture agents can write through a small tool surface without general vault access."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from starlette.routing import Route

from backplane.mcp.asgi import compose_private_app
from backplane.mcp.capture import build_capture_mcp
from backplane.operations.daily_notes import read_daily_note

if TYPE_CHECKING:
    from backplane.utils.async_path import AsyncPath


async def test_capture_surface_saves_diary_and_rejects_general_tools(
    obsidian_vault: AsyncPath,
) -> None:
    """The capture server saves real diary text but cannot expose or call vault readers."""
    _ = obsidian_vault
    async with Client(build_capture_mcp()) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "record_diary",
            "record_idea",
            "capture_task",
        }
        for tool in tools:
            assert "idempotency_key" in tool.input_schema["required"]
        with pytest.raises(ToolError):
            await client.call_tool("record_idea", {"idea": "Missing key"})
        with pytest.raises(ToolError):
            await client.call_tool(
                "record_idea",
                {"idea": "Null key", "idempotency_key": None},
            )
        result = await client.call_tool(
            "record_diary",
            {
                "content": "Walked the dog for 25 minutes at 16:00.",
                "date": "2026-10-17",
                "idempotency_key": "voice-diary-1",
            },
        )
        assert not result.is_error
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("get_daily_note", {})

    note = await read_daily_note(dt.date(2026, 10, 17))
    assert "Walked the dog for 25 minutes at 16:00." in note
    assert "Recorded " in note


def test_capture_endpoint_is_available_with_the_sse_transport() -> None:
    """The dedicated HTTP endpoint coexists with the existing SSE endpoints."""
    paths = {
        route.path for route in compose_private_app().routes if isinstance(route, Route)
    }
    assert {"/sse", "/mcp-capture"} <= paths
