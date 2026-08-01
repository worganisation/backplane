"""Vault search routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from backplane.api.schemas import SearchResponse
from backplane.services.vault_search import VaultSearchKind, VaultSearchService

router = APIRouter(tags=["search"])


@router.get("/obsidian/search/find", response_model=SearchResponse)
async def find_notes(
    query: Annotated[str, Query(min_length=1)],
    kinds: list[VaultSearchKind] | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    """Find vault notes by title or filename.

    Returns:
        Ranked title-search response.
    """
    return SearchResponse(
        hits=await VaultSearchService.find_notes_by_title(
            query,
            kinds=kinds,
            limit=limit,
        ),
    )


@router.get("/obsidian/search/content", response_model=SearchResponse)
async def search_notes(
    query: Annotated[str, Query(min_length=1)],
    kinds: list[VaultSearchKind] | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    """Search vault note contents for a topic or phrase.

    Returns:
        Ranked content-search response.
    """
    return SearchResponse(
        hits=await VaultSearchService.search_note_contents(
            query,
            kinds=kinds,
            limit=limit,
        ),
    )
