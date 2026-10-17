"""Exercise the notification REST callbacks and conversational MCP tools together."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2
from pydantic import SecretStr

from backplane.api.routers.idea_followup import get_idea_followup_service
from backplane.mcp.idea_followup import get_idea_followup, save_idea_elaboration
from backplane.services.idea_followup import IdeaFollowup, IdeaFollowupService
from backplane.services.ideas import IdeaService
from backplane.utils import SETTINGS

if TYPE_CHECKING:
    import pytest
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.utils import AsyncPath


async def test_notification_to_assist_elaboration(
    api_app: FastAPI,
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated HA selection/delivery resumes via MCP and persists one elaboration."""
    _ = obsidian_vault
    service = IdeaFollowupService(context_session_factory)
    api_app.dependency_overrides[get_idea_followup_service] = lambda: service
    monkeypatch.setattr(
        "backplane.mcp.idea_followup.IdeaFollowupService",
        lambda: service,
    )
    monkeypatch.setattr(SETTINGS, "context_api_token", SecretStr("test-token"))
    idea = await IdeaService.record("Consider building a weather station")
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=api_app),
        base_url="http://test",
    ) as client:
        missing = await client.post("/idea-followups/reserve", json={})
        assert missing.status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        empty = await client.post("/idea-followups/reserve", json={})
        assert empty.json() is None
        claimed = await client.post(
            "/idea-followups/reserve",
            json={"home": True, "receptive": True, "outside_quiet_hours": True},
        )
        assert claimed.status_code == 200
        followup = IdeaFollowup.model_validate(claimed.json())
        delivered = await client.post(f"/idea-followups/{followup.prompt.id}/delivered")
        assert delivered.status_code == 200
        current = await get_idea_followup()
        assert current is not None
        assert current.idea.id == idea.id
        link = await save_idea_elaboration(
            followup.prompt.id,
            idea.id,
            "One temperature sensor outdoors first.",
        )
        assert "Idea development" in link
        current = await get_idea_followup(followup.prompt.id)
        assert current is not None
        assert current.elaborations == ["One temperature sensor outdoors first."]


async def test_notification_snooze_and_dismiss_callbacks(
    api_app: FastAPI,
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Button callbacks act on their exact prompt IDs and reject unrelated IDs."""
    _ = obsidian_vault
    service = IdeaFollowupService(context_session_factory)
    api_app.dependency_overrides[get_idea_followup_service] = lambda: service
    monkeypatch.setattr(SETTINGS, "context_api_token", SecretStr("test-token"))
    _ = await IdeaService.record("Consider building a weather station")
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=api_app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-token"},
    ) as client:
        claimed = await client.post(
            "/idea-followups/reserve",
            json={"home": True, "receptive": True, "outside_quiet_hours": True},
        )
        followup = IdeaFollowup.model_validate(claimed.json())
        delivered = await client.post(f"/idea-followups/{followup.prompt.id}/delivered")
        assert delivered.status_code == 200
        snoozed = await client.post(f"/idea-followups/{followup.prompt.id}/snooze")
        assert snoozed.status_code == 200
        assert (
            await client.post(f"/idea-followups/{followup.prompt.id}/snooze")
        ).status_code == 200
        missing = await client.post(
            "/idea-followups/00000000-0000-0000-0000-000000000000/snooze",
        )
        assert missing.status_code == 404
        dismissed = await client.post(f"/idea-followups/{followup.prompt.id}/dismiss")
        assert dismissed.status_code == 200
        assert dismissed.json()["status"] == "dismissed"
        assert await service.get() is None
