"""Utilities for turning markdown files into structured documents."""

from __future__ import annotations

import difflib
import io
import pathlib
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import cache, lru_cache
from typing import TYPE_CHECKING, Annotated, ClassVar, Self, cast

import mdformat
from loguru import logger
from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, computed_field

from .async_path import AsyncPath
from .exceptions import SectionNotFoundError, UserError
from .helpers.files import atomic_write_text, vault_write_lock
from .settings import SETTINGS
from .yaml import YAML_LOADER, FrontmatterValue

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Sequence

    from markdown_it.token import Token


@cache
def _markdown_it() -> MarkdownIt:
    """Return the configured markdown parser."""
    return MarkdownIt("commonmark").enable(["table", "strikethrough"])


@dataclass(frozen=True, slots=True)
class _Heading:
    """A parsed heading with source position."""

    level: int
    line_no: int
    text: str


@lru_cache(maxsize=1024)
def _heading_plain_text(heading: str) -> str:
    """Return the plain-text form of a heading for format-insensitive lookups.

    Inline markdown markup (``**bold**``, ``_italic_``, ``` `code` ```,
    ``~~strike~~``, ``[link](url)``, ...) is stripped so that
    :meth:`MarkdownDocument.get_section` can match a section regardless of how its
    heading is decorated in the source. The cached result means repeated lookups
    over the same headings are O(1) after the first parse.

    Args:
        heading: The raw heading text as stored on a :class:`MarkdownSection`.

    Returns:
        The visible text of the heading with surrounding whitespace stripped.
    """
    parts: list[str] = []

    def _collect(tokens: Iterable[Token]) -> None:
        for token in tokens:
            if token.type in {"text", "code_inline"}:
                parts.append(token.content)
            elif token.children:
                _collect(token.children)

    _collect(_markdown_it().parseInline(heading))
    return "".join(parts).strip()


