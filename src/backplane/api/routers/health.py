"""Health routes."""

from __future__ import annotations

from fastapi import APIRouter

from backplane import __version__
from backplane.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health/check", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return the service health and installed version."""
    return HealthResponse(status="ok", version=__version__)
