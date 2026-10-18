"""Distinct idea captures and compatibility with grouped timestamp inbox entries."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Final, Literal, final
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel

from backplane.services.obsidian import ObsidianService
from backplane.utils import (
    SETTINGS,
    VAULT_PATHS,
    YAML_LOADER,
    AsyncPath,
    MarkdownDocument,
    atomic_write_text,
    exc,
    resolve_under_root,
    today,
)
from backplane.utils.helpers.files import vault_write_lock

MAX_IDEA_PAGE_SIZE: Final = 100
IDEA_NOTES_DIR: Final = VAULT_PATHS.inbox_dir / "Ideas"


@dataclass(frozen=True, slots=True)
class Capture:
    """An individual idea or a legacy group of ideas recorded in one minute."""

    id: str
    date: str
    time: str
    text: str
    path: AsyncPath
    kind: Literal["idea", "legacy_group"] = "legacy_group"


class IdeaCapture(BaseModel, frozen=True):
    """Retrievable capture with its original text and provenance."""

    id: str
    date: str
    time: str
    text: str
    path: AsyncPath
    kind: Literal["idea", "legacy_group"]


def parse_inbox(doc: MarkdownDocument, days: int | None = 30) -> list[Capture]:
    """Parse legacy date/minute groups without inventing individual identities.

    Returns:
        Nonempty legacy groups in document order within the lookback window.
    """
    cutoff = today() - dt.timedelta(days=days) if days is not None else None
    captures: list[Capture] = []

    for date_section in doc.body:
        try:
            section_date = dt.date.fromisoformat(date_section.heading)
        except ValueError:
            continue

        if cutoff is not None and section_date < cutoff:
            continue

        for time_section in date_section.sections:
            text = "\n\n".join([
                time_section.content or "",
                *(section.render() for section in time_section.sections),
            ])
            capture_text = "\n".join(
                line.rstrip()
                for line in text.strip().splitlines()
                if not (
                    (normalized := line.strip().replace("\\", "")).startswith("↗ [[")
                    and normalized.endswith("]]")
                )
            ).strip()
            if capture_text:
                captures.append(
                    Capture(
                        id=f"{date_section.heading}T{time_section.heading}",
                        date=date_section.heading,
                        time=time_section.heading,
                        text=capture_text,
                        path=ObsidianService.IDEA_INBOX_PATH,
                    ),
                )

    return captures


def _payload(capture: Capture) -> IdeaCapture:
    """Project a stored capture for transport responses.

    Returns:
        A public capture representation.
    """
    return IdeaCapture(
        id=capture.id,
        date=capture.date,
        time=capture.time,
        text=capture.text,
        path=capture.path,
        kind=capture.kind,
    )


@final
class IdeaService:
    """Record immutable idea notes and retrieve both distinct and legacy captures."""

    @staticmethod
    async def record(idea: str, *, idempotency_key: str | None = None) -> IdeaCapture:
        """Store original capture text under a collision-resistant identity.

        Returns:
            The recorded individual idea.

        Raises:
            BadRequestError: The idea or supplied key is blank.
            ConflictError: A key is reused with different text.
        """
        if not idea.strip() or (
            idempotency_key is not None and not idempotency_key.strip()
        ):
            message = "Idea and any idempotency key must not be blank."
            raise exc.BadRequestError(message)

        identity = (
            uuid5(NAMESPACE_URL, "backplane:idea:" + idempotency_key)
            if idempotency_key is not None
            else uuid4()
        )
        capture_id = f"idea-{identity}"
        path = IDEA_NOTES_DIR / f"{capture_id}.md"
        fingerprint = hashlib.sha256(idea.encode()).hexdigest()
        async with vault_write_lock():
            resolved = await resolve_under_root(path)
            if await resolved.exists():
                raw = await resolved.read_text(encoding="utf-8")
                header, _, _text = raw.partition("\n---\n")
                if f"fingerprint: {fingerprint}" not in header.splitlines():
                    message = "Idempotency key already used with different idea input."
                    raise exc.ConflictError(message)
                return await IdeaService.get_idea(capture_id)

            now = dt.datetime.now(tz=SETTINGS.local_timezone)
            header = (
                f"---\nid: {capture_id}\ncreated: {now.isoformat()}\n"
                f"fingerprint: {fingerprint}\n---\n"
            )
            await atomic_write_text(resolved, header + idea)

        return IdeaCapture(
            id=capture_id,
            date=now.date().isoformat(),
            time=now.time().isoformat(),
            text=idea,
            path=path,
            kind="idea",
        )

    @staticmethod
    async def load_captures(*, days: int | None = None) -> list[Capture]:
        """Load individual ideas and legacy groups for retrieval and task linking.

        Returns:
            Captures in chronological order; absent inboxes produce an empty list.

        Raises:
            UserError: If an individual capture has invalid metadata.
        """
        captures: list[Capture] = []
        try:
            async with ObsidianService().idea_inbox(read_only=True) as inbox:
                captures.extend(parse_inbox(inbox, days=days))
        except FileNotFoundError:
            pass

        cutoff = today() - dt.timedelta(days=days) if days is not None else None
        directory = await resolve_under_root(IDEA_NOTES_DIR)
        if await directory.is_dir():
            async for path in directory.iterdir():
                if path.suffix != ".md" or not await path.is_file():
                    continue

                async with await path.open(encoding="utf-8", newline="") as note:
                    raw = await note.read()
                header, separator, text = raw.partition("\n---\n")
                frontmatter: dict[str, object] = (
                    YAML_LOADER.load(header.removeprefix("---\n")) or {}  # pyright: ignore[reportUnknownMemberType]
                )
                created_value = frontmatter.get("created")
                if (
                    not separator
                    or frontmatter.get("id") != path.stem
                    or created_value is None
                ):
                    raise exc.UserError(
                        message=f"Invalid idea capture metadata: {path.name}",
                    )

                try:
                    created = dt.datetime.fromisoformat(str(created_value))
                except ValueError as error:
                    raise exc.UserError(
                        message=f"Invalid idea capture timestamp: {path.name}",
                    ) from error

                if cutoff is not None and created.date() < cutoff:
                    continue

                captures.append(
                    Capture(
                        id=path.stem,
                        date=created.date().isoformat(),
                        time=created.time().isoformat(),
                        text=text,
                        path=IDEA_NOTES_DIR / path.name,
                        kind="idea",
                    ),
                )

        return sorted(
            captures,
            key=lambda capture: (capture.date, capture.time, capture.id),
        )

    @staticmethod
    async def list_ideas(*, limit: int = 20, offset: int = 0) -> list[IdeaCapture]:
        """List newest captures first with bounded pagination.

        Returns:
            A page of individual ideas and explicitly identified legacy groups.

        Raises:
            UserError: If pagination is outside the supported bounds.
        """
        if not 1 <= limit <= MAX_IDEA_PAGE_SIZE or offset < 0:
            raise exc.UserError(message="Use limit 1-100 and a nonnegative offset.")

        captures = list(reversed(await IdeaService.load_captures()))
        return [_payload(capture) for capture in captures[offset : offset + limit]]

    @staticmethod
    async def get_idea(capture_id: str) -> IdeaCapture:
        """Read a capture by its stable ID, including legacy date/minute IDs.

        Returns:
            The matching capture and its original text.

        Raises:
            NotFoundError: If no capture has the requested identity.
        """
        for capture in await IdeaService.load_captures():
            if capture.id == capture_id:
                return _payload(capture)

        raise exc.NotFoundError(
            message=f"Capture {capture_id!r} not found.",
            detail={"resource": "capture", "id": capture_id},
        )
