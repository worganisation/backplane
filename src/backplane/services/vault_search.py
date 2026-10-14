"""Vault note search across entity, task, and daily-note directories."""

from __future__ import annotations

import pathlib
import re
from typing import TYPE_CHECKING, Final, Literal, final

from loguru import logger
from pydantic import BaseModel, computed_field
from rapidfuzz import fuzz

from backplane.services.ideas import IDEA_NOTES_DIR
from backplane.services.obsidian import ObsidianService
from backplane.utils import VAULT_PATHS, AsyncPath, build_obsidian_link, safe_slug
from backplane.utils.enums import VaultEntityKind
from backplane.utils.helpers.files import resolve_under_root
from backplane.utils.markdown import markdown_body, note_title_from_markdown
from backplane.utils.settings import SETTINGS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

VaultSearchKind = Literal[
    "domain",
    "person",
    "project",
    "resource",
    "task",
    "daily_note",
    "idea",
]

_ALL_KINDS: Final[frozenset[VaultSearchKind]] = frozenset(
    {"domain", "person", "project", "resource", "task", "daily_note", "idea"},
)

_EXCLUDED_BOARD_NAMES: Final = frozenset(
    {
        VAULT_PATHS.project_board_path.name,
        VAULT_PATHS.task_board_path.name,
    },
)

_FUZZY_TITLE_THRESHOLD: Final = 70.0
_EXACT_TITLE_SCORE: Final = 100.0
_EXACT_FILENAME_SCORE: Final = 95.0
_SUBSTRING_TITLE_SCORE: Final = 80.0
_CONTENT_BASE_SCORE: Final = 80.0
_CONTENT_OCCURRENCE_BONUS: Final = 5.0
_CONTENT_MAX_OCCURRENCE_BONUS: Final = 20.0
_DEFAULT_EXCERPT_CHARS: Final = 120


class VaultNoteSearchHit(BaseModel, frozen=True):
    """A ranked vault note search result."""

    kind: VaultSearchKind
    title: str
    path: AsyncPath
    score: float
    excerpt: str | None = None

    @computed_field
    @property
    def canonical_link(self) -> str:
        """Obsidian wikilink for the matched note."""
        return build_obsidian_link(self.path)


def _fuzzy_score(query: str, text: str) -> float:
    """Return a conservative fuzzy score between query and text."""
    return max(fuzz.token_set_ratio(query, text), fuzz.partial_ratio(query, text))


def _resolve_kinds(kinds: list[VaultSearchKind] | None) -> frozenset[VaultSearchKind]:
    if kinds is None:
        return _ALL_KINDS
    return frozenset(kinds)


def _directory_for_kind(kind: VaultSearchKind) -> AsyncPath:
    if kind == "idea":
        return IDEA_NOTES_DIR
    if kind == "task":
        return VAULT_PATHS.task_notes_dir
    if kind == "daily_note":
        return VAULT_PATHS.daily_notes_dir
    return VaultEntityKind(kind).vault_dir


def _vault_relative_path(path: AsyncPath) -> AsyncPath:
    root_resolved = pathlib.Path(SETTINGS.obsidian_vault_path.as_posix()).resolve()
    path_resolved = pathlib.Path(path.as_posix())
    return AsyncPath(path_resolved.relative_to(root_resolved).as_posix())


def _note_title(text: str, *, filename_stem: str) -> str:
    if title := note_title_from_markdown(text):
        return title
    return filename_stem


def _title_find_score(
    query: str,
    *,
    title: str,
    filename_stem: str,
) -> float | None:
    query_folded = query.casefold()
    title_folded = title.casefold()
    stem_folded = filename_stem.casefold()
    slug_folded = safe_slug(title).casefold()
    query_slug_folded = safe_slug(query).casefold()

    if title_folded == query_folded:
        return _EXACT_TITLE_SCORE

    if stem_folded == query_folded or slug_folded == query_slug_folded:
        return _EXACT_FILENAME_SCORE

    if query_folded in title_folded:
        return _SUBSTRING_TITLE_SCORE

    if title_folded in query_folded and title_folded != query_folded:
        return None

    fuzzy = _fuzzy_score(query, title)
    if fuzzy >= _FUZZY_TITLE_THRESHOLD:
        return fuzzy

    return None


def _build_excerpt(body: str, query: str, *, max_chars: int) -> str:
    lower_body = body.casefold()
    lower_query = query.casefold()
    idx = lower_body.find(lower_query)
    if idx < 0:
        return ""

    half = max_chars // 2
    start = max(0, idx - half)
    end = min(len(body), idx + len(query) + half)
    excerpt = " ".join(body[start:end].split())
    if start > 0:
        excerpt = f"…{excerpt}"
    if end < len(body):
        excerpt = f"{excerpt}…"
    return excerpt


