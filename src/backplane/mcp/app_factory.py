"""FastMCP server factory for Backplane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from backplane import __version__
from backplane.mcp.context_capture import register_context_capture_tools
from backplane.mcp.instructions import BACKPLANE_MCP_INSTRUCTIONS
from backplane.mcp.obsidian import register_obsidian_tools
from backplane.mcp.tasks import register_task_tools
from backplane.mcp.vault_entities import register_vault_entity_tools
from backplane.mcp.vault_search import register_vault_search_tools
from backplane.services.home_assistant import notify_startup, reload_mcp_integration

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastmcp.server.auth import AuthProvider


@lifespan
async def _home_assistant_lifespan(mcp: FastMCP[None]) -> AsyncGenerator[None]:
    """Startup lifecycle hook that gathers MCP server metadata and notifies Home Assistant.

    Collects registered tools and resources from the MCP server and sends a startup
    notification to Home Assistant, then reloads the Home Assistant MCP integration.
    """
    raw_tools = await mcp.list_tools()
    raw_resources = await mcp.list_resources()
    raw_templates = await mcp.list_resource_templates()

    tools = [t.name for t in raw_tools]
    resources = [r.name for r in raw_resources] + [t.name for t in raw_templates]

    await notify_startup(tools, resources)
    await reload_mcp_integration()
    yield


def build_backplane_mcp(
    *,
    name: str = "Backplane",
    auth: AuthProvider | None = None,
    notify_home_assistant: bool = False,
    require_oauth: bool = False,
) -> FastMCP[None]:
    """Create a Backplane MCP server instance with all tools registered.

    Args:
        name: Display name for the MCP server instance.
        auth: Optional FastMCP auth provider.
        notify_home_assistant: Whether to trigger Home Assistant MCP integration
            notification and reload on startup.
        require_oauth: Whether to register tools and resources with OAuth metadata
            for ChatGPT-facing authentication.

    Returns:
        Configured FastMCP server instance.
    """
    mcp: FastMCP[None] = FastMCP(
        name,
        instructions=BACKPLANE_MCP_INSTRUCTIONS,
        version=__version__,
        auth=auth,
        lifespan=_home_assistant_lifespan if notify_home_assistant else None,
    )

    register_obsidian_tools(mcp, require_oauth=require_oauth)
    register_context_capture_tools(mcp, require_oauth=require_oauth)
    register_task_tools(mcp, require_oauth=require_oauth)
    register_vault_entity_tools(mcp, require_oauth=require_oauth)
    register_vault_search_tools(mcp, require_oauth=require_oauth)

    return mcp
