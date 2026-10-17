"""MCP tools for searching vault notes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from loguru import logger
from pydantic import Field

from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs
from backplane.services.vault_search import (
    VaultNoteSearchHit,
    VaultSearchKind,
    VaultSearchService,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

_FIND_DESCRIPTION = """Find notes by approximate title or filename.

Use when the user knows a note name, such as a Domain, Project, Resource, Person,
task, or daily note — for example "Home Assistant", "garage migration", or
"2026-06-16".

Prefer this over `search_vault_notes` for name-like queries. Prefer this over
`list_vault_entities` when searching across note kinds or when the name is partial."""

_SEARCH_DESCRIPTION = """Search vault note contents for a topic or phrase.

Use when the user asks what notes mention a topic, integration, or phrase — for
example "MQTT broker", "rain alert", or "backup verification".

Prefer this over `find_vault_notes` when the query is topical rather than a note name.
After finding a hit, read entity notes with `get_vault_entity`, daily notes with
`get_daily_note`, ideas with `list_ideas` and `get_idea`, or follow `canonical_link` in responses."""


async def find_vault_notes(
    query: Annotated[
        str,
        Field(
            description="Approximate note title or filename to match.",
            min_length=1,
        ),
    ],
    kinds: Annotated[
        list[VaultSearchKind] | None,
        Field(description="Note kinds to search. Omit to search all kinds."),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="Maximum number of hits to return.",
            ge=1,
            le=50,
        ),
    ] = 20,
) -> list[VaultNoteSearchHit]:
    """Find vault notes by title or filename.

    Args:
        query: Approximate note name to match.
        kinds: Optional note kinds to restrict the search.
        limit: Maximum number of hits to return.

    Returns:
        Ranked search hits sorted by match quality.
    """
    logger.info("find_vault_notes: query={!r} kinds={} limit={}", query, kinds, limit)
    return await VaultSearchService.find_notes_by_title(
        query,
        kinds=kinds,
        limit=limit,
    )


async def search_vault_notes(
    query: Annotated[
        str,
        Field(
            description="Topic or phrase to match in note content.",
            min_length=1,
        ),
    ],
    kinds: Annotated[
        list[VaultSearchKind] | None,
        Field(description="Note kinds to search. Omit to search all kinds."),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="Maximum number of hits to return.",
            ge=1,
            le=50,
        ),
    ] = 20,
) -> list[VaultNoteSearchHit]:
    """Search vault note contents for a topic or phrase.

    Args:
        query: Topic or phrase to match in note content.
        kinds: Optional note kinds to restrict the search.
        limit: Maximum number of hits to return.

    Returns:
        Ranked search hits with excerpts around the first match.
    """
    logger.info("search_vault_notes: query={!r} kinds={} limit={}", query, kinds, limit)
    return await VaultSearchService.search_note_contents(
        query,
        kinds=kinds,
        limit=limit,
    )


def register_vault_search_tools(
    mcp: FastMCP[None],
    *,
    require_oauth: bool = False,
) -> None:
    """Register vault note search tools on a FastMCP server instance.

    Parameters:
        require_oauth: If True, all registered tools require OAuth authentication.
    """
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()

    _ = mcp.tool(description=_FIND_DESCRIPTION, **auth_kwargs)(find_vault_notes)
    _ = mcp.tool(description=_SEARCH_DESCRIPTION, **auth_kwargs)(search_vault_notes)