def _content_find_score(body: str, query: str) -> tuple[float, str] | None:
    lower_body = body.casefold()
    lower_query = query.casefold()
    if lower_query not in lower_body:
        return None

    occurrences = len(re.findall(re.escape(lower_query), lower_body))
    bonus = min(
        (occurrences - 1) * _CONTENT_OCCURRENCE_BONUS,
        _CONTENT_MAX_OCCURRENCE_BONUS,
    )
    return _CONTENT_BASE_SCORE + bonus, _build_excerpt(
        body,
        query,
        max_chars=_DEFAULT_EXCERPT_CHARS,
    )


async def _iter_searchable_notes(
    *,
    kinds: frozenset[VaultSearchKind],
) -> AsyncIterator[tuple[VaultSearchKind, AsyncPath, str, str]]:
    """Yield searchable notes as (kind, vault_rel_path, title, raw_text)."""
    if "idea" in kinds:
        inbox_path = await resolve_under_root(ObsidianService.IDEA_INBOX_PATH)
        if await inbox_path.is_file():
            text = await inbox_path.read_text(encoding="utf-8")
            yield "idea", ObsidianService.IDEA_INBOX_PATH, "Ideas (legacy groups)", text

    for kind in sorted(kinds):
        directory = await resolve_under_root(_directory_for_kind(kind))
        if not await directory.is_dir():
            continue

        async for entry in directory.iterdir():
            if entry.suffix != ".md" or not await entry.is_file():
                continue
            if entry.name in _EXCLUDED_BOARD_NAMES:
                continue

            try:
                text = await entry.read_text(encoding="utf-8")
                rel_path = _vault_relative_path(AsyncPath(entry.as_posix()))
            except (UnicodeDecodeError, OSError) as exc:
                logger.warning("Skipping unreadable vault note {}: {}", entry, exc)
                continue

            title = _note_title(text, filename_stem=entry.stem)
            yield kind, rel_path, title, text


@final
class VaultSearchService:
    """Service for discovering vault notes by title or content."""

    @staticmethod
    async def find_notes_by_title(
        query: str,
        *,
        kinds: list[VaultSearchKind] | None = None,
        limit: int = 20,
    ) -> list[VaultNoteSearchHit]:
        """Find notes whose title or filename matches a query.

        Args:
            query: Approximate note name to match.
            kinds: Optional note kinds to search; defaults to all searchable kinds.
            limit: Maximum number of hits to return.

        Returns:
            Ranked search hits sorted by descending score.
        """
        resolved_kinds = _resolve_kinds(kinds)
        hits: list[VaultNoteSearchHit] = []
        seen_paths: set[AsyncPath] = set()

        async for kind, rel_path, title, _text in _iter_searchable_notes(
            kinds=resolved_kinds,
        ):
            if rel_path in seen_paths:
                continue

            filename_stem = rel_path.stem
            if (
                score := _title_find_score(
                    query,
                    title=title,
                    filename_stem=filename_stem,
                )
            ) is None:
                continue

            seen_paths.add(rel_path)
            hits.append(
                VaultNoteSearchHit(
                    kind=kind,
                    title=title,
                    path=rel_path,
                    score=score,
                ),
            )

        hits.sort(key=lambda hit: (-hit.score, hit.title.casefold()))
        return hits[:limit]

    @staticmethod
    async def search_note_contents(
        query: str,
        *,
        kinds: list[VaultSearchKind] | None = None,
        limit: int = 20,
        excerpt_chars: int = _DEFAULT_EXCERPT_CHARS,
    ) -> list[VaultNoteSearchHit]:
        """Find notes whose body contains a query phrase.

        Args:
            query: Topic or phrase to match in note content.
            kinds: Optional note kinds to search; defaults to all searchable kinds.
            limit: Maximum number of hits to return.
            excerpt_chars: Approximate excerpt length around the first match.

        Returns:
            Ranked search hits with excerpts, sorted by descending score.
        """
        hits: list[VaultNoteSearchHit] = []

        async for kind, rel_path, title, text in _iter_searchable_notes(
            kinds=_resolve_kinds(kinds),
        ):
            body = markdown_body(text)
            match = _content_find_score(body, query)
            if match is None:
                continue

            score, excerpt = match
            if excerpt_chars != _DEFAULT_EXCERPT_CHARS:
                excerpt = _build_excerpt(body, query, max_chars=excerpt_chars)

            hits.append(
                VaultNoteSearchHit(
                    kind=kind,
                    title=title,
                    path=rel_path,
                    score=score,
                    excerpt=excerpt,
                ),
            )

        hits.sort(key=lambda hit: (-hit.score, hit.title.casefold()))
        return hits[:limit]
