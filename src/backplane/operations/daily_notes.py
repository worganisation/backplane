"""Shared daily-note and idea-capture operations."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from backplane.services.ideas import IdeaService
from backplane.services.obsidian import ObsidianService
from backplane.utils import (
    SETTINGS,
    VAULT_PATHS,
    MarkdownDocument,
    exc,
    format_human_date,
    resolve_under_root,
    today,
)
from backplane.utils.helpers.files import vault_write_lock

if TYPE_CHECKING:
    from backplane.services.vault_entities import UpdateMode


async def record_diary(
    content: str,
    date: dt.date | None = None,
    *,
    idempotency_key: str | None = None,
) -> str:
    """Append a timestamped diary entry and its retry receipt in one atomic note write.

    Returns:
        The original saved date, including for retries after midnight.

    Raises:
        BadRequestError: The content or supplied key is blank.
        ConflictError: A key is reused with different input.
    """  # ruff: ignore[docstring-extraneous-exception] -- The receipt lookup raises conflicts.
    if not content.strip() or (
        idempotency_key is not None and not idempotency_key.strip()
    ):
        message = "Diary content and any idempotency key must not be blank."
        raise exc.BadRequestError(message)

    key = (
        hashlib.sha256(idempotency_key.encode()).hexdigest()
        if idempotency_key is not None
        else None
    )
    fingerprint = hashlib.sha256(
        json.dumps([content, date.isoformat() if date else None]).encode(),
    ).hexdigest()
    captured_at = dt.datetime.now(SETTINGS.local_timezone)
    resolved_date = date or captured_at.date()

    async with vault_write_lock():
        if key is not None and (saved_date := await _saved_diary_date(key, fingerprint)):
            return f"Diary entry saved to {saved_date}."

        async with ObsidianService().daily_note(
            date=resolved_date,
            create_if_not_exists=True,
            read_only=False,
        ) as note:
            section = note.get_section(
                (format_human_date(resolved_date), "Diary"),
                create_if_not_exists=True,
            )
            section.append_content(
                f"Recorded {captured_at:%Y-%m-%d %H:%M %z} — {content}",
            )
            if key is not None:
                receipts = _diary_receipts(note)
                receipts[key] = fingerprint
                note.frontmatter["backplane_diary_captures"] = json.dumps(receipts)

    return f"Diary entry saved to {resolved_date.isoformat()}."


def _diary_receipts(note: MarkdownDocument) -> dict[str, str]:
    """Read durable retry receipts stored alongside the diary text.

    Returns:
        Operation-key digests mapped to original request fingerprints.
    """
    raw = note.frontmatter.get("backplane_diary_captures", "{}")
    return TypeAdapter(dict[str, str]).validate_json(str(raw))


async def _saved_diary_date(key: str, fingerprint: str) -> str | None:
    """Find a receipt across dates while holding the vault lock.

    Returns:
        The saved note date, or None for a new operation.

    Raises:
        ConflictError: The key belongs to a different request.
    """
    directory = await resolve_under_root(VAULT_PATHS.daily_notes_dir)
    if not await directory.is_dir():
        return None

    async for path in directory.iterdir():
        if path.suffix != ".md" or not await path.is_file():
            continue

        async with MarkdownDocument(
            vault_path=VAULT_PATHS.daily_notes_dir / path.name,
            read_only=True,
        ) as note:
            receipts = _diary_receipts(note)
        if key not in receipts:
            continue

        if receipts[key] != fingerprint:
            message = "Idempotency key already used with different diary input."
            raise exc.ConflictError(message)
        return path.stem

    return None


async def read_daily_note(date: dt.date | None = None) -> str:
    """Read and render a daily note.

    Returns:
        Rendered Markdown for the requested daily note.

    Raises:
        NotFoundError: If the requested daily note does not exist.
    """
    resolved_date = date or today()
    try:
        async with ObsidianService().daily_note(
            date=resolved_date,
            read_only=True,
        ) as daily_note:
            return daily_note.render()
    except FileNotFoundError as error:
        raise exc.NotFoundError(
            message=f"Daily note for {resolved_date.isoformat()} not found.",
            detail={"date": resolved_date.isoformat()},
        ) from error


async def update_daily_note_section(
    *,
    heading_path: tuple[str, ...],
    content: str,
    mode: UpdateMode = "append",
    create_section_if_not_exists: bool = False,
    date: dt.date | None = None,
) -> str:
    """Update and render a section in a daily note.

    Returns:
        Rendered Markdown for the updated section.

    Raises:
        InformationRequiredError: If the requested section is missing and creation was not requested.
    """
    resolved_date = date or today()
    resolved_heading_path = heading_path
    if resolved_heading_path[0] != (
        top_level_heading := format_human_date(resolved_date)
    ):
        resolved_heading_path = (top_level_heading, *resolved_heading_path)

    async with ObsidianService().daily_note(
        date=resolved_date,
        create_if_not_exists=True,
        read_only=False,
    ) as daily_note:
        try:
            section = daily_note.get_section(
                resolved_heading_path,
                create_if_not_exists=create_section_if_not_exists,
            )
        except exc.SectionNotFoundError as error:
            raise exc.InformationRequiredError(
                message=(
                    f"{error} Retry with an existing section, or set "
                    "`create_section_if_not_exists=true` to create it."
                ),
                detail=error.detail,
            ) from error

        if not section.content or mode == "replace":
            section.replace_content(content)
        elif mode == "append":
            section.append_content(content)
        else:
            section.prepend_content(content)

    return section.render()


async def record_idea(idea: str, *, idempotency_key: str | None = None) -> str:
    """Record an idea in the timestamped idea inbox.

    Returns:
        Confirmation message for the capture.
    """
    capture = await IdeaService.record(idea, idempotency_key=idempotency_key)
    return f"Idea recorded successfully. ID: {capture.id}"
