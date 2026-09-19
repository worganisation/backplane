"""Vault entity routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from backplane.api.schemas import (
    CreateEntityRequest,
    EntityKind,
    EntitySectionUpdateRequest,
    MarkdownResponse,
    NamesResponse,
    SectionResponse,
    SectionsResponse,
    VaultEntitySectionResponse,
)
from backplane.services.vault_entities import VaultEntityService
from backplane.utils.enums import VaultEntityKind
from backplane.utils.helpers.obsidian import VaultNoteMetadata

router = APIRouter(tags=["entities"])


@router.get("/obsidian/entities/{kind}", response_model=NamesResponse)
async def list_entities(kind: EntityKind) -> NamesResponse:
    """List entity display names for a kind.

    Returns:
        Entity names response.
    """
    return NamesResponse(
        names=await VaultEntityService.list_entities(VaultEntityKind(kind)),
    )


@router.post(
    "/obsidian/entities/{kind}",
    response_model=VaultNoteMetadata,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity(
    kind: EntityKind,
    request: CreateEntityRequest,
) -> VaultNoteMetadata:
    """Create an entity note from its vault template.

    Returns:
        Metadata for the created note.
    """
    return await VaultEntityService.create_entity(VaultEntityKind(kind), request.name)


@router.get("/obsidian/entities/{kind}/{name}", response_model=MarkdownResponse)
async def get_entity(kind: EntityKind, name: str) -> MarkdownResponse:
    """Read an entity note.

    Returns:
        Rendered entity note response.
    """
    return MarkdownResponse(
        markdown=await VaultEntityService.get_entity(VaultEntityKind(kind), name),
    )


@router.get(
    "/obsidian/entities/{kind}/{name}/sections",
    response_model=SectionsResponse,
)
async def list_entity_sections(kind: EntityKind, name: str) -> SectionsResponse:
    """List available entity-note sections.

    Returns:
        Available section metadata response.
    """
    sections = await VaultEntityService.list_entity_sections(VaultEntityKind(kind), name)
    return SectionsResponse(
        sections=[VaultEntitySectionResponse(**section) for section in sections],
    )


@router.get(
    "/obsidian/entities/{kind}/{name}/section",
    response_model=SectionResponse,
)
async def get_entity_section(
    kind: EntityKind,
    name: str,
    heading_path: Annotated[list[str], Query(min_length=1)],
) -> SectionResponse:
    """Read a section in an entity note.

    Returns:
        Rendered entity section response.
    """
    return SectionResponse(
        markdown=await VaultEntityService.get_entity_section(
            VaultEntityKind(kind),
            name,
            heading_path=heading_path,
        ),
    )


@router.patch(
    "/obsidian/entities/{kind}/{name}/section",
    response_model=SectionResponse,
)
async def update_entity_section(
    kind: EntityKind,
    name: str,
    request: EntitySectionUpdateRequest,
) -> SectionResponse:
    """Update a section in an entity note.

    Returns:
        Rendered updated entity section response.
    """
    return SectionResponse(
        markdown=await VaultEntityService.update_entity(
            VaultEntityKind(kind),
            name,
            heading_path=request.heading_path,
            content=request.content,
            mode=request.mode,
            create_section_if_not_exists=request.create_section_if_not_exists,
        ),
    )
