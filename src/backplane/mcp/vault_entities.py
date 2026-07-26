"""MCP tools for vault entity notes (Domains, People, Projects, Resources)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from loguru import logger
from pydantic import Field

from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs
from backplane.services.vault_entities import (
    UpdateMode,
    VaultEntitySection,
    VaultEntityService,
)
from backplane.utils.enums import VaultEntityKind
from backplane.utils.helpers.obsidian import (
    VaultNoteMetadata,  # ruff:ignore[typing-only-first-party-import]
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

VaultEntityKindParam = Literal["domain", "person", "project", "resource"]

_LIST_DESCRIPTION = """List display names of vault entity notes for a given kind.

Use when the user asks what Domains, Projects, Resources, or People exist, or when
choosing from existing entities."""

_LIST_SECTIONS_DESCRIPTION = """List sections in a Domain, Project, Resource, or Person note.

Use before reading or updating a specific section when the available headings are unknown.
Returned paths are relative to the note title."""

_GET_DESCRIPTION = """Read a Domain, Project, Resource, or Person note as rendered markdown.

Use when the user asks about an entity note's contents."""

_GET_SECTION_DESCRIPTION = """Read one section of a Domain, Project, Resource, or Person note as rendered markdown.

Use when only a specific section is needed. Pass the exact section path returned by
`list_vault_entity_sections`."""

_CREATE_DESCRIPTION = """Create a new Domain, Project, Resource, or Person note from the vault template.

Use for new durable entities:
- Domains: broad areas or platforms.
- Resources: specific integrations, APIs, vendors, services, or references.
- Projects: scoped outcomes or ongoing efforts.
- People: individuals referenced in related work.

Do not create duplicate Domain/Resource notes with the same meaning.
Fails if a note with the same name already exists."""

_UPDATE_DESCRIPTION = """Update a section of a Domain, Project, Resource, or Person note.

Use `append` for most captures. Use `replace` only when the user explicitly asks to overwrite.

Common entity sections include:
- Overview
- Notes
- Related Tasks

Some entity kinds may also have more specific sections, such as Goals, Links, Context,
Key Resources, or Active Projects.

When the target section is obvious, use the most appropriate existing/common section, usually
`["Overview"]`, `["Notes"]`, or `["Related Tasks"]`.

When the available headings are unknown or the target section is ambiguous, call
`list_vault_entity_sections` first and pass an exact returned path.

Only set `create_section_if_not_exists=true` when the user explicitly asks for a new section,
or when no existing section is appropriate."""


async def list_vault_entities(
    kind: Annotated[
        VaultEntityKindParam,
        Field(
            description="Entity kind to list: `domain`, `person`, `project`, or `resource`.",
        ),
    ],
) -> list[str]:
    """List display names of vault entity notes.

    Args:
        kind: Entity kind to list.

    Returns:
        Display names sorted alphabetically.
    """
    logger.info("list_vault_entities: kind={}", kind)
    return await VaultEntityService.list_entities(VaultEntityKind(kind))


async def list_vault_entity_sections(
    kind: Annotated[
        VaultEntityKindParam,
        Field(description="Entity kind: `domain`, `person`, `project`, or `resource`."),
    ],
    name: Annotated[
        str,
        Field(description="Human-readable entity name."),
    ],
) -> list[VaultEntitySection]:
    """List sections from a vault entity note.

    Parameters:
        kind: The type of vault entity (domain, person, project, or resource).
        name: The human-readable name of the entity.

    Returns:
        A list of VaultEntitySection objects in document order.
    """
    logger.info("list_vault_entity_sections: kind={} name={!r}", kind, name)
    return await VaultEntityService.list_entity_sections(
        VaultEntityKind(kind),
        name,
    )


async def get_vault_entity(
    kind: Annotated[
        VaultEntityKindParam,
        Field(description="Entity kind: `domain`, `person`, `project`, or `resource`."),
    ],
    name: Annotated[
        str,
        Field(description="Human-readable entity name."),
    ],
) -> str:
    """Retrieve a vault entity note.

    Returns:
        The entity note rendered as markdown.
    """
    logger.info("get_vault_entity: kind={} name={!r}", kind, name)
    return await VaultEntityService.get_entity(VaultEntityKind(kind), name)


