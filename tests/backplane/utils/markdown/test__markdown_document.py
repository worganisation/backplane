"""Tests for MarkdownDocument vault I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backplane.utils.async_path import AsyncPath

import pathlib

import pytest

from backplane.utils.markdown import MarkdownDocument


async def test__markdown_document__creates_missing_file_on_enter(
    obsidian_vault: AsyncPath,
) -> None:
    """A missing note is created with atomic_write_text during __aenter__."""
    rel = pathlib.PurePath("Daily/2026-05-20.md")
    target = obsidian_vault / rel
    assert not await target.exists()

    async with MarkdownDocument(
        vault_path=rel,
        create_if_not_exists=True,
        initial_content="## Tasks\n\n",
        detect_external_modification=False,
    ) as doc:
        assert doc.get_section(("Tasks",)).heading == "Tasks"

    assert await target.exists()
    assert "## Tasks" in await target.read_text(encoding="utf-8")


async def test__markdown_document__creates_empty_file_without_initial_content(
    obsidian_vault: AsyncPath,
) -> None:
    """create_if_not_exists with no initial_content writes an empty file."""
    rel = pathlib.PurePath("empty.md")
    target = obsidian_vault / rel

    async with MarkdownDocument(
        vault_path=rel,
        create_if_not_exists=True,
        detect_external_modification=False,
    ):
        pass

    assert await target.exists()
    assert not await target.read_text(encoding="utf-8")


async def test__markdown_document__persists_edits_on_exit(
    obsidian_vault: AsyncPath,
) -> None:
    """Successful edits are flushed with atomic_write_text on __aexit__."""
    rel = pathlib.PurePath("note.md")
    target = obsidian_vault / rel
    _ = await target.write_text("## Ideas\n\nfirst thought\n", encoding="utf-8")

    async with MarkdownDocument(
        vault_path=rel,
        detect_external_modification=False,
    ) as doc:
        doc.get_section(("Ideas",)).append_content("second thought")

    text = await target.read_text(encoding="utf-8")
    assert "second thought" in text


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        "Introductory prose.\n\n- A leading list item\n",
        "Introductory prose.\n\n# Note\n\n## Tasks\n\nExisting task.\n",
        '---\nstatus: "active"\n---\nIntroductory prose.\n',
        (
            '---\nstatus: "active"\n---\n'
            "Introductory prose.\n\n```markdown\n# A fenced heading\n```\n\n"
            "# Note\n\n## Tasks\n\nExisting task.\n"
        ),
        "```markdown\n# A fenced heading\n```\n",
    ],
)
async def test__markdown_document__preserves_preamble_on_render_and_save(
    obsidian_vault: AsyncPath,
    source: str,
    *,
    read_only: bool,
) -> None:
    """Leading body content survives read-only rendering and a save without edits."""
    rel = pathlib.PurePath("note.md")
    target = obsidian_vault / rel
    _ = await target.write_text(source, encoding="utf-8")

    async with MarkdownDocument(vault_path=rel, read_only=read_only) as doc:
        assert doc.render() == source

    assert await target.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("existing_section", [False, True])
async def test__markdown_document__preserves_preamble_when_editing_sections(
    obsidian_vault: AsyncPath,
    *,
    existing_section: bool,
) -> None:
    """Editing or creating a section retains frontmatter and preceding prose."""
    rel = pathlib.PurePath("note.md")
    target = obsidian_vault / rel
    preamble = '---\nstatus: "active"\n---\nIntroductory prose.\n'
    sections = "\n# Note\n\n## Tasks\n\nExisting task.\n" if existing_section else ""
    _ = await target.write_text(preamble + sections, encoding="utf-8")

    async with MarkdownDocument(vault_path=rel) as doc:
        doc.get_section(("Note", "Tasks"), create_if_not_exists=True).append_content(
            "New task.",
        )

    expected_content = "Existing task.\nNew task." if existing_section else "New task."
    expected = preamble + "\n# Note\n\n## Tasks\n\n" + expected_content + "\n"
    assert await target.read_text(encoding="utf-8") == expected
