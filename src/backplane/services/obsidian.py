"""Helpers for reading and editing Obsidian markdown notes."""

from __future__ import annotations

import asyncio
import datetime as dt  # ruff:ignore[typing-only-standard-library-import]
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, ClassVar, Final, cast, final

from loguru import logger

from backplane.utils import (
    SETTINGS,
    VAULT_PATHS,
    AsyncPath,
    MarkdownDocument,
    exc,
    resolve_under_root,
    substitute_obsidian_core_date_variables,
    today,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

_OBSIDIAN_CONFIG_DIR: Final = ".obsidian"


@final
class ObsidianService:
    """Service for interacting with the Obsidian vault."""

    _move_note_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    IDEA_INBOX_PATH: Final = VAULT_PATHS.inbox_dir / "Ideas.md"

    @staticmethod
    async def _daily_note_template_source() -> str | None:
        """Load the daily note template file configured in ``.obsidian/daily-notes.json``.

        Returns:
            Raw template file contents, or ``None`` if config or template is missing.
        """
        config_path = SETTINGS.obsidian_vault_path / ".obsidian" / "daily-notes.json"
        try:
            raw = await config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

        try:
            parsed_unknown = json.loads(raw)  # pyright: ignore[reportAny]
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed_unknown, dict):
            return None

        data = cast("dict[str, object]", parsed_unknown)
        rel = data.get("template")
        if not isinstance(rel, str) or not rel:
            return None

        path_str = rel if rel.endswith(".md") else f"{rel}.md"
        template_path = SETTINGS.obsidian_vault_path / path_str
        try:
            return await template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    @asynccontextmanager
    async def daily_note(  # ruff:ignore[no-self-use]
        self,
        date: dt.date | None = None,
        *,
        create_if_not_exists: bool = False,
        read_only: bool = True,
    ) -> AsyncGenerator[MarkdownDocument]:
        """Open a daily note for editing, flushing on successful exit.

        Args:
            date: Date of the daily note. Defaults to today's local date.
            create_if_not_exists: If true, create the note when missing using the vault's
                daily note template from ``.obsidian/daily-notes.json`` when configured.
            read_only: When true, require file content unchanged on exit (no accidental writes).

        Yields:
            Loaded markdown document for the requested daily note.
        """
        date = date or today()
        vault_path = VAULT_PATHS.daily_notes_dir / f"{date.isoformat()}.md"
        full_path = SETTINGS.obsidian_vault_path / vault_path

        initial_content: str | None = None
        if (
            create_if_not_exists
            and not await full_path.exists()
            and (template := await ObsidianService._daily_note_template_source())
            is not None
        ):
            initial_content = substitute_obsidian_core_date_variables(template, date)

        async with MarkdownDocument(
            vault_path=vault_path,
            create_if_not_exists=create_if_not_exists,
            initial_content=initial_content,
            read_only=read_only,
        ) as daily_note:
            yield daily_note

    @asynccontextmanager
    async def idea_inbox(
        self,
        *,
        read_only: bool = False,
    ) -> AsyncGenerator[MarkdownDocument]:
        """Provide access to the idea inbox document for reading or editing.

        Parameters:
            read_only: If `True`, open the document in read-only mode.

        Yields:
            The loaded markdown document for the idea inbox.
        """
        async with MarkdownDocument(
            vault_path=self.IDEA_INBOX_PATH,
            read_only=read_only,
        ) as idea_inbox:
            yield idea_inbox

    @staticmethod
    def _validate_vault_note_path(path: AsyncPath) -> AsyncPath:
        """Validate a vault-relative markdown note path.

        Args:
            path: Path relative to the vault root.

        Returns:
            The validated path.

        Raises:
            UserError: If the path is empty, not a markdown file, or under `.obsidian/`.
        """
        if not path.parts:
            msg = "Note path must not be empty."
            raise exc.UserError(message=msg)

        if path.suffix != ".md":
            msg = f"Note path must be a markdown file ending in .md: {path!s}"
            raise exc.UserError(message=msg)

        if path.parts[0] == _OBSIDIAN_CONFIG_DIR:
            msg = f"Paths under .obsidian/ are not allowed: {path!s}"
            raise exc.UserError(message=msg)

        return path

    @staticmethod
    async def move_note(
        source_path: AsyncPath,
        destination_path: AsyncPath,
    ) -> AsyncPath:
        """Move a vault note to a new vault-relative path.

        Creates missing destination parent directories. Removes the source note's
        immediate parent directory when it becomes empty after the move.

        Args:
            source_path: Vault-relative path to the note to move.
            destination_path: Vault-relative destination path for the note.

        Returns:
            Vault-relative path to the moved note.

        Raises:
            UserError: If either path is invalid or escapes the vault.
            NotFoundError: If the source note does not exist.
            ConflictError: If the destination note already exists.
        """
        source_rel = ObsidianService._validate_vault_note_path(source_path)
        destination_rel = ObsidianService._validate_vault_note_path(destination_path)

        try:
            source_abs = await resolve_under_root(source_rel)
            destination_abs = await resolve_under_root(destination_rel)
        except ValueError as err:
            raise exc.UserError(message=str(err)) from err

        if not await source_abs.is_file():
            msg = f"Note not found: {source_rel!s}"
            raise exc.NotFoundError(message=msg)

        source_parent = source_abs.parent
        vault_root = await SETTINGS.obsidian_vault_path.resolve()

        async with ObsidianService._move_note_lock:
            if await destination_abs.exists():
                msg = f"Destination already exists: {destination_rel!s}"
                raise exc.ConflictError(message=msg)

            await destination_abs.parent.mkdir(parents=True, exist_ok=True)
            _ = await source_abs.rename(destination_abs)

        if source_parent != vault_root and await source_parent.is_dir():
            empty = True
            async for _ in source_parent.iterdir():
                empty = False
                break
            if empty:
                await source_parent.rmdir()
                logger.debug("Removed empty directory after move: {}", source_parent)

        logger.info("Moved note from {} to {}", source_rel, destination_rel)
        return AsyncPath(*destination_rel.parts)
