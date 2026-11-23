"""Exercise the manual runner's request and failure reporting boundaries."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scripts.dev.evaluate_capture import ROOT, evaluate

if TYPE_CHECKING:
    import pytest
    from pydantic import JsonValue
    from pytest_mock import MockerFixture

    from tests.scripts.dev.evaluate_capture.conftest import OllamaReply


async def test__evaluate_reports_transport_failures_without_writes(
    ollama_requests: list[dict[str, JsonValue]],
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    """HTTP failures produce a failed report and cannot reach capture write operations."""
    mock_diary = mocker.patch("backplane.mcp.obsidian.record_diary")
    mock_idea = mocker.patch("backplane.mcp.obsidian.record_idea")
    mock_task = mocker.patch("backplane.mcp.tasks.capture_task")

    assert await evaluate(model="local-test-model") == 1

    report = json.loads(capsys.readouterr().out)
    assert (
        report["failed"]
        == len(ollama_requests)
        == len(
            json.loads((ROOT / "scripts/fixtures/capture-evaluation.json").read_text()),
        )
    )
    assert all(request["model"] == "local-test-model" for request in ollama_requests)
    assert all("tools" in request for request in ollama_requests)
    mock_diary.assert_not_called()
    mock_idea.assert_not_called()
    mock_task.assert_not_called()


async def test__evaluate_dry_run_does_not_contact_ollama(
    ollama_requests: list[dict[str, JsonValue]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Preview renders actual deployment prompts while sending no HTTP requests."""
    assert await evaluate(dry_run=True) == 0

    report = json.loads(capsys.readouterr().out)
    assert ollama_requests == []
    assert report["dry_run"] is True
    assert "Today: 2026-10-18" in report["cases"][0]["prompt"]
    assert "Yesterday: 2026-10-17" in report["cases"][0]["prompt"]


async def test__evaluate_never_executes_successful_tool_proposals(
    ollama_requests: list[dict[str, JsonValue]],
    ollama_reply: OllamaReply,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    """Returned tool proposals are reported and scored without calling write handlers."""
    mock_diary = mocker.patch("backplane.mcp.obsidian.record_diary")
    ollama_reply["status"] = 200
    ollama_reply["body"] = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "record_diary",
                                "arguments": '{"content":"Synthetic capture","idempotency_key":"generic"}',
                            },
                        },
                    ],
                },
            },
        ],
    }

    assert await evaluate() == 1

    report = json.loads(capsys.readouterr().out)
    assert len(ollama_requests) == len(
        json.loads((ROOT / "scripts/fixtures/capture-evaluation.json").read_text()),
    )
    assert all(case["response"] is not None for case in report["cases"])
    mock_diary.assert_not_called()
