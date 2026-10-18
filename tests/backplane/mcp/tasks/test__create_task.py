"""Tests for the create_task MCP tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backplane.mcp import tasks
from backplane.services.tasks import CaptureCandidate, CreateTaskResult
from backplane.utils import enums

_CANDIDATE_SNIPPET_MAX_LEN = 80

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    (
        "description",
        "title",
        "due",
        "priority",
        "returned_title",
        "returned_slug",
    ),
    [
        (
            "Review backup logs",
            None,
            None,
            None,
            "Review backup logs",
            "review-backup-logs",
        ),
        (
            "Install the hallway sensor before Friday",
            "Install hallway sensor",
            "2026-05-29",
            enums.Priority.HIGH,
            "Install hallway sensor",
            "install-hallway-sensor",
        ),
    ],
)
async def test__create_task__forwards_fields_to_task_service(
    mocker: MockerFixture,
    make_create_task_result: Callable[..., CreateTaskResult],
    description: str,
    title: str | None,
    due: str | None,
    priority: enums.Priority | None,
    returned_title: str,
    returned_slug: str,
) -> None:
    """Task fields are forwarded while omitted optional values default to None."""
    mock_create_task = mocker.AsyncMock(
        return_value=make_create_task_result(title=returned_title, slug=returned_slug),
    )
    mock_task_service = mocker.patch("backplane.mcp.tasks.TaskService")
    mock_task_service.return_value.create_task = mock_create_task  # pyright: ignore[reportAny]

    result = await tasks.create_task(
        description=description,
        title=title,
        due=due,
        priority=priority,
        link_capture_id=None,
        idempotency_key=None,
        project=None,
    )

    assert result.metadata.title == returned_title
    assert result.slug == returned_slug
    assert result.messages == []
    mock_task_service.assert_called_once_with()
    mock_create_task.assert_awaited_once_with(
        description,
        title=title,
        due=due,
        priority=priority,
        link_capture_id=None,
        idempotency_key=None,
        project=None,
    )


async def test__create_task__matched_capture_is_included_in_confirmation(
    mocker: MockerFixture,
    make_create_task_result: Callable[..., CreateTaskResult],
) -> None:
    """A matched inbox capture should be mentioned in the confirmation."""
    mock_create_task = mocker.AsyncMock(
        return_value=make_create_task_result(
            title="Review backup logs",
            slug="review-backup-logs",
            matched_capture_id="2026-05-25T21:15",
        ),
    )
    mock_task_service = mocker.patch("backplane.mcp.tasks.TaskService")
    mock_task_service.return_value.create_task = mock_create_task  # pyright: ignore[reportAny]

    result = await tasks.create_task(
        description="backup logs",
    )

    assert result.matched_capture_id == "2026-05-25T21:15"
    assert result.messages == ["Matched inbox capture from 2026-05-25T21:15."]


async def test__create_task__logs_success_response(
    mocker: MockerFixture,
    make_create_task_result: Callable[..., CreateTaskResult],
) -> None:
    """Successful task creation logs the service result and response string."""
    mock_info = mocker.patch("backplane.mcp.tasks.logger.info")
    mock_create_task = mocker.AsyncMock(
        return_value=make_create_task_result(
            title="Review backup logs",
            slug="review-backup-logs",
        ),
    )
    mock_task_service = mocker.patch("backplane.mcp.tasks.TaskService")
    mock_task_service.return_value.create_task = mock_create_task  # pyright: ignore[reportAny]

    _ = await tasks.create_task(description="Review backup logs")

    assert any(
        "create_task succeeded" in str(call.args[0])  # pyright: ignore[reportAny]
        for call in mock_info.call_args_list
    )


async def test__create_task__candidate_capture_is_included_in_confirmation(
    mocker: MockerFixture,
    make_create_task_result: Callable[..., CreateTaskResult],
) -> None:
    """Near matches are offered without failing task creation."""
    mock_create_task = mocker.AsyncMock(
        return_value=make_create_task_result(
            title="Update rain alert notification",
            slug="update-rain-alert-notification",
            candidate_captures=[
                CaptureCandidate(
                    id="2026-05-17T01:44",
                    text=("I need to create reminder notifications for the mood tracker"),
                ),
            ],
        ),
    )
    mock_task_service = mocker.patch("backplane.mcp.tasks.TaskService")
    mock_task_service.return_value.create_task = mock_create_task  # pyright: ignore[reportAny]

    result = await tasks.create_task(description="Update rain alert notification")

    assert result.candidate_captures == [
        CaptureCandidate(
            id="2026-05-17T01:44",
            text="I need to create reminder notifications for the mood tracker",
        ),
    ]
    assert "2026-05-17T01:44" in result.messages[0]
    assert (
        "I need to create reminder notifications for the mood tracker"
        in result.messages[0]
    )


async def test__create_task__long_candidate_snippet_is_truncated(
    mocker: MockerFixture,
    make_create_task_result: Callable[..., CreateTaskResult],
) -> None:
    """Long candidate snippets are truncated in the confirmation."""
    long_text = (
        "I need to investigate the automated backup verification system because "
        "the notifications have been failing intermittently for the past week"
    )
    mock_create_task = mocker.AsyncMock(
        return_value=make_create_task_result(
            title="Fix backup notifications",
            slug="fix-backup-notifications",
            candidate_captures=[
                CaptureCandidate(id="2026-05-17T01:44", text=long_text),
            ],
        ),
    )
    mock_task_service = mocker.patch("backplane.mcp.tasks.TaskService")
    mock_task_service.return_value.create_task = mock_create_task  # pyright: ignore[reportAny]

    result = await tasks.create_task(description="Fix backup notifications")

    message = result.messages[0]
    snippet = message.split("'")[1]
    assert snippet.endswith("...")
    assert len(snippet) == _CANDIDATE_SNIPPET_MAX_LEN


async def test__create_task__forwards_link_capture_id(
    mocker: MockerFixture,
    make_create_task_result: Callable[..., CreateTaskResult],
) -> None:
    """An explicit capture link is forwarded to the task service."""
    mock_create_task = mocker.AsyncMock(
        return_value=make_create_task_result(
            title="Review backup logs",
            slug="review-backup-logs",
            matched_capture_id="2026-05-25T21:15",
        ),
    )
    mock_task_service = mocker.patch("backplane.mcp.tasks.TaskService")
    mock_task_service.return_value.create_task = mock_create_task  # pyright: ignore[reportAny]

    _ = await tasks.create_task(
        description="backup logs",
        link_capture_id="2026-05-25T21:15",
        idempotency_key=None,
        project=None,
    )

    mock_create_task.assert_awaited_once_with(
        "backup logs",
        title=None,
        due=None,
        priority=None,
        link_capture_id="2026-05-25T21:15",
        idempotency_key=None,
        project=None,
    )


async def test__link_task_to_capture__forwards_fields(
    mocker: MockerFixture,
) -> None:
    """The follow-up linking tool delegates to the task service."""
    mock_link_capture = mocker.AsyncMock(
        return_value="Task review-backup-logs linked to capture 2026-05-25T21:15.",
    )
    mock_task_service = mocker.patch("backplane.mcp.tasks.TaskService")
    mock_task_service.return_value.link_capture = mock_link_capture  # pyright: ignore[reportAny]

    result = await tasks.link_task_to_capture(
        task_slug="review-backup-logs",
        capture_id="2026-05-25T21:15",
    )

    assert result == "Task review-backup-logs linked to capture 2026-05-25T21:15."
    mock_link_capture.assert_awaited_once_with(
        "review-backup-logs",
        "2026-05-25T21:15",
    )
