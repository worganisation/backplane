"""Exercise real HTTP source shapes and bounded local-model responses."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import aiohttp
import pytest
import yarl
from aiohttp import web

from backplane.diary.collector import MOOD, collect_day
from backplane.diary.render import generate_narrative
from backplane.utils import SETTINGS, exc

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def source_server(unused_tcp_port: int) -> AsyncIterator[yarl.URL]:
    """Serve HA REST objects and local completion responses over actual HTTP.

    Yields:
        Local source endpoint.
    """
    now = dt.datetime.now(dt.UTC)
    date = now.date().isoformat()

    async def states(request: web.Request) -> web.Response:
        _ = await request.read()
        assert request.headers["Authorization"] == "Bearer fixture-token"
        common = {"last_changed": now.isoformat(), "last_updated": now.isoformat()}
        return web.json_response([
            {
                **common,
                "entity_id": MOOD,
                "state": "none",
                "attributes": {
                    "diary_history_start": date,
                    "diary_history_end": date,
                    "diary_checkins": [],
                },
            },
            {
                **common,
                "entity_id": "sensor.will_habit_1_status",
                "state": "due",
                "attributes": {
                    "configured": True,
                    "habit_name": "Water",
                    "completion_history": {date: 0},
                },
            },
        ])

    async def history(request: web.Request) -> web.Response:
        _ = await request.read()
        return web.json_response([])

    async def calendar(request: web.Request) -> web.Response:
        _ = await request.read()
        return web.json_response([
            {
                "summary": "All day title",
                "start": {"date": date},
                "end": {"date": (now.date() + dt.timedelta(days=1)).isoformat()},
                "description": "Do not copy this",
            },
        ])

    async def completion(request: web.Request) -> web.Response:
        body: object = await request.json()
        assert isinstance(body, dict)
        assert "tools" not in body
        return web.json_response({
            "choices": [{"message": {"content": "Will recorded a day."}}],
        })

    app = web.Application()
    app.router.add_get("/api/states", states)
    app.router.add_get("/api/history/period/{start}", history)
    app.router.add_get("/api/calendars/{calendar}", calendar)
    app.router.add_post("/v1/chat/completions", completion)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    try:
        yield yarl.URL(f"http://127.0.0.1:{unused_tcp_port}")
    finally:
        await runner.cleanup()


async def test_rest_source_shapes_and_narrative(
    source_server: yarl.URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real HA date objects produce a saved-ready snapshot and local prose."""
    monkeypatch.setattr(SETTINGS, "home_assistant_url", source_server)
    monkeypatch.setattr(SETTINGS, "home_assistant_token", "fixture-token")
    monkeypatch.setattr(SETTINGS, "ollama_base_url", str(source_server / "v1"))
    result = await collect_day(dt.datetime.now(dt.UTC).date())
    assert len(result.entries) == 2
    assert not any(item.startswith("Dated") for item in result.missing)
    assert "Do not copy" not in result.model_dump_json()
    assert await generate_narrative("Scheduled: All day title") == "Will recorded a day."


async def test_missing_credentials_and_invalid_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuration gaps and out-of-window requests fail before any HTTP call."""
    with pytest.raises(exc.BadRequestError):
        _ = await collect_day(dt.date(2000, 1, 1))
    monkeypatch.setattr(SETTINGS, "home_assistant_url", None)
    with pytest.raises(exc.UserError):
        _ = await collect_day(dt.datetime.now(dt.UTC).date())


async def test_source_http_error_is_not_an_empty_day(
    source_server: yarl.URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed endpoint cannot be mistaken for a complete empty snapshot."""
    monkeypatch.setattr(SETTINGS, "home_assistant_url", source_server / "missing")
    monkeypatch.setattr(SETTINGS, "home_assistant_token", "fixture-token")
    with pytest.raises(aiohttp.ClientResponseError):
        _ = await collect_day(dt.datetime.now(dt.UTC).date())
