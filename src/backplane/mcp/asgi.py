"""ASGI composition for Backplane MCP servers."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from fastmcp.server.http import StarletteWithLifespan
from starlette.routing import BaseRoute, Route

from backplane.mcp.app_factory import build_backplane_mcp
from backplane.mcp.auth import create_public_mcp_auth
from backplane.mcp.upstreams.ha import (
    HomeAssistantMcpConfig,
    mount_home_assistant_upstream,
)
from backplane.utils.settings import SETTINGS

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.applications import Starlette
    from starlette.types import Lifespan

_HA_MCP_HTTP_PATH = "/mcp-ha"


def _ha_mcp_route(ha_app: StarletteWithLifespan) -> Route | None:
    """Return the streamable HTTP route from an HA MCP ASGI app.

    Returns:
        The protected MCP route for ``/mcp-ha``, or ``None`` if missing.
    """
    for route in ha_app.routes:
        if isinstance(route, Route) and route.path == _HA_MCP_HTTP_PATH:
            return route
    return None


def _combine_lifespans(
    *apps: StarletteWithLifespan,
) -> Lifespan[Starlette]:
    """Return a Starlette lifespan that runs each MCP app lifespan in order."""

    @asynccontextmanager
    async def combined_lifespan(app: Starlette) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            for mcp_app in apps:
                _ = await stack.enter_async_context(mcp_app.router.lifespan_context(app))
            yield

    return combined_lifespan


def _compose_mcp_apps(
    *,
    core_app: StarletteWithLifespan,
    ha_app: StarletteWithLifespan | None,
) -> StarletteWithLifespan:
    """Merge a core MCP HTTP app with an optional HA MCP route.

    Returns:
        Combined ASGI app exposing ``/mcp`` and, when configured, ``/mcp-ha``.

    Raises:
        RuntimeError: If the HA MCP HTTP route is missing from the HA app.
    """
    if ha_app is None:
        return core_app

    ha_route = _ha_mcp_route(ha_app)
    if ha_route is None:
        msg = f"Expected HA MCP HTTP route at {_HA_MCP_HTTP_PATH}"
        raise RuntimeError(msg)

    routes: list[BaseRoute] = [*core_app.routes, ha_route]
    return StarletteWithLifespan(
        routes=routes,
        middleware=core_app.user_middleware,
        lifespan=_combine_lifespans(core_app, ha_app),
    )


def _build_private_ha_mcp() -> StarletteWithLifespan | None:
    """Build the private HA-augmented MCP HTTP app when upstream proxying is enabled.

    Returns:
        Streamable HTTP ASGI app for ``/mcp-ha``, or ``None`` when disabled.
    """
    if not SETTINGS.ha_mcp_enabled:
        return None

    config = HomeAssistantMcpConfig(
        url=SETTINGS.require_ha_mcp_url(),
        namespace=SETTINGS.ha_mcp_namespace,
    )
    ha_mcp = build_backplane_mcp(name="Backplane + Home Assistant")
    mount_home_assistant_upstream(ha_mcp, config)
    return ha_mcp.http_app(transport="http", path=_HA_MCP_HTTP_PATH)


def compose_public_mcp_app() -> StarletteWithLifespan:
    """Build the authenticated public MCP HTTP ASGI app.

    Returns:
        Streamable HTTP ASGI app for ``/mcp``. When HA upstream is enabled, HA
        tools are mounted on the same server and gated by ``HA_MCP_SCOPE``.
    """
    auth = create_public_mcp_auth()
    mcp = build_backplane_mcp(auth=auth, require_oauth=True)
    if SETTINGS.ha_mcp_enabled:
        mount_home_assistant_upstream(
            mcp,
            HomeAssistantMcpConfig(
                url=SETTINGS.require_ha_mcp_url(),
                namespace=SETTINGS.ha_mcp_namespace,
            ),
            require_ha_scope=True,
        )
    return mcp.http_app(transport="http")


def compose_private_mcp_app() -> StarletteWithLifespan:
    """Build the private LAN MCP HTTP ASGI app with optional HA upstream.

    Returns:
        Streamable HTTP ASGI app for ``/mcp`` and, when enabled, ``/mcp-ha``.
    """
    core_mcp = build_backplane_mcp(notify_home_assistant=True)
    core_app = core_mcp.http_app(transport="http")
    ha_app = _build_private_ha_mcp()
    return _compose_mcp_apps(core_app=core_app, ha_app=ha_app)
