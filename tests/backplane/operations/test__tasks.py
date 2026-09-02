"""Tests for shared task-result operations."""

from __future__ import annotations

from backplane.operations.tasks import TaskCreationOutcome, build_task_capture_messages
from backplane.services.tasks import CaptureCandidate


def test__build_task_capture_messages__preserves_adapter_specific_guidance() -> None:
    """The shared builder preserves each adapter's capture-link wording."""
    outcome = TaskCreationOutcome.model_construct(
        matched_capture_id=None,
        candidate_captures=[
            CaptureCandidate(
                id="2026-05-17T01:44",
                text="I need to create reminder notifications for the mood tracker",
            ),
        ],
    )

    api_message = build_task_capture_messages(outcome, style="api")
    mcp_message = build_task_capture_messages(
        outcome,
        style="mcp",
        candidate_snippet_max_len=80,
    )

    assert "link it with that capture ID" in api_message[0]
    assert "say 'link it to 2026-05-17T01:44'" in mcp_message[0]
