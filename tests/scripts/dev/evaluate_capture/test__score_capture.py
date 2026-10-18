"""Check grounded capture proposals without dispatching their functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts.dev.evaluate_capture import Message, Scenario, score

if TYPE_CHECKING:
    from pydantic import JsonValue


def test__score_accepts_explicit_project(
    capture_schemas: dict[str, dict[str, JsonValue]],
    sample_capture_scenario: Scenario,
    sample_capture_message: Message,
) -> None:
    """Schema-valid proposals preserve the user's explicit project and wording."""
    assert (
        score(
            sample_capture_scenario,
            sample_capture_message,
            capture_schemas,
            "request-",
        )
        == []
    )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ('{"description":"Check roof","idempotency_key":"request-1"}', "project:"),
        ('{"description":"Check roof","project":"Solar Plan"}', "required property"),
        (
            '{"description":"Check roof","project":"Solar Plan","idempotency_key":null}',
            "not of type",
        ),
        (
            '{"description":"Check roof","project":"Solar Plan","idempotency_key":"generic"}',
            "request's prefix",
        ),
        (
            '{"description":"roof","project":"Solar Plan","idempotency_key":"request-1","due":"2026-02-30"}',
            "due:",
        ),
        (
            '{"description":"Different task","project":"Solar Plan","idempotency_key":"request-1"}',
            "wording missing",
        ),
        ("[]", "JSON object"),
        ("not json", "JSON object"),
    ],
)
def test__score_rejects_invalid_arguments(
    capture_schemas: dict[str, dict[str, JsonValue]],
    sample_capture_scenario: Scenario,
    sample_capture_message: Message,
    arguments: str,
    expected: str,
) -> None:
    """Missing keys, fabricated fields and malformed proposals are reported as failures."""
    function = sample_capture_message.tool_calls[0].function.model_copy(
        update={"arguments": arguments},
    )
    call = sample_capture_message.tool_calls[0].model_copy(update={"function": function})
    message = sample_capture_message.model_copy(update={"tool_calls": [call]})

    assert any(
        expected in issue
        for issue in score(sample_capture_scenario, message, capture_schemas, "request-")
    )


@pytest.mark.parametrize("name", ["record_diary", "invented_tool"])
def test__score_rejects_wrong_routing(
    capture_schemas: dict[str, dict[str, JsonValue]],
    sample_capture_scenario: Scenario,
    sample_capture_message: Message,
    name: str,
) -> None:
    """A different or unknown tool cannot pass a routing check."""
    function = sample_capture_message.tool_calls[0].function.model_copy(
        update={"name": name},
    )
    call = sample_capture_message.tool_calls[0].model_copy(update={"function": function})

    assert score(
        sample_capture_scenario,
        Message(tool_calls=[call]),
        capture_schemas,
        "request-",
    )


@pytest.mark.parametrize(
    ("speech", "passes"),
    [("Which day do you mean?", True), ("Saved", False), ("", False)],
)
def test__score_requires_clarification_without_a_capture(
    capture_schemas: dict[str, dict[str, JsonValue]],
    speech: str,
    *,
    passes: bool,
) -> None:
    """An ambiguous request needs a question rather than a fabricated save."""
    scenario = Scenario(name="ambiguous", text="That day", tool=None, clarification=True)

    assert (
        bool(score(scenario, Message(content=speech), capture_schemas, "request-"))
        is not passes
    )


def test__score_rejects_capture_for_a_question(
    capture_schemas: dict[str, dict[str, JsonValue]],
    sample_capture_message: Message,
) -> None:
    """Valid schemas do not excuse capturing ordinary questions."""
    scenario = Scenario(name="question", text="What time is it?", tool=None)

    assert score(scenario, sample_capture_message, capture_schemas, "request-")


def test__score_validates_diary_calendar_date(
    capture_schemas: dict[str, dict[str, JsonValue]],
    sample_capture_message: Message,
) -> None:
    """The actual diary schema rejects impossible dates rather than just date-shaped strings."""
    scenario = Scenario(name="diary", text="I walked", tool="record_diary")
    function = sample_capture_message.tool_calls[0].function.model_copy(
        update={
            "name": "record_diary",
            "arguments": '{"content":"I walked","idempotency_key":"request-1","date":"2026-02-30"}',
        },
    )
    call = sample_capture_message.tool_calls[0].model_copy(update={"function": function})

    assert any(
        "date" in issue
        for issue in score(
            scenario,
            Message(tool_calls=[call]),
            capture_schemas,
            "request-",
        )
    )
