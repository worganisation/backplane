"""Shared fixtures for Backplane context persistence tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backplane.context.tables import ContextBase
from backplane.services.context_capture import ContextCaptureService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def context_engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Provide a file-backed SQLite context database.

    Yields:
        Initialized async database engine.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'context.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(ContextBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def context_session_factory(
    context_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Provide sessions for the isolated context database.

    Returns:
        Async session factory.
    """
    return async_sessionmaker(context_engine, expire_on_commit=False)


@pytest.fixture
def context_service(
    context_session_factory: async_sessionmaker[AsyncSession],
) -> ContextCaptureService:
    """Provide the canonical service over an isolated database.

    Returns:
        Context-capture service.
    """
    return ContextCaptureService(context_session_factory)
