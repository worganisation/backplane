"""Generate README documentation from the registered MCP surface."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path  # ruff:ignore[typing-only-standard-library-import]
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastmcp.resources import Resource, ResourceTemplate
    from fastmcp.tools import Tool

README_CATALOG_START = "<!-- backplane:mcp-catalog:start -->"
README_CATALOG_END = "<!-- backplane:mcp-catalog:end -->"
README_CATALOG_INSERTION_ANCHOR = "\n### Public MCP (ChatGPT)\n"


@dataclass(frozen=True, slots=True)
class McpParameterRow:
    """One row in a tool or resource-template parameter table."""

    name: str
    type_label: str
    required: bool
    default: str
    description: str


@dataclass(frozen=True, slots=True)
class McpToolDoc:
    """Documented MCP tool."""

    name: str
    description: str
    parameters: tuple[McpParameterRow, ...]


@dataclass(frozen=True, slots=True)
class McpResourceDoc:
    """Documented MCP resource."""

    name: str
    uri: str
    description: str
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class McpResourceTemplateDoc:
    """Documented MCP resource template."""

    name: str
    uri_template: str
    description: str
    mime_type: str | None
    parameters: tuple[McpParameterRow, ...]


@dataclass(frozen=True, slots=True)
class McpCatalog:
    """Collected MCP server metadata for documentation."""

    server_name: str
    server_version: str
    instructions: str
    tools: tuple[McpToolDoc, ...]
    resources: tuple[McpResourceDoc, ...]
    resource_templates: tuple[McpResourceTemplateDoc, ...]


def _schema_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast("dict[str, object]", value)


def _schema_type_label(schema: Mapping[str, object]) -> str:
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        typed_enum_values = cast("list[object]", enum_values)
        return " \\| ".join(f"`{value}`" for value in typed_enum_values)

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        typed_any_of = cast("list[object]", any_of)
        non_null = [
            _schema_type_label(option_dict)
            for option in typed_any_of
            if (option_dict := _schema_dict(option)) and option_dict.get("type") != "null"
        ]
        if non_null:
            optional = any(
                _schema_dict(option).get("type") == "null" for option in typed_any_of
            )
            label = " \\| ".join(non_null)
            return f"{label}?" if optional else label

    schema_type = schema.get("type")
    if schema_type == "array":
        items = _schema_dict(schema.get("items"))
        return f"{_schema_type_label(items)}[]"
    if schema_type == "string" and schema.get("format") == "date":
        return "`date` (YYYY-MM-DD)"
    if isinstance(schema_type, str):
        return f"`{schema_type}`"

    return "`unknown`"


def _schema_default(schema: Mapping[str, object]) -> str:
    if "default" not in schema:
        return "—"
    default = schema["default"]
    if default is None:
        return "`null`"
    if isinstance(default, bool):
        return f"`{str(default).lower()}`"
    if isinstance(default, str):
        return f"`{default}`"
    return f"`{default!r}`"


def _parameter_rows(
    parameters: Mapping[str, object] | None,
) -> tuple[McpParameterRow, ...]:
    if parameters is None:
        return ()

    properties = _schema_dict(parameters.get("properties"))
    required_names = {
        name
        for name in cast("list[object]", parameters.get("required", []))
        if isinstance(name, str)
    }

    rows: list[McpParameterRow] = []
    for name in sorted(properties):
        prop = _schema_dict(properties[name])
        description = prop.get("description")
        rows.append(
            McpParameterRow(
                name=name,
                type_label=_schema_type_label(prop),
                required=name in required_names,
                default=_schema_default(prop),
                description=description if isinstance(description, str) else "",
            ),
        )
    return tuple(rows)


def _tool_doc(tool: Tool) -> McpToolDoc:
    return McpToolDoc(
        name=tool.name,
        description=tool.description or "",
        parameters=_parameter_rows(tool.parameters),
    )


def _resource_doc(resource: Resource) -> McpResourceDoc:
    return McpResourceDoc(
        name=resource.name,
        uri=str(resource.uri),
        description=resource.description or "",
        mime_type=resource.mime_type,
    )


def _resource_template_doc(template: ResourceTemplate) -> McpResourceTemplateDoc:
    return McpResourceTemplateDoc(
        name=template.name,
        uri_template=template.uri_template,
        description=template.description or "",
        mime_type=template.mime_type,
        parameters=_parameter_rows(template.parameters),
    )


async def collect_mcp_catalog() -> McpCatalog:
    """Introspect the Backplane MCP server and collect documentation metadata.

    Returns:
        Structured catalog of server instructions, tools, and resources.
    """
    from backplane.mcp.server import (
        create_mcp_server,
    )

    mcp = create_mcp_server()
    tools = await mcp.list_tools()
    resources = await mcp.list_resources()
    templates = await mcp.list_resource_templates()

    return McpCatalog(
        server_name=mcp.name,
        server_version=mcp.version or "",
        instructions=mcp.instructions or "",
        tools=tuple(
            _tool_doc(tool) for tool in sorted(tools, key=lambda item: item.name)
        ),
        resources=tuple(
            _resource_doc(resource)
            for resource in sorted(resources, key=lambda item: item.name)
        ),
        resource_templates=tuple(
            _resource_template_doc(template)
            for template in sorted(templates, key=lambda item: item.name)
        ),
    )


def _render_parameter_table(parameters: tuple[McpParameterRow, ...]) -> str:
    if not parameters:
        return ""

    lines = [
        "",
        "| Parameter | Type | Required | Default | Description |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in parameters:
        required = "yes" if row.required else "no"
        description = row.description.replace("\n", " ")
        lines.append(
            f"| `{row.name}` | {row.type_label} | {required} | {row.default} | {description} |",
        )
    return "\n".join(lines)


def render_mcp_catalog_markdown(catalog: McpCatalog) -> str:
    """Render the MCP catalog as markdown body text (without section heading).

    Args:
        catalog: Collected MCP metadata.

    Returns:
        Markdown fragment for insertion into README.md.
    """
    lines = [
        (
            "This section is generated automatically from the registered MCP surface. "
            "Run `prek run update-readme-mcp-catalog` to refresh it after changing tools "
            "or resources."
        ),
        "",
        f"**Server:** `{catalog.server_name}` v{catalog.server_version}",
        "",
        "### Server instructions",
        "",
        catalog.instructions.strip(),
        "",
        "### Tools",
        "",
    ]

    if not catalog.tools:
        lines.append("_No tools registered._")
    else:
        for index, tool in enumerate(catalog.tools):
            if index:
                lines.append("")
            lines.extend(
                [
                    f"#### `{tool.name}`",
                    "",
                    tool.description.strip(),
                ],
            )
            lines.append(_render_parameter_table(tool.parameters))

    lines.extend(["", "### Resources", ""])
    if not catalog.resources:
        lines.append("_No static resources registered._")
    else:
        for index, resource in enumerate(catalog.resources):
            if index:
                lines.append("")
            mime = f" (`{resource.mime_type}`)" if resource.mime_type else ""
            lines.extend(
                [
                    f"#### `{resource.name}`",
                    "",
                    f"- **URI:** `{resource.uri}`{mime}",
                    f"- **Description:** {resource.description.strip()}",
                ],
            )

    lines.extend(["", "### Resource templates", ""])
    if not catalog.resource_templates:
        lines.append("_No resource templates registered._")
    else:
        for index, template in enumerate(catalog.resource_templates):
            if index:
                lines.append("")
            mime = f" (`{template.mime_type}`)" if template.mime_type else ""
            lines.extend(
                [
                    f"#### `{template.name}`",
                    "",
                    f"- **URI template:** `{template.uri_template}`{mime}",
                    f"- **Description:** {template.description.strip()}",
                ],
            )
            lines.append(_render_parameter_table(template.parameters))

    return "\n".join(lines).rstrip() + "\n"


def render_readme_catalog_section(catalog: McpCatalog) -> str:
    """Render the full README section, including markers and heading.

    Returns:
        Marked markdown section ready for README.md.
    """
    body = render_mcp_catalog_markdown(catalog)
    return (
        f"{README_CATALOG_START}\n"
        "## MCP tools and resources\n\n"
        f"{body}"
        f"{README_CATALOG_END}\n"
    )


def update_readme_catalog(readme_path: Path, catalog: McpCatalog) -> bool:
    """Insert or replace the MCP catalog section in README.md.

    Args:
        readme_path: Path to README.md.
        catalog: MCP metadata to document.

    Returns:
        True when README.md was modified.

    Raises:
        ValueError: When README.md is missing catalog markers and the insertion anchor.
    """
    section = render_readme_catalog_section(catalog)
    content = readme_path.read_text(encoding="utf-8")

    start_idx = content.find(README_CATALOG_START)
    end_idx = content.find(README_CATALOG_END, start_idx)
    if start_idx != -1 and end_idx != -1:
        end_idx += len(README_CATALOG_END)
        suffix = content[end_idx:]
        if section.endswith("\n") and suffix.startswith("\n"):
            suffix = suffix[1:]
        new_content = content[:start_idx] + section + suffix
    elif README_CATALOG_INSERTION_ANCHOR in content:
        before, after = content.split(README_CATALOG_INSERTION_ANCHOR, maxsplit=1)
        new_content = before + "\n" + section + README_CATALOG_INSERTION_ANCHOR + after
    else:
        msg = "README.md is missing MCP catalog markers and the Public MCP insertion anchor."
        raise ValueError(msg)

    if new_content == content:
        return False

    _ = readme_path.write_text(new_content, encoding="utf-8")
    return True


def generate_readme_catalog_markdown() -> str:
    """Collect MCP metadata and render the README catalog section.

    Returns:
        Full marked README section for the MCP catalog.
    """
    catalog = asyncio.run(collect_mcp_catalog())
    return render_readme_catalog_section(catalog)


def refresh_readme_catalog(readme_path: Path) -> bool:
    """Regenerate and write the MCP catalog section in README.md.

    Returns:
        True when README.md was modified.
    """
    catalog = asyncio.run(collect_mcp_catalog())
    return update_readme_catalog(readme_path, catalog)
