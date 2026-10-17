"""Shared PostgreSQL fixtures for Backplane context persistence tests."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from backplane.services.context_capture import ContextCaptureService
from backplane.utils import SETTINGS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture(scope="session")
def context_postgres() -> Iterator[PostgresContainer]:
    """Reuse PostgreSQL 17 for all database tests within each pytest worker.

    Yields:
        A disposable server matching the deployed PostgreSQL major version.
    """
    with PostgresContainer(
        "postgres:17",
        username="test",
        password="test",  # ruff:ignore[hardcoded-password-func-arg] -- Disposable container credentials, never a live service.
        dbname="postgres",
        driver="asyncpg",
    ) as postgres:
        yield postgres


@pytest.fixture
async def context_database_url(
    context_postgres: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[str]:
    """Create an isolated database without wrapping tests in a shared transaction.

    Yields:
        Async PostgreSQL URL for an empty database.
    """
    server_url = make_url(context_postgres.get_connection_url())
    database_name = f"context_test_{uuid.uuid4().hex}"
    database_url = server_url.set(database=database_name).render_as_string(
        hide_password=False,
    )
    admin = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    monkeypatch.setattr(SETTINGS, "context_database_url", SecretStr(database_url))

    try:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        try:
            yield database_url
        finally:
            async with admin.connect() as connection:
                await connection.exec_driver_sql(
                    f'DROP DATABASE "{database_name}" WITH (FORCE)',
                )
    finally:
        await admin.dispose()


@pytest.fixture
async def context_engine(context_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Apply production migrations and provide independent pooled connections.

    Yields:
        Initialized async database engine.
    """
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    engine = create_async_engine(context_database_url)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def context_session_factory(
    context_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Provide independent sessions and transactions for the isolated database.

    Returns:
        Async session factory bound to the engine, never a shared connection.
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
