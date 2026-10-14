"""Tests for MCP README catalog generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from backplane.utils.async_path import AsyncPath
from backplane.utils.settings import SETTINGS
from scripts.dev.mcp_catalog import (
    README_CATALOG_END,
    README_CATALOG_INSERTION_ANCHOR,
    README_CATALOG_START,
    McpCatalog,
    McpParameterRow,
    McpResourceDoc,
    McpResourceTemplateDoc,
    McpToolDoc,
    _parameter_rows,
    _schema_default,
    _schema_type_label,
    collect_mcp_catalog,
    generate_readme_catalog_markdown,
    refresh_readme_catalog,
    render_mcp_catalog_markdown,
    render_readme_catalog_section,
    update_readme_catalog,
)

_FIXTURE_VAULT = (
    Path(__file__).resolve().parents[3] / "scripts" / "fixtures" / "readme-vault"
)


def test__schema_type_label__formats_common_json_schema_shapes() -> None:
    """JSON schema helpers render concise markdown type labels."""
    assert _schema_type_label({"type": "string"}) == "`string`"
    assert (
        _schema_type_label({"type": "string", "format": "date"}) == "`date` (YYYY-MM-DD)"
    )
    assert _schema_type_label({"enum": ["append", "prepend", "replace"]}) == (
        "`append` \\| `prepend` \\| `replace`"
    )
    assert (
        _schema_type_label({"type": "array", "items": {"type": "string"}}) == "`string`[]"
    )
    assert (
        _schema_type_label({"anyOf": [{"type": "string"}, {"type": "null"}]})
        == "`string`?"
    )


def test__render_mcp_catalog_markdown__includes_tools_resources_and_templates() -> None:
    """Rendered markdown documents tools, resources, and templates."""
    catalog = McpCatalog(
        server_name="Backplane",
        instructions="Keep outputs concise.",
        tools=(
            McpToolDoc(
                name="create_task",
                description="Create a task.",
                parameters=(
                    McpParameterRow(
                        name="description",
                        type_label="`string`",
                        required=True,
                        default="—",
                        description="Task text.",
                    ),
                ),
            ),
        ),
        resources=(
            McpResourceDoc(
                name="Today's Daily Note",
                uri="obsidian://daily-note/today",
                description="Today's note.",
                mime_type="text/markdown",
            ),
        ),
        resource_templates=(
            McpResourceTemplateDoc(
                name="Daily Note by Date",
                uri_template="obsidian://daily-note/{date}",
                description="Note for a date.",
                mime_type="text/markdown",
                parameters=(
                    McpParameterRow(
                        name="date",
                        type_label="`date` (YYYY-MM-DD)",
                        required=True,
                        default="—",
                        description="ISO date.",
                    ),
                ),
            ),
        ),
    )

    markdown = render_mcp_catalog_markdown(catalog)

    assert "#### `create_task`" in markdown
    assert "| `description` | `string` | yes | — | Task text. |" in markdown
    assert "obsidian://daily-note/today" in markdown
    assert "obsidian://daily-note/{date}" in markdown


def test__update_readme_catalog__replaces_existing_marked_section(tmp_path: Path) -> None:
    """README updates replace only the marked MCP catalog section."""
    readme = tmp_path / "README.md"
    readme.write_text(
        f"# Example\n\n{README_CATALOG_START}\n"
        "## MCP tools and resources\n\n"
        "old content\n\n"
        f"{README_CATALOG_END}\n\n"
        "### Public MCP (ChatGPT)\n\n",
        encoding="utf-8",
    )
    catalog = McpCatalog(
        server_name="Backplane",
        instructions="New instructions.",
        tools=(),
        resources=(),
        resource_templates=(),
    )

    changed = update_readme_catalog(readme, catalog)

    assert changed is True
    text = readme.read_text(encoding="utf-8")
    assert "old content" not in text
    assert "New instructions." in text
    assert "### Public MCP (ChatGPT)" in text


def test__update_readme_catalog__is_noop_when_content_unchanged(tmp_path: Path) -> None:
    """README updates return false when the rendered section is unchanged."""
    catalog = McpCatalog(
        server_name="Backplane",
        instructions="Same instructions.",
        tools=(),
        resources=(),
        resource_templates=(),
    )
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Example\n\n" + render_readme_catalog_section(catalog),
        encoding="utf-8",
    )

    changed = update_readme_catalog(readme, catalog)

    assert changed is False


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "boolean", "default": False}, "`boolean`"),
        ({"type": "boolean", "default": True}, "`boolean`"),
    ],
)
def test__schema_type_label__boolean(schema: dict[str, object], expected: str) -> None:
    """Boolean schemas render as markdown code spans."""
    assert _schema_type_label(schema) == expected


def test__schema_type_label__returns_unknown_for_empty_schema() -> None:
    """Schemas without a recognizable type render as unknown."""
    assert _schema_type_label({}) == "`unknown`"


def test__schema_type_label__ignores_non_dict_anyof_options() -> None:
    """Non-dict anyOf entries are skipped when building type labels."""
    assert _schema_type_label({"anyOf": ["not a dict", {"type": "string"}]}) == "`string`"


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({}, "—"),
        ({"default": None}, "`null`"),
        ({"default": True}, "`true`"),
        ({"default": False}, "`false`"),
        ({"default": "append"}, "`append`"),
        ({"default": 42}, "`42`"),
    ],
)
def test__schema_default__formats_values(
    schema: dict[str, object],
    expected: str,
) -> None:
    """Schema defaults render as markdown-friendly strings."""
    assert _schema_default(schema) == expected


def test__parameter_rows__returns_empty_for_none() -> None:
    """Missing parameter schemas produce no table rows."""
    assert _parameter_rows(None) == ()


def test__parameter_rows__builds_sorted_rows() -> None:
    """Parameter rows include type, required, default, and description metadata."""
    rows = _parameter_rows(
        {
            "properties": {
                "zebra": {"type": "string", "description": "Last alphabetically."},
                "alpha": {"type": "boolean", "default": False},
            },
            "required": ["alpha"],
        },
    )

    assert rows == (
        McpParameterRow(
            name="alpha",
            type_label="`boolean`",
            required=True,
            default="`false`",
            description="",
        ),
        McpParameterRow(
            name="zebra",
            type_label="`string`",
            required=False,
            default="—",
            description="Last alphabetically.",
        ),
    )


async def test__collect_mcp_catalog__introspects_registered_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog collection reads tools and resources from the MCP server."""
    monkeypatch.setattr(SETTINGS, "obsidian_vault_path", AsyncPath(_FIXTURE_VAULT))

    catalog = await collect_mcp_catalog()

    assert catalog.server_name == "Backplane"
    assert catalog.instructions
    assert any(tool.name == "add_to_daily_note" for tool in catalog.tools)
    assert any(
        resource.uri == "obsidian://daily-note/today" for resource in catalog.resources
    )
    assert any(
        template.uri_template == "obsidian://daily-note/{date}"
        for template in catalog.resource_templates
    )


