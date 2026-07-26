"""ASGI composition for Backplane MCP servers."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from fastmcp.server.http import StarletteWithLifespan
from starlette.routing import BaseRoute, Route

from backplane.mcp.app_factory import build_backplane_mcp
from backplane.mcp.auth import create_public_mcp_auth
from backplane.mcp.upstreams import get_enabled_upstreams, mount_upstream
from backplane.utils.settings import SETTINGS

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.applications import Starlette
    from starlette.types import Lifespan

    from backplane.mcp.upstreams.base import UpstreamMcpConfig


def _upstream_http_path(config: UpstreamMcpConfig) -> str:
    """Return the private HTTP path assigned to an upstream."""
    return f"/mcp-{config.namespace}"


def _upstream_mcp_route(
    upstream_app: StarletteWithLifespan,
    path: str,
) -> Route | None:
    """Return the streamable HTTP route from an upstream MCP ASGI app.

    Returns:
        The MCP route for ``path``, or ``None`` if missing.
    """
    for route in upstream_app.routes:
        if isinstance(route, Route) and route.path == path:
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
    upstream_apps: tuple[tuple[str, StarletteWithLifespan], ...],
) -> StarletteWithLifespan:
    """Merge a core MCP HTTP app with private upstream routes.

    Returns:
        Combined ASGI app exposing ``/mcp`` and configured upstream routes.

    Raises:
        RuntimeError: If an expected upstream MCP HTTP route is missing.
    """
    if not upstream_apps:
        return core_app

    routes: list[BaseRoute] = [*core_app.routes]
    apps = [core_app]
    for path, upstream_app in upstream_apps:
        upstream_route = _upstream_mcp_route(upstream_app, path)
        if upstream_route is None:
            msg = f"Expected upstream MCP HTTP route at {path}"
            raise RuntimeError(msg)
        routes.append(upstream_route)
        apps.append(upstream_app)

    return StarletteWithLifespan(
        routes=routes,
        middleware=core_app.user_middleware,
        lifespan=_combine_lifespans(*apps),
    )


def _build_private_upstream_mcp(
    config: UpstreamMcpConfig,
) -> StarletteWithLifespan:
    """Build a private Backplane server augmented with one upstream.

    Returns:
        Streamable HTTP ASGI app for the upstream's private path.
    """
    mcp = build_backplane_mcp(name=f"Backplane + {config.name}")
    mount_upstream(mcp, config, gated=False)
    return mcp.http_app(transport="http", path=_upstream_http_path(config))


def compose_public_mcp_app() -> StarletteWithLifespan:
    """Build the authenticated public MCP HTTP ASGI app.

    Returns:
        Streamable HTTP ASGI app for ``/mcp``. When HA upstream is enabled, HA
        tools are mounted on the same server and gated by ``HA_MCP_SCOPE``.
    """
    auth = create_public_mcp_auth()
    mcp = build_backplane_mcp(auth=auth, require_oauth=True)
    for config in get_enabled_upstreams(SETTINGS):
        mount_upstream(mcp, config, gated=True)
    return mcp.http_app(transport="http")


def compose_private_mcp_app() -> StarletteWithLifespan:
    """Build the private LAN MCP HTTP ASGI app with optional HA upstream.

    Returns:
        Streamable HTTP ASGI app for ``/mcp`` and, when enabled, ``/mcp-ha``.
    """
    core_mcp = build_backplane_mcp(notify_home_assistant=True)
    core_app = core_mcp.http_app(transport="http")
    upstream_apps = tuple(
        (
            _upstream_http_path(config),
            _build_private_upstream_mcp(config),
        )
        for config in get_enabled_upstreams(SETTINGS)
    )
    return _compose_mcp_apps(
        core_app=core_app,
        upstream_apps=upstream_apps,
    )
