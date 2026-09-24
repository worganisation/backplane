"""Registration coverage for context-capture MCP tools."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, cast

import pytest

from backplane.context.schemas import ContextEventCreate
from backplane.mcp.app_factory import build_backplane_mcp
from backplane.mcp.context_capture import (
    record_context_event,
    register_context_capture_tools,
)
from backplane.utils import SETTINGS, exc

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from backplane.mcp.auth import OAuthToolMeta, OAuthToolRegistrationKwargs


class _RecordingMcp:
    """Minimal typed recorder for FastMCP registration calls."""

    def __init__(self) -> None:
        self.calls: list[OAuthToolRegistrationKwargs] = []

    def tool(
        self,
        **kwargs: object,
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Record registration kwargs and return an identity decorator."""
        self.calls.append(
            cast("OAuthToolRegistrationKwargs", cast("object", kwargs)),
        )

        def decorator(function: Callable[..., object]) -> Callable[..., object]:
            return function

        return decorator


async def test__build_backplane_mcp__registers_context_capture_tools() -> None:
    """Private MCP exposes the shared context service operations."""
    mcp = build_backplane_mcp()

    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert tool_names >= {
        "record_context_event",
        "record_context_events",
        "find_context_events",
        "evaluate_capture_prompt",
        "mark_capture_prompt_delivered",
        "respond_to_capture_prompt",
        "dismiss_capture_prompt",
        "expire_capture_prompt",
    }


def test__register_context_capture_tools__applies_public_oauth_metadata() -> None:
    """Public registration advertises baseline OAuth on sensitive context tools."""
    registration: OAuthToolMeta = {
        "securitySchemes": [{"type": "oauth2", "scopes": ["openid"]}],
    }
    recorder = _RecordingMcp()

    register_context_capture_tools(
        cast("FastMCP[None]", cast("object", recorder)),
        require_oauth=True,
    )

    assert len(recorder.calls) == 8
    assert all(call.get("meta") == registration for call in recorder.calls)


async def test__context_mcp__defers_database_requirement_until_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP startup works unconfigured while a context operation fails closed."""
    monkeypatch.setattr(SETTINGS, "context_database_url", None)
    mcp = build_backplane_mcp()

    assert "record_context_event" in {tool.name for tool in await mcp.list_tools()}
    with pytest.raises(exc.ServiceUnavailableError):
        _ = await record_context_event(
            ContextEventCreate(
                user_id="will",
                source="test",
                idempotency_key="unconfigured",
                kind="test.event",
                occurred_at=dt.datetime(2026, 9, 2, 10, tzinfo=dt.UTC),
            ),
        )
