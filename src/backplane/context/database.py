"""Async database configuration for context capture."""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backplane.utils import SETTINGS, exc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

AsyncSessionFactory = async_sessionmaker[AsyncSession]


def require_context_database_url() -> str:
    """Return the configured context database URL without exposing it in settings repr.

    Raises:
        ServiceUnavailableError: If context persistence is not configured.
    """
    value = SETTINGS.context_database_url
    if value is None or not (url := value.get_secret_value().strip()):
        msg = "CONTEXT_DATABASE_URL is required for context capture."
        raise exc.ServiceUnavailableError(message=msg)
    return url


@cache
def context_engine() -> AsyncEngine:
    """Return the process-wide async context database engine."""
    return create_async_engine(
        require_context_database_url(),
        echo=SETTINGS.context_database_echo,
        pool_pre_ping=True,
    )


@cache
def context_session_factory() -> AsyncSessionFactory:
    """Return the process-wide async session factory."""
    return async_sessionmaker(
        context_engine(),
        expire_on_commit=False,
    )


async def dispose_context_database() -> None:
    """Dispose the cached engine and clear database factories."""
    if context_engine.cache_info().currsize:
        await context_engine().dispose()
    context_session_factory.cache_clear()
    context_engine.cache_clear()
