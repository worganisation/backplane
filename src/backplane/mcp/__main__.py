"""Entrypoint for running the Backplane MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import uvicorn
import uvloop
from loguru import logger

from backplane import __version__
from backplane.mcp import create_mcp_server
from backplane.mcp.asgi import compose_private_app
from backplane.utils.settings import SETTINGS

if TYPE_CHECKING:
    from fastmcp import FastMCP

_HOST: Final = "0.0.0.0"  # ruff:ignore[hardcoded-bind-all-interfaces]
_PORT: Final = 8000


def create_private_mcp_server() -> FastMCP[None]:
    """Build the private Home Assistant-facing MCP server.

    Returns:
        FastMCP server configured to notify Home Assistant on startup.
    """
    return create_mcp_server(notify_home_assistant=True)


def main() -> None:
    """Run the private MCP server until interrupted."""
    logger.info("Starting Backplane MCP server v{} on {}:{}", __version__, _HOST, _PORT)
    transport_note = (
        "streamable HTTP (/mcp, /mcp-ha)" if SETTINGS.ha_mcp_enabled else "SSE"
    )
    logger.info("Serving private REST API at /api alongside MCP {}", transport_note)
    app = compose_private_app()
    uvloop.run(
        uvicorn.Server(
            uvicorn.Config(
                app,
                host=_HOST,
                port=_PORT,
                log_level="info",
            ),
        ).serve(),
    )


if __name__ == "__main__":
    main()
