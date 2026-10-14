"""Tests for which text is passed to task metadata extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backplane.services.obsidian import ObsidianService
from backplane.services.tasks import TaskMetadata, TaskService
from backplane.utils import VAULT_PATHS, enums, today

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from backplane.utils.async_path import AsyncPath


@pytest.mark.anyio
async def test__create_task_keeps_matched_capture_context_for_short_request(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """A short request retains both its text and the capture's useful background."""
    capture_date = today().isoformat()
    capture_text = (
        "Add Jordan's calendar feed to the shared dashboard and notify them "
        "when meetings change."
    )
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await board.write_text("## Backlog\n\n", encoding="utf-8")
    _ = await inbox.write_text(
        f"""# {capture_date}

## 14:30

{capture_text}
""",
        encoding="utf-8",
    )

    metadata = TaskMetadata(
        title="Stub",
        domains=[],
        resources=[],
        projects=[],
        people=["Jordan"],
        priority=enums.Priority.MEDIUM,
        effort=enums.Effort.MEDIUM,
        next_action="",
    )
    extract = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        new=mocker.AsyncMock(return_value=metadata),
    )

    _ = await TaskService.create_task("calendar dashboard")

    _ = extract.assert_awaited_once_with(
        "Current task request (authoritative):\ncalendar dashboard\n\n"
        "Linked inbox capture (background context; the current request takes "
        f"precedence if details differ):\n{capture_text}",
        None,
        None,
        fallback_description="calendar dashboard",
    )


@pytest.mark.parametrize("explicit_link", [False, True])
async def test__create_task_preserves_expanded_request_with_capture_provenance(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
    *,
    explicit_link: bool,
) -> None:
    """Explicit and fuzzy links retain new details in metadata and the task body."""
    capture_date = today().isoformat()
    capture_id = f"{capture_date}T14:30"
    capture_text = "Build a garden dashboard"
    description = (
        "Build a garden dashboard with soil moisture graphs and a frost alert\n"
        "Send the frost alert to Jordan."
    )
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await board.write_text("## Backlog\n\n", encoding="utf-8")
    _ = await inbox.write_text(
        f"# {capture_date}\n\n## 14:30\n\n{capture_text}\n",
        encoding="utf-8",
    )
    metadata = TaskMetadata(
        title="Build garden dashboard",
        domains=[],
        resources=[],
        projects=[],
        people=[],
    )
    extract = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        new=mocker.AsyncMock(return_value=metadata),
    )

    result = await TaskService.create_task(
        description,
        link_capture_id=capture_id if explicit_link else None,
    )

    assert result.matched_capture_id == capture_id
    _ = extract.assert_awaited_once_with(
        f"Current task request (authoritative):\n{description}\n\n"
        "Linked inbox capture (background context; the current request takes "
        f"precedence if details differ):\n{capture_text}",
        None,
        None,
        fallback_description=description,
    )
    note = await (obsidian_vault / result.path).read_text(encoding="utf-8")
    assert (
        "## Description\n\n"
        "> Build a garden dashboard with soil moisture graphs and a frost alert\n"
        "> Send the frost alert to Jordan.\n\n"
    ) in note
    assert f"source_capture: {capture_id}\n" in note
    assert (
        f"## Source Capture\n\n[[Inbox/Ideas|Ideas]] ({capture_id})\n\n> {capture_text}\n"
    ) in note
    inbox_text = await inbox.read_text(encoding="utf-8")
    assert capture_text in inbox_text
    assert f"↗ {result.metadata.canonical_link}" in inbox_text


@pytest.mark.parametrize("explicit_link", [False, True])
async def test__create_task_linked_fallback_title_uses_current_request(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
    *,
    explicit_link: bool,
) -> None:
    """Model failures use the raw request for titles and filenames, without labels."""
    capture_date = today().isoformat()
    capture_id = f"{capture_date}T14:30"
    capture_text = "Build a garden dashboard"
    description = "Build a garden dashboard with soil moisture graphs and a frost alert"
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    board = obsidian_vault / VAULT_PATHS.task_board_path
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await board.write_text("## Backlog\n\n", encoding="utf-8")
    _ = await inbox.write_text(
        f"# {capture_date}\n\n## 14:30\n\n{capture_text}\n",
        encoding="utf-8",
    )
    _ = mocker.patch(
        "backplane.services.tasks._metadata_catalog_prompt",
        new=mocker.AsyncMock(return_value=""),
    )
    agent = mocker.Mock()
    agent.run = mocker.AsyncMock(side_effect=RuntimeError("Model unavailable"))
    _ = mocker.patch("backplane.services.tasks._metadata_agent", return_value=agent)

    result = await TaskService.create_task(
        description,
        link_capture_id=capture_id if explicit_link else None,
    )

    assert result.matched_capture_id == capture_id
    assert result.title == description[:60]
    assert result.path.name == f"{description[:60]}.md"
    assert await (obsidian_vault / result.path).exists()
    agent.run.assert_awaited_once_with(
        f"Task description: Current task request (authoritative):\n{description}\n\n"
        "Linked inbox capture (background context; the current request takes "
        f"precedence if details differ):\n{capture_text}",
    )
