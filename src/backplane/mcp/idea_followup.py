"""Assist tools for developing the exact idea from a follow-up notification."""

from __future__ import annotations

import uuid  # ruff:ignore[typing-only-standard-library-import] -- MCP resolves annotations at runtime.
from typing import TYPE_CHECKING

from backplane.mcp.auth import OAuthToolRegistrationKwargs, oauth_tool_registration_kwargs
from backplane.services.idea_followup import (
    IdeaElaboration,
    IdeaFollowup,
    IdeaFollowupService,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def get_idea_followup(prompt_id: uuid.UUID | None = None) -> IdeaFollowup | None:
    """Read the idea from the user's follow-up notification before discussing it.

    Omit prompt_id for the current notification. If no current context exists,
    ask which idea the user means; never guess or choose a different idea.
    Ask one useful question about the outcome, feasibility or next step.

    Returns:
        Original wording, exact IDs and prior elaborations, or None.
    """
    return await IdeaFollowupService().get(prompt_id)


async def save_idea_elaboration(prompt_id: uuid.UUID, capture_id: str, text: str) -> str:
    """Save the user's elaboration against the exact IDs from get_idea_followup.

    Preserve the user's wording. This stores development notes, not a commitment.
    Create a project or task only when the user explicitly asks to commit to it.
    For tasks use capture_task then link_task_to_capture with its task filename stem and
    this capture_id. This avoids model enrichment; projectless tasks are valid.
    For a project, include the original idea wikilink and this development note in
    its Overview using create_vault_entity/update_vault_entity.

    Returns:
        The saved development note's wikilink; confirm only after success.
    """
    return await IdeaFollowupService().elaborate(
        prompt_id,
        IdeaElaboration(capture_id=capture_id, text=text),
    )


def register_idea_followup_tools(
    mcp: FastMCP[None],
    *,
    require_oauth: bool = False,
) -> None:
    """Register the two conversational follow-up tools."""
    auth_kwargs: OAuthToolRegistrationKwargs = {}
    if require_oauth:
        auth_kwargs = oauth_tool_registration_kwargs()
    for tool in (get_idea_followup, save_idea_elaboration):
        _ = mcp.tool(**auth_kwargs)(tool)
