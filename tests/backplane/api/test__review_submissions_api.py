"""Exercise durable REST receipt and exact MCP save as one phone reply flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2
from pydantic import SecretStr

from backplane.api.routers.review_submissions import get_review_submission_service
from backplane.context.review_submissions import ReviewAttempt, ReviewSubmission
from backplane.mcp.review_submissions import get_review_submission, save_review_submission
from backplane.services.idea_followup import FollowupAvailability, IdeaFollowupService
from backplane.services.ideas import IdeaService
from backplane.services.review_submissions import ReviewSubmissionService
from backplane.utils import SETTINGS

if TYPE_CHECKING:
    import pytest
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.utils import AsyncPath


async def test_phone_receipt_to_mcp_save(
    api_app: FastAPI,
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth, claim, exact MCP save and duplicate claim preserve one exported reply."""
    _ = obsidian_vault
    service = ReviewSubmissionService(context_session_factory)
    api_app.dependency_overrides[get_review_submission_service] = lambda: service
    monkeypatch.setattr(
        "backplane.mcp.review_submissions.ReviewSubmissionService",
        lambda: service,
    )
    monkeypatch.setattr(SETTINGS, "context_api_token", SecretStr("test-token"))
    _ = await IdeaService.record("Maybe a weather station")
    followups = IdeaFollowupService(context_session_factory)
    followup = await followups.reserve(
        FollowupAvailability(home=True, receptive=True, outside_quiet_hours=True),
    )
    assert followup is not None
    _ = await followups.mark_submitted(followup.prompt.id)
    payload = {
        "idempotency_key": "phone-event-1",
        "prompt_id": str(followup.prompt.id),
        "kind": "idea",
        "text": "  One outdoor sensor first.  ",
    }

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=api_app),
        base_url="http://test",
    ) as client:
        assert (await client.post("/review-submissions", json=payload)).status_code == 401
        assert (await client.get("/review-submissions")).status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        response = await client.post("/review-submissions", json=payload)
        assert response.status_code == 200
        receipt = ReviewSubmission.model_validate(response.json())
        assert receipt.text == payload["text"]
        assert receipt.status == "pending"
        route = f"/review-submissions/{receipt.id}"
        assert (await client.get("/review-submissions?limit=0")).status_code == 422
        assert len((await client.get("/review-submissions")).json()) == 1

        attempt = ReviewAttempt.model_validate(
            (await client.post(f"{route}/begin")).json(),
        )
        assert attempt.request_text is not None
        assert attempt.submission.attempt_id is not None
        assert (await client.post(f"{route}/begin")).status_code == 409
        assert (await get_review_submission(receipt.id)).prompt_id == followup.prompt.id
        saved = await save_review_submission(receipt.id, attempt.submission.attempt_id)
        assert saved.status == "saved"
        completed = await client.post(
            f"{route}/finish",
            json={
                "attempt_id": str(attempt.submission.attempt_id),
                "assistant_reply": "Saved.",
                "conversation_id": "test-conversation",
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "saved"
        assert (await client.get(route)).json()["text"] == payload["text"]
        duplicate = ReviewAttempt.model_validate(
            (await client.post(f"{route}/begin")).json(),
        )
        assert duplicate.request_text is None
        assert duplicate.submission.status == "saved"
        assert (await client.get("/review-submissions")).json() == []

    updated = await followups.get(followup.prompt.id)
    assert updated is not None
    assert updated.elaborations == [payload["text"]]
