"""Vault note routes."""

from __future__ import annotations

from fastapi import APIRouter

from backplane.api.schemas import MoveNoteRequest, MoveNoteResponse
from backplane.services.obsidian import ObsidianService
from backplane.utils import AsyncPath

router = APIRouter(tags=["notes"])


@router.post("/obsidian/notes/move", response_model=MoveNoteResponse)
async def move_note(request: MoveNoteRequest) -> MoveNoteResponse:
    """Move a vault-relative Markdown note.

    Returns:
        Move confirmation response.
    """
    moved_path = await ObsidianService.move_note(
        AsyncPath(request.source_path),
        AsyncPath(request.destination_path),
    )
    return MoveNoteResponse(
        message=f"Moved note to {moved_path}.",
        path=str(moved_path),
    )
