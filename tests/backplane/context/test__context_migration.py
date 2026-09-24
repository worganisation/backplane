"""Migration coverage for the canonical context schema."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from backplane.context.tables import ContextBase
from backplane.utils import SETTINGS

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from sqlalchemy.engine import Connection


def _schema(connection: Connection) -> dict[str, set[str]]:
    inspector = inspect(connection)
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


async def test__context_migration__matches_orm_metadata_and_downgrades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alembic and ORM metadata describe the same tables and columns."""
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setattr(SETTINGS, "context_database_url", SecretStr(database_url))
    config = Config("alembic.ini")

    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        migrated = await connection.run_sync(_schema)
    expected = {
        table.name: {column.name for column in table.columns}
        for table in ContextBase.metadata.sorted_tables
    }
    assert migrated == expected

    await asyncio.to_thread(command.downgrade, config, "base")
    async with engine.connect() as connection:
        remaining = await connection.run_sync(_schema)
    await engine.dispose()
    assert remaining == {}
