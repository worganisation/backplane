"""Tests for the composed private API and MCP ASGI application."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from starlette.routing import Mount, Route

from backplane.mcp.asgi import compose_private_app

if TYPE_CHECKING:
    from backplane.utils.async_path import AsyncPath


async def test__compose_private_app__serves_rest_api_and_sse_mcp(
    obsidian_vault: AsyncPath,
) -> None:
    """The private ASGI app serves REST while retaining the SSE MCP endpoints."""
    _ = obsidian_vault
    app = compose_private_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://backplane.test",
    ) as client:
        response = await client.get("/api/health/check")

    assert response.status_code == 200
    route_paths = {
        route.path for route in app.routes if isinstance(route, (Mount, Route))
    }
    assert route_paths >= {"/api", "/sse", "/messages"}
