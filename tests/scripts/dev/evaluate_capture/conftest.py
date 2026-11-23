"""Actual capture schemas and an isolated Ollama-compatible HTTP endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from pydantic import AnyHttpUrl

from backplane.mcp.capture import build_capture_mcp
from backplane.utils.settings import SETTINGS
from scripts.dev.evaluate_capture import JSON_OBJECT, Message, Scenario

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pydantic import JsonValue
    from pytest_mock import MockerFixture


@pytest.fixture
async def capture_schemas() -> dict[str, dict[str, JsonValue]]:
    """Read production schemas without executing registered handlers."""
    return {
        tool.name: JSON_OBJECT.validate_python(tool.parameters)
        for tool in await build_capture_mcp().list_tools()
    }


@pytest.fixture
def sample_capture_scenario() -> Scenario:
    """Require the explicit project and original task detail."""
    return Scenario(
        name="project",
        text="Add check roof to Solar Plan",
        tool="capture_task",
        arguments={"project": "Solar Plan", "due": None},
        contains=["roof"],
    )


@pytest.fixture
def sample_capture_message() -> Message:
    """Return one schema-valid proposal with the request's operation prefix."""
    return Message.model_validate({
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": "capture_task",
                    "arguments": '{"description":"roof","project":"Solar Plan","idempotency_key":"request-1"}',
                },
            },
        ],
    })


class OllamaReply(TypedDict):
    """Status and JSON body returned by the isolated test server."""

    status: int
    body: dict[str, JsonValue]


@pytest.fixture
def ollama_reply() -> OllamaReply:
    """Default to a transport failure without reaching a real model."""
    return {"status": 503, "body": {"error": "unavailable"}}


@pytest.fixture
async def ollama_requests(
    mocker: MockerFixture,
    ollama_reply: OllamaReply,
) -> AsyncGenerator[list[dict[str, JsonValue]]]:
    """Serve controlled completions without a model.

    Yields:
        Requests received by the isolated HTTP server.
    """
    requests: list[dict[str, JsonValue]] = []

    async def respond(request: web.Request) -> web.Response:
        requests.append(JSON_OBJECT.validate_json(await request.text()))
        return web.json_response(ollama_reply["body"], status=ollama_reply["status"])

    app = web.Application()
    app.router.add_post("/v1/chat/completions", respond)
    async with TestServer(app) as server:
        _ = mocker.patch.object(
            SETTINGS,
            "ollama_base_url",
            AnyHttpUrl(str(server.make_url("/v1"))),
        )
        yield requests