async def get_vault_entity_section(
    *,
    kind: Annotated[
        VaultEntityKindParam,
        Field(description="Entity kind: `domain`, `person`, `project`, or `resource`."),
    ],
    name: Annotated[
        str,
        Field(description="Human-readable entity name."),
    ],
    heading_path: Annotated[
        list[str],
        Field(
            description=("Section path relative to the note title, e.g. `['Overview']`."),
            min_length=1,
        ),
    ],
) -> str:
    """Read one section of a vault entity note.

    Args:
        kind: Entity kind.
        name: Human-readable entity name.
        heading_path: Section path relative to the note title.

    Returns:
        The requested section rendered as markdown.
    """
    logger.info(
        "get_vault_entity_section: kind={} name={!r} heading_path={!r}",
        kind,
        name,
        heading_path,
    )
    return await VaultEntityService.get_entity_section(
        VaultEntityKind(kind),
        name,
        heading_path=heading_path,
    )


async def create_vault_entity(
    kind: Annotated[
        VaultEntityKindParam,
        Field(description="Entity kind: `domain`, `person`, `project`, or `resource`."),
    ],
    name: Annotated[
        str,
        Field(description="Human-readable note title."),
    ],
) -> VaultNoteMetadata:
    """Create a new vault entity note from the vault template.

    Args:
        kind: Entity kind.
        name: Human-readable entity name.

    Returns:
        Metadata for the created note, including `canonical_link`.
    """
    logger.info("create_vault_entity: kind={} name={!r}", kind, name)
    return await VaultEntityService.create_entity(VaultEntityKind(kind), name)


async def update_vault_entity(
    *,
    kind: Annotated[
        VaultEntityKindParam,
        Field(description="Entity kind: `domain`, `person`, `project`, or `resource`."),
    ],
    name: Annotated[
        str,
        Field(description="Human-readable entity name."),
    ],
    heading_path: Annotated[
        list[str],
        Field(
            description=(
                "Section path relative to the note title. Prefer exact paths from "
                "`list_vault_entity_sections` when available."
            ),
            min_length=1,
        ),
    ],
    content: Annotated[
        str,
        Field(description="Markdown content to add or replace."),
    ],
    mode: Annotated[
        UpdateMode,
        Field(
            description=(
                "How to combine content with existing section text. Prefer `append`; "
                "use `replace` only when explicitly requested."
            ),
        ),
    ] = "append",
    create_section_if_not_exists: Annotated[
        bool,
        Field(
            description=(
                "Create the requested section and any missing ancestors if they do not exist."
            ),
        ),
    ] = False,
) -> str:
    """Update a section of a vault entity note.

    Args:
        kind: Entity kind.
        name: Human-readable entity name.
        heading_path: Section path relative to the note title.
        content: Markdown content to combine with the section.
        mode: How to combine content with existing section text.
        create_section_if_not_exists: Create the section when missing.

    Returns:
        The updated section rendered as markdown.
    """
    logger.info(
        "update_vault_entity: kind={} name={!r} heading_path={!r} mode={}",
        kind,
        name,
        heading_path,
        mode,
    )
    return await VaultEntityService.update_entity(
        VaultEntityKind(kind),
        name,
        heading_path=heading_path,
        content=content,
        mode=mode,
        create_section_if_not_exists=create_section_if_not_exists,
    )


def register_vault_entity_tools(
    mcp: FastMCP[None],
    *,
    require_oauth: bool = False,
) -> None:
    """Register vault entity tools for listing, reading, creating, and updating vault entity notes.

    Parameters:
        require_oauth (bool): If True, all registered tools require OAuth authentication. Defaults to False.
    """
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()

    _ = mcp.tool(description=_LIST_DESCRIPTION, **auth_kwargs)(list_vault_entities)
    _ = mcp.tool(description=_LIST_SECTIONS_DESCRIPTION, **auth_kwargs)(
        list_vault_entity_sections,
    )
    _ = mcp.tool(description=_GET_DESCRIPTION, **auth_kwargs)(get_vault_entity)
    _ = mcp.tool(description=_GET_SECTION_DESCRIPTION, **auth_kwargs)(
        get_vault_entity_section,
    )
    _ = mcp.tool(description=_CREATE_DESCRIPTION, **auth_kwargs)(create_vault_entity)
    _ = mcp.tool(description=_UPDATE_DESCRIPTION, **auth_kwargs)(update_vault_entity)
