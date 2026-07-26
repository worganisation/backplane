"""Public-facing Backplane MCP server entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import uvicorn
import uvloop
from loguru import logger

from backplane import __version__
from backplane.mcp.asgi import compose_public_mcp_app

if TYPE_CHECKING:
    from fastmcp.server.http import StarletteWithLifespan

_HOST: Final = "0.0.0.0"  # ruff:ignore[hardcoded-bind-all-interfaces]
_PORT: Final = 8001


def create_public_mcp_app() -> StarletteWithLifespan:
    """Build the authenticated public MCP HTTP ASGI app.

    Returns:
        Streamable HTTP ASGI app for the ChatGPT-facing MCP server.
    """
    return compose_public_mcp_app()


def main() -> None:
    """Run the public MCP server until interrupted."""
    logger.info(
        "Starting public Backplane MCP server v{} on {}:{} with OAuth",
        __version__,
        _HOST,
        _PORT,
    )
    app = create_public_mcp_app()

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