def _parse_frontmatter(text: str) -> tuple[dict[str, FrontmatterValue], str]:
    """Split Obsidian-style frontmatter from the markdown body.

    The YAML block is loaded through ``YAML_LOADER`` (round-trip mode) so types,
    quote styles, key order, and comments are preserved for the eventual dump.

    Returns:
        Parsed frontmatter as a ``CommentedMap`` and the remaining markdown body.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, text

    try:
        closing_line = lines[1:].index("---") + 1
    except ValueError:
        return {}, text

    yaml_text = "\n".join(lines[1:closing_line])
    loaded: dict[str, FrontmatterValue] = (
        YAML_LOADER.load(yaml_text) or {}  # pyright: ignore[reportUnknownMemberType]
    )
    body_text = "\n".join(lines[closing_line + 1 :])
    return loaded, body_text


def markdown_body(text: str) -> str:
    """Return markdown body text with Obsidian-style YAML frontmatter removed."""
    _, body = _parse_frontmatter(text)
    return body


_H1_HEADING_PATTERN = re.compile(r"^\s*#(?:[ \t]+)(.*)$")


def note_title_from_markdown(text: str) -> str | None:
    """Extract the first level-1 heading from markdown text, skipping YAML frontmatter.

    Returns:
        The text of the first H1 heading (without the ``#`` prefix), or ``None`` if no
        heading is found.
    """
    for line in markdown_body(text).splitlines():
        if match := _H1_HEADING_PATTERN.match(line):
            return match.group(1).strip()

    return None


def _extract_headings(
    tokens: Sequence[Token],
    lines: Sequence[str],
) -> list[_Heading]:
    """Extract markdown headings from a token stream.

    The heading text is sliced directly from the source line rather than walking
    the parsed inline tokens, so inline formatting (``**bold**``, ``*italic*``,
    ``[links](url)``, etc.) is preserved verbatim.

    Returns:
        Headings in document order with raw text and zero-based source lines.
    """
    headings: list[_Heading] = []
    for token in tokens:
        if token.type != "heading_open" or not token.tag.startswith("h"):
            continue
        if not token.map:
            continue

        # Heading source lines are ``#... text``. Strip the leading marker run plus
        # the single separator space; any trailing whitespace is also dropped.
        raw = lines[token.map[0]].lstrip("#").lstrip(" \t").rstrip()
        headings.append(
            _Heading(
                level=int(token.tag.removeprefix("h")),
                line_no=token.map[0],
                text=raw,
            ),
        )
    return headings


def _render_text(text: str) -> str:
    """Normalize raw markdown into a canonical form.

    Preserves the formatting of YAML frontmatter while standardizing body formatting,
    enabling equivalent documents to compare equal regardless of whitespace
    differences.

    Args:
        text: Raw markdown source, optionally including YAML frontmatter.

    Returns:
        The normalized markdown string.
    """
    fm, body_text = _parse_frontmatter(text)
    body = mdformat.text(  # pyright: ignore[reportUnknownMemberType]
        body_text,
        extensions={"gfm", "wikilink"},
    ).lstrip()
    if not fm:
        return body
    buffer = io.StringIO()
    YAML_LOADER.dump(fm, buffer)  # pyright: ignore[reportUnknownMemberType]
    return f"{buffer.getvalue()}---\n{body}"


def _section_content(lines: list[str], start_line: int, end_line: int) -> str | None:
    """Return trimmed markdown body content for a heading span."""
    content_lines = lines[start_line:end_line]
    while content_lines and not content_lines[0].strip():
        del content_lines[0]
    while content_lines and not content_lines[-1].strip():
        del content_lines[-1]

    if not content_lines:
        return None

    return "\n".join(content_lines)


class MarkdownSection(BaseModel):
    """A markdown section with nested child sections."""

    heading: str
    content: str | None = None
    sections: list[MarkdownSection] = Field(default_factory=list)
    level: Annotated[
        int,
        Field(ge=1, le=6, description="The heading level of the section."),
    ]

    def append_content(self, content: str) -> None:
        """Append content to this section.

        Args:
            content: The content to append.
        """
        self.content = (self.content or "") + "\n" + content

    def prepend_content(self, content: str) -> None:
        """Prepend content to this section.

        Args:
            content: The content to prepend.
        """
        self.content = content + "\n" + (self.content or "")

    def replace_content(self, content: str) -> None:
        """Replace this section's content.

        Args:
            content: The replacement content.
        """
        self.content = content

    def iter_sections(self) -> Generator[MarkdownSection]:
        """Yield this section followed by its nested sections in document order.

        Yields:
            The section and its nested sections.
        """
        yield self
        for section in self.sections:
            yield from section.iter_sections()

    def render(self) -> str:
        """Render the section to markdown.

        Returns:
            A markdown source string for this section and its nested sections.
            The output is valid markdown but not necessarily canonically formatted;
            :meth:`MarkdownDocument.render` runs the final document through
            ``mdformat`` to normalise spacing, table alignment, and so on.
        """
        parts: list[str] = [f"{'#' * self.level} {self.heading}"]
        if self.content is not None and self.content.strip():
            parts.append(self.content)
        parts.extend(section.render() for section in self.sections)
        return "\n\n".join(parts)


class MarkdownDocument(BaseModel):
    """A markdown document split into frontmatter and heading sections."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    _write_stack: AsyncExitStack = PrivateAttr(default_factory=AsyncExitStack)
    _frontmatter: dict[str, FrontmatterValue] = PrivateAttr(default_factory=dict)
    _body: list[MarkdownSection] = PrivateAttr(default_factory=list)
    _loaded_rendered: Annotated[str, PrivateAttr()] = ""

    vault_path: Annotated[
        AsyncPath | pathlib.PurePath,
        Field(description="The path within the vault to the markdown file."),
    ]

    initial_content: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "When ``create_if_not_exists`` is true and the file is missing, this "
                "string is written as the new file contents instead of an empty file."
            ),
        ),
    ] = None

    create_if_not_exists: Annotated[
        bool,
        Field(description="Whether to create the file if it does not exist."),
    ] = False

    read_only: Annotated[
        bool,
        Field(description="When true, skip all validation and writes on exit."),
    ] = False

    detect_external_modification: Annotated[
        bool,
        Field(
            description=(
                "When true, re-read the file before writing and raise if it was modified "
                "externally since it was loaded (optimistic concurrency guard)."
            ),
        ),
    ] = True

    @computed_field
    @property
    def frontmatter(self) -> dict[str, FrontmatterValue]:
        """Document frontmatter."""
        return self._frontmatter

    @computed_field
    @property
    def body(self) -> list[MarkdownSection]:
        """The top-level sections of the parsed document.

        Returns:
            list[MarkdownSection]: The document's root-level sections.
        """
        return self._body

    @property
    def _async_file_path(self) -> AsyncPath:
        """Compute the full absolute path to the markdown file in the vault.

        Returns:
                The full path obtained by joining the vault root path with the relative vault path.
        """
        return SETTINGS.obsidian_vault_path / self.vault_path

    async def __aenter__(self) -> Self:
        """Load the document and return it for editing.

        Returns:
            The loaded document instance.
        """
        try:
            if not self.read_only or self.create_if_not_exists:
                _ = await self._write_stack.enter_async_context(vault_write_lock())

            return await self._load()
        except BaseException:
            await self._write_stack.aclose()
            raise

    async def _load(self) -> Self:
        """Read and parse the document while holding the writer lock when needed.

        Returns:
            The loaded document instance.

        Raises:
            FileNotFoundError: If the file does not exist and creation is disabled.
        """
        try:
            text = await self._async_file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if not self.create_if_not_exists:
                raise

            text = self.initial_content if self.initial_content is not None else ""
            await atomic_write_text(self._async_file_path, text)

        self._loaded_rendered = _render_text(text)
        self._frontmatter, body_text = _parse_frontmatter(text)
        lines = body_text.splitlines()

        if not (headings := _extract_headings(_markdown_it().parse(body_text), lines)):
            self._body = []
            return self

        sections_by_heading: dict[_Heading, MarkdownSection] = {}
        roots: list[MarkdownSection] = []
        stack: list[tuple[_Heading, MarkdownSection]] = []
        for heading in headings:
            section = MarkdownSection(heading=heading.text, level=heading.level)
            sections_by_heading[heading] = section

            # The stack tracks the active heading path. Pop until the top is a
            # shallower heading, which is the parent of this section.
            while stack and stack[-1][0].level >= heading.level:
                _ = stack.pop()

            # If a parent remains, nest under it; otherwise this is a top-level
            # section in the document body.
            if stack:
                stack[-1][1].sections.append(section)
            else:
                roots.append(section)

            # This section may become the parent for later, deeper headings.
            stack.append((heading, section))

        for idx, heading in enumerate(headings):
            next_heading_line = (
                headings[idx + 1].line_no if idx + 1 < len(headings) else len(lines)
            )
            section = sections_by_heading[heading]
            section.content = _section_content(
                lines,
                start_line=heading.line_no + 1,
                end_line=next_heading_line,
            )
            if section.content is None and section.sections:
                section.content = ""

        self._body = roots
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: object,
    ) -> None:
        """Flush successful edits and clear loaded state.

        Args:
            exc_type: Exception type from the context manager, if any.
            _exc_value: Exception value from the context manager, if any.
            _traceback: Exception traceback from the context manager, if any.
        """
        try:
            if exc_type is None and not self.read_only:
                await self._save()
        finally:
            await self._write_stack.aclose()

    async def _save(self) -> None:
        """Validate external changes and flush edits while holding the writer lock.

        Raises:
            ValueError: If the file was modified externally since it was loaded and
                ``detect_external_modification`` is enabled.
        """
        if self.detect_external_modification:
            current_text = await self._async_file_path.read_text(encoding="utf-8")
            current_normalized = _render_text(current_text)
            if current_normalized != self._loaded_rendered:
                diff = "".join(
                    difflib.unified_diff(
                        self._loaded_rendered.splitlines(keepends=True),
                        current_normalized.splitlines(keepends=True),
                        fromfile="on_disk_at_load",
                        tofile="on_disk_now",
                    ),
                )
                logger.debug("External modification detected:\n{}", diff)
                msg = "File was modified externally since it was loaded."
                raise ValueError(msg)

        await atomic_write_text(self._async_file_path, self.render())

    def get_section(
        self,
        heading_path: tuple[str, ...],
        *,
        create_if_not_exists: bool = False,
    ) -> MarkdownSection:
        """Return the section at the given heading path, optionally creating it.

        Heading comparison is case-insensitive and format-insensitive: inline markdown markup on each
        side (``**bold**``, ``_italic_``, ``` `code` ``, links, ...) is stripped and case-folded
        before matching.

        Args:
            heading_path: Sequence of heading text components to traverse.
            create_if_not_exists: When ``True``, create any missing sections (and their \
                ancestors) rather than raising ``ValueError``.

        Returns:
            The section at the given path.

        Raises:
            UserError: If the heading path is empty.
            SectionNotFoundError: If the section is not found and ``create_if_not_exists`` is ``False``.
        """
        if not (path_parts := list(heading_path)):
            raise UserError(message="Heading path cannot be empty")

        section: MarkdownSection | None = None
        prev_heading: str | None = None
        container: list[MarkdownSection] = self.body

        while path_parts:
            heading = path_parts.pop(0)
            target = _heading_plain_text(heading).casefold()
            found = next(
                (
                    s
                    for s in container
                    if _heading_plain_text(s.heading).casefold() == target
                ),
                None,
            )

            if found is None:
                if not create_if_not_exists:
                    raise SectionNotFoundError(
                        heading,
                        prev_heading,
                        [s.heading for s in container],
                    )

                found = MarkdownSection(
                    heading=heading,
                    level=(section.level if section is not None else 0) + 1,
                )
                container.append(found)

            section = found
            container = section.sections
            prev_heading = heading

        # We know section is not None because we checked for empty heading_path above.
        return cast("MarkdownSection", section)

    def iter_sections(self) -> Generator[MarkdownSection]:
        """Yield every section in the document in document order.

        Yields:
            Each top-level section followed by its nested sections.
        """
        for section in self.body:
            yield from section.iter_sections()

    def render(self) -> str:
        """Render the document as a normalized markdown string.

        Returns:
            The full markdown document including frontmatter (if any) and body.
        """
        body = mdformat.text(  # pyright: ignore[reportUnknownMemberType]
            "\n\n".join(section.render() for section in self.body),
            extensions={"gfm", "wikilink"},
        ).lstrip()

        if not self.frontmatter:
            return body

        # ruamel.yaml's ``YAML.dump`` writes to a stream and returns ``None``; per-call
        # ``sort_keys``/``allow_unicode`` kwargs don't exist (round-trip mode preserves
        # key order, and unicode is allowed by default on the instance). Dumping into
        # an ``io.StringIO`` is the documented way to capture the output as a string.
        buffer = io.StringIO()
        YAML_LOADER.dump(self.frontmatter, buffer)  # pyright: ignore[reportUnknownMemberType]

        # ``explicit_start = True`` emits the opening ``---``; the closing delimiter for
        # Obsidian-style frontmatter is also ``---`` (not the YAML ``...`` document-end
        # marker that ``explicit_end = True`` would produce), so it's added manually.
        return f"{buffer.getvalue()}---\n{body}"