def test__render_mcp_catalog_markdown__separates_multiple_entries() -> None:
    """Rendered markdown adds spacing between multiple tools and resources."""
    catalog = McpCatalog(
        server_name="Backplane",
        instructions="Keep outputs concise.",
        tools=(
            McpToolDoc(name="first_tool", description="First.", parameters=()),
            McpToolDoc(name="second_tool", description="Second.", parameters=()),
        ),
        resources=(
            McpResourceDoc(
                name="First Resource",
                uri="obsidian://one",
                description="First resource.",
                mime_type=None,
            ),
            McpResourceDoc(
                name="Second Resource",
                uri="obsidian://two",
                description="Second resource.",
                mime_type="text/markdown",
            ),
        ),
        resource_templates=(
            McpResourceTemplateDoc(
                name="First Template",
                uri_template="obsidian://template/one",
                description="First template.",
                mime_type=None,
                parameters=(),
            ),
            McpResourceTemplateDoc(
                name="Second Template",
                uri_template="obsidian://template/two",
                description="Second template.",
                mime_type="text/markdown",
                parameters=(),
            ),
        ),
    )

    markdown = render_mcp_catalog_markdown(catalog)

    assert "#### `first_tool`" in markdown
    assert "#### `second_tool`" in markdown
    assert "obsidian://one" in markdown
    assert "obsidian://two" in markdown
    assert "obsidian://template/one" in markdown
    assert "obsidian://template/two" in markdown
    assert "_No tools registered._" not in markdown


def test__update_readme_catalog__inserts_at_anchor_when_markers_missing(
    tmp_path: Path,
) -> None:
    """README updates can insert the catalog before the Public MCP section."""
    readme = tmp_path / "README.md"
    readme.write_text(
        f"# Example\n{README_CATALOG_INSERTION_ANCHOR}OAuth details follow.\n",
        encoding="utf-8",
    )
    catalog = McpCatalog(
        server_name="Backplane",
        instructions="New instructions.",
        tools=(),
        resources=(),
        resource_templates=(),
    )

    changed = update_readme_catalog(readme, catalog)

    assert changed is True
    text = readme.read_text(encoding="utf-8")
    assert README_CATALOG_START in text
    assert "New instructions." in text
    assert "### Public MCP (ChatGPT)" in text
    assert "OAuth details follow." in text


def test__update_readme_catalog__raises_when_anchor_missing(tmp_path: Path) -> None:
    """README updates fail when neither markers nor the insertion anchor exist."""
    readme = tmp_path / "README.md"
    readme.write_text("# Example\n\nNo catalog markers here.\n", encoding="utf-8")
    catalog = McpCatalog(
        server_name="Backplane",
        instructions="Instructions.",
        tools=(),
        resources=(),
        resource_templates=(),
    )

    with pytest.raises(ValueError, match="missing MCP catalog markers"):
        update_readme_catalog(readme, catalog)


def test__generate_readme_catalog_markdown__uses_live_server_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generated README sections include marked content from the MCP server."""
    monkeypatch.setattr(SETTINGS, "obsidian_vault_path", AsyncPath(_FIXTURE_VAULT))

    section = generate_readme_catalog_markdown()

    assert section.startswith(README_CATALOG_START)
    assert section.endswith(f"{README_CATALOG_END}\n")
    assert "#### `add_to_daily_note`" in section


def test__refresh_readme_catalog__writes_live_server_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh writes a marked README section from the live MCP server."""
    monkeypatch.setattr(SETTINGS, "obsidian_vault_path", AsyncPath(_FIXTURE_VAULT))
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Example\n\n"
        f"{README_CATALOG_START}\n"
        "## MCP tools and resources\n\n"
        "old content\n\n"
        f"{README_CATALOG_END}\n",
        encoding="utf-8",
    )

    changed = refresh_readme_catalog(readme)

    assert changed is True
    text = readme.read_text(encoding="utf-8")
    assert "old content" not in text
    assert "#### `add_to_daily_note`" in text
