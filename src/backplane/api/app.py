"""FastAPI application exposing Backplane's vault operations."""

from __future__ import annotations

from fastapi import FastAPI

from backplane import __version__
from backplane.api.errors import handle_backplane_error
from backplane.api.routers import daily_notes, entities, health, notes, search, tasks
from backplane.utils import exc


def create_api_app() -> FastAPI:
    """Create the private REST API without Home Assistant MCP passthrough.

    Returns:
        FastAPI application serving vault operations.
    """
    app = FastAPI(
        title="Backplane REST API",
        version=__version__,
        description="Semantic vault operations for a private Backplane instance.",
    )
    app.add_exception_handler(exc.BackplaneError, handle_backplane_error)
    for router in (
        health.router,
        daily_notes.router,
        notes.router,
        tasks.router,
        entities.router,
        search.router,
    ):
        app.include_router(router)
    return app
