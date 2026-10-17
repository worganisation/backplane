"""Daily-note template discovery and new-note initialization tests."""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING

import pytest

from backplane.operations.daily_notes import update_daily_note_section
from backplane.services.obsidian import ObsidianService
from backplane.utils import VAULT_PATHS, exc, format_human_date
from backplane.utils.helpers.files import atomic_write_text

if TYPE_CHECKING:
    from backplane.utils.async_path import AsyncPath

DATE = dt.date(2026, 5, 20)
TEMPLATE = "---\ndate: '{{date}}'\n---\n# {{date:dddd, MMMM Do YYYY}}\n\n## Journal\n"


@pytest.mark.parametrize("config", [None, "{}", '{"template": ""}', '{"template": null}'])
async def test__daily_note__uses_conventional_template(
    obsidian_vault: AsyncPath,
    config: str | None,
) -> None:
    """An unset template uses the conventional file and substitutes the note date."""
    await atomic_write_text(obsidian_vault / "Templates/Daily Note.md", TEMPLATE)
    if config is not None:
        await atomic_write_text(obsidian_vault / ".obsidian/daily-notes.json", config)

    section = await update_daily_note_section(
        heading_path=("Journal",),
        content="A useful day.",
        date=DATE,
    )

    assert section == "## Journal\n\nA useful day."
    persisted = await (
        obsidian_vault / VAULT_PATHS.daily_notes_dir / f"{DATE}.md"
    ).read_text(
        encoding="utf-8",
    )
    assert "date: '2026-05-20'" in persisted
    assert f"# {format_human_date(DATE)}" in persisted
    assert "A useful day." in persisted
    assert "{{date" not in persisted


@pytest.mark.parametrize("configured", ["Templates/Custom", "Templates/Custom.md"])
async def test__daily_note__configured_template_takes_precedence(
    obsidian_vault: AsyncPath,
    configured: str,
) -> None:
    """Explicit settings with or without an extension override the conventional file."""
    await atomic_write_text(obsidian_vault / "Templates/Daily Note.md", "# Fallback\n")
    await atomic_write_text(obsidian_vault / "Templates/Custom.md", TEMPLATE)
    await atomic_write_text(
        obsidian_vault / ".obsidian/daily-notes.json",
        json.dumps({"template": configured}),
    )

    async with ObsidianService().daily_note(
        DATE,
        create_if_not_exists=True,
        read_only=False,
    ) as note:
        assert note.get_section((format_human_date(DATE), "Journal"))
        assert "Fallback" not in note.render()


async def test__daily_note__missing_fallback_creates_empty_note(
    obsidian_vault: AsyncPath,
) -> None:
    """A vault without a configured or conventional template can create an empty note."""
    async with ObsidianService().daily_note(
        DATE,
        create_if_not_exists=True,
        read_only=False,
    ) as note:
        assert not note.render().strip()

    assert await (obsidian_vault / VAULT_PATHS.daily_notes_dir / f"{DATE}.md").is_file()


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("{broken", "must contain valid JSON"),
        ("[]", "must contain an object"),
        ('{"template": 42}', "template must be a vault-relative path string"),
        ('{"template": "../secret"}', "Unsafe path"),
        ('{"template": "/tmp/secret.md"}', "Unsafe path"),
        ('{"template": "Templates/Missing"}', "Daily-note template not found"),
    ],
)
async def test__daily_note__invalid_settings_do_not_create_note(
    obsidian_vault: AsyncPath,
    config: str,
    message: str,
) -> None:
    """Invalid explicit settings fail before creating a note, even with a fallback."""
    await atomic_write_text(obsidian_vault / "Templates/Daily Note.md", TEMPLATE)
    await atomic_write_text(obsidian_vault / ".obsidian/daily-notes.json", config)

    with pytest.raises(exc.UserError, match=message):
        async with ObsidianService().daily_note(
            DATE,
            create_if_not_exists=True,
            read_only=False,
        ):
            pytest.fail("Invalid settings must prevent opening the note")

    assert not await (
        obsidian_vault / VAULT_PATHS.daily_notes_dir / f"{DATE}.md"
    ).exists()


async def test__daily_note__rejects_template_symlink_outside_vault(
    obsidian_vault: AsyncPath,
) -> None:
    """A conventional template symlink cannot read a file outside the vault."""
    template = obsidian_vault / "Templates/Daily Note.md"
    await template.symlink_to(obsidian_vault.parent / "outside-template.md")

    with pytest.raises(exc.UserError, match="Path escapes root"):
        async with ObsidianService().daily_note(
            DATE,
            create_if_not_exists=True,
            read_only=False,
        ):
            pytest.fail("An unsafe template must prevent opening the note")

    assert not await (
        obsidian_vault / VAULT_PATHS.daily_notes_dir / f"{DATE}.md"
    ).exists()


async def test__daily_note__template_read_failure_does_not_create_note(
    obsidian_vault: AsyncPath,
) -> None:
    """An unreadable template must not silently produce an empty note."""
    await (obsidian_vault / "Templates/Daily Note.md").mkdir()

    with pytest.raises(IsADirectoryError):
        async with ObsidianService().daily_note(
            DATE,
            create_if_not_exists=True,
            read_only=False,
        ):
            pytest.fail("A template read failure must prevent opening the note")

    assert not await (
        obsidian_vault / VAULT_PATHS.daily_notes_dir / f"{DATE}.md"
    ).exists()


async def test__daily_note__existing_note_ignores_templates(
    obsidian_vault: AsyncPath,
) -> None:
    """An existing note opens without loading even an invalid template setting."""
    note_path = obsidian_vault / VAULT_PATHS.daily_notes_dir / f"{DATE}.md"
    original = f"# {format_human_date(DATE)}\n\n## Music\n\nExisting track.\n"
    await atomic_write_text(note_path, original)
    await atomic_write_text(obsidian_vault / ".obsidian/daily-notes.json", "{broken")

    async with ObsidianService().daily_note(DATE, create_if_not_exists=True) as note:
        assert "Existing track." in note.render()

    assert await note_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("create_section", [False, True])
async def test__daily_note__existing_note_requires_explicit_section_creation(
    obsidian_vault: AsyncPath,
    *,
    create_section: bool,
) -> None:
    """Music-only notes keep their content and require opt-in to add Journal."""
    note_path = obsidian_vault / VAULT_PATHS.daily_notes_dir / f"{DATE}.md"
    original = f"# {format_human_date(DATE)}\n\n## Music\n\nExisting track.\n"
    await atomic_write_text(note_path, original)
    await atomic_write_text(obsidian_vault / "Templates/Daily Note.md", TEMPLATE)

    if create_section:
        _ = await update_daily_note_section(
            heading_path=("Journal",),
            content="A useful day.",
            date=DATE,
            create_section_if_not_exists=True,
        )

        persisted = await note_path.read_text(encoding="utf-8")
        assert "Existing track." in persisted
        assert "## Journal\n\nA useful day." in persisted
        assert "date:" not in persisted
    else:
        with pytest.raises(
            exc.InformationRequiredError,
            match="create_section_if_not_exists=true",
        ):
            _ = await update_daily_note_section(
                heading_path=("Journal",),
                content="A useful day.",
                date=DATE,
            )

        assert await note_path.read_text(encoding="utf-8") == original
