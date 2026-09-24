"""End-to-end REST coverage for context capture."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import httpx
from pydantic import SecretStr

from backplane.api.routers.context_capture import get_context_capture_service
from backplane.context.schemas import (
    CapturePromptEvaluationResult,
    ContextEventCreate,
    ContextEventList,
    ContextEventResult,
)
from backplane.utils import SETTINGS

if TYPE_CHECKING:
    import pytest
    from fastapi import FastAPI

    from backplane.services.context_capture import ContextCaptureService


AUTH_VALUE = "context-test-credential"
HEADERS = {"Authorization": f"Bearer {AUTH_VALUE}"}


def _event(key: str) -> ContextEventCreate:
    return ContextEventCreate(
        user_id="will",
        source="api-test",
        source_event_id=key,
        idempotency_key=key,
        kind="location.changed",
        occurred_at=dt.datetime(2026, 9, 2, 10, tzinfo=dt.UTC),
        summary=f"Location {key}",
    )


async def test__context_api__requires_dedicated_bearer_token(
    api_app: FastAPI,
    context_service: ContextCaptureService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every context route fails closed without the configured bearer token."""
    api_app.dependency_overrides[get_context_capture_service] = lambda: context_service
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://backplane.test",
    ) as client:
        monkeypatch.setattr(SETTINGS, "context_api_token", None)
        health = await client.get("/health/check")
        unconfigured = await client.get("/capture-policies/will")
        monkeypatch.setattr(SETTINGS, "context_api_token", SecretStr(AUTH_VALUE))
        missing = await client.get("/capture-policies/will")
        invalid = await client.get(
            "/capture-policies/will",
            headers={"Authorization": "Bearer wrong"},
        )
        valid = await client.get("/capture-policies/will", headers=HEADERS)

    assert health.status_code == httpx.codes.OK
    assert unconfigured.status_code == httpx.codes.SERVICE_UNAVAILABLE
    assert missing.status_code == httpx.codes.UNAUTHORIZED
    assert invalid.status_code == httpx.codes.UNAUTHORIZED
    assert AUTH_VALUE not in missing.text
    assert AUTH_VALUE not in invalid.text
    assert valid.status_code == httpx.codes.OK


async def test__context_api__runs_event_prompt_and_response_flow(
    api_app: FastAPI,
    context_service: ContextCaptureService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST adapters expose the canonical event-to-response lifecycle."""
    api_app.dependency_overrides[get_context_capture_service] = lambda: context_service
    monkeypatch.setattr(SETTINGS, "context_api_token", SecretStr(AUTH_VALUE))
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://backplane.test",
        headers=HEADERS,
    ) as client:
        policy = await client.put(
            "/capture-policies/will",
            json={
                "timezone": "Europe/London",
                "baseline_prompt_limit": 1,
                "context_prompt_limit": 5,
                "cooldown_seconds": 0,
            },
        )
        event = await client.post(
            "/context/events",
            json=_event("home").model_dump(mode="json"),
        )
        event_id = ContextEventResult.model_validate(event.json()).event.id
        prompt = await client.post(
            "/capture-prompts/evaluate",
            json={
                "user_id": "will",
                "source": "appdaemon",
                "idempotency_key": "capture-home",
                "kind": "mood.capture",
                "budget_class": "context",
                "event_ids": [str(event_id)],
                "reason": "Arrived home",
                "wording": "How are you feeling?",
            },
        )
        prompt_id = CapturePromptEvaluationResult.model_validate(prompt.json()).prompt.id
        delivered = await client.post(
            f"/capture-prompts/{prompt_id}/delivered",
            json={"delivery_context": {"device": "phone"}},
        )
        response = await client.post(
            f"/capture-prompts/{prompt_id}/respond",
            json={
                "idempotency_key": "mood-7",
                "response_kind": "mood_rating",
                "payload": {"value": 7},
                "response_context": {"location": "home"},
            },
        )
        listed = await client.get(
            "/context",
            params={"user_id": "will", "kinds": "location.changed"},
        )

    assert policy.status_code == httpx.codes.OK
    assert event.status_code == httpx.codes.OK
    assert prompt.status_code == httpx.codes.OK
    assert prompt.json()["allowed"] is True
    assert delivered.json()["status"] == "delivered"
    assert response.json()["prompt"]["status"] == "responded"
    assert response.json()["response"]["payload"] == {"value": 7}
    listed_events = ContextEventList.model_validate(listed.json()).events
    assert [item.id for item in listed_events] == [event_id]
