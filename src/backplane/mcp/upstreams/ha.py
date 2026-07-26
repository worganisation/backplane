"""Home Assistant MCP add-on upstream proxy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from fastmcp.exceptions import NotFoundError
from fastmcp.server import create_proxy
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from loguru import logger

from backplane.mcp.auth import HA_MCP_SCOPE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastmcp import FastMCP
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools.base import Tool, ToolResult
    from mcp import types as mt


@dataclass(frozen=True)
class HomeAssistantMcpConfig:
    """Configuration for the Home Assistant MCP upstream.

    Callers must validate that the upstream is enabled and that ``url`` is set
    (for example via ``Settings.require_ha_mcp_url``) before mounting.
    """

    url: str
    namespace: str


class _RequireHaScopeMiddleware(Middleware):
    """Hide and block HA-namespaced tools unless the token has ``HA_MCP_SCOPE``."""

    _tool_prefix: str
    _scope: str

    def __init__(self, *, namespace: str, scope: str = HA_MCP_SCOPE) -> None:
        self._tool_prefix = f"{namespace}_"
        self._scope = scope

    def _token_has_scope(self) -> bool:
        token = get_access_token()
        return token is not None and self._scope in token.scopes

    def _is_ha_tool(self, name: str) -> bool:
        return name.startswith(self._tool_prefix)

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        if self._token_has_scope():
            return tools
        return [tool for tool in tools if not self._is_ha_tool(tool.name)]

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if self._is_ha_tool(context.message.name) and not self._token_has_scope():
            msg = f"Unknown tool: {context.message.name}"
            raise NotFoundError(msg)
        return await call_next(context)


def mount_home_assistant_upstream(
    mcp: FastMCP[None],
    config: HomeAssistantMcpConfig,
    *,
    require_ha_scope: bool = False,
) -> None:
    """Mount the Home Assistant MCP add-on as a namespaced upstream proxy.

    Args:
        mcp: Backplane MCP server to augment with HA tools.
        config: Validated HA MCP upstream configuration.
        require_ha_scope: When true, HA tools are only visible to tokens that
            include ``HA_MCP_SCOPE`` (public OAuth clients).
    """
    logger.info(
        "Mounting Home Assistant MCP upstream with namespace {}",
        config.namespace,
    )
    ha_proxy = create_proxy(
        config.url,
        name="Home Assistant MCP",
    )
    mcp.mount(ha_proxy, namespace=config.namespace)
    if require_ha_scope:
        mcp.add_middleware(
            _RequireHaScopeMiddleware(namespace=config.namespace),
        )
