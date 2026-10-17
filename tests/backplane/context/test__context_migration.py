"""Migration coverage for the canonical context schema."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from backplane.context.tables import ContextBase

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


def _schema(connection: Connection) -> dict[str, set[str]]:
    inspector = inspect(connection)
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


async def test__context_migration__matches_orm_metadata_and_downgrades(
    context_database_url: str,
) -> None:
    """Alembic and ORM metadata describe the same tables and columns."""
    config = Config("alembic.ini")

    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(context_database_url)
    try:
        async with engine.connect() as connection:
            migrated = await connection.run_sync(_schema)
            differences = await connection.run_sync(
                lambda connection: compare_metadata(
                    MigrationContext.configure(connection),
                    ContextBase.metadata,
                ),
            )
        expected = {
            table.name: {column.name for column in table.columns}
            for table in ContextBase.metadata.sorted_tables
        }
        assert migrated == expected
        assert differences == []

        await asyncio.to_thread(command.downgrade, config, "base")
        async with engine.connect() as connection:
            remaining = await connection.run_sync(_schema)
    finally:
        await engine.dispose()
    assert remaining == {}
