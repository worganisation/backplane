"""Fixtures for REST API tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from backplane.api.app import create_api_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI


@pytest.fixture
def api_app() -> FastAPI:
    """Return the Backplane REST application."""
    return create_api_app()


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Return an HTTP client bound to the Backplane REST application.

    Yields:
        HTTP client for the API application.
    """
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://backplane.test",
    ) as client:
        yield client
