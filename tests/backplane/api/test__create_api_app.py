"""Tests for the private REST API application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backplane.services.obsidian import ObsidianService
from backplane.services.tasks import TaskMetadata
from backplane.utils import VAULT_PATHS, enums, today

if TYPE_CHECKING:
    import httpx
    from pytest_mock import MockerFixture

    from backplane.utils.async_path import AsyncPath


async def test__create_api_app__returns_health_status(
    api_client: httpx.AsyncClient,
) -> None:
    """The API exposes a health endpoint."""
    response = await api_client.get("/health/check")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test__create_api_app__updates_daily_note_section(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API updates a requested daily-note section."""
    _ = obsidian_vault
    response = await api_client.patch(
        "/obsidian/daily-note",
        json={
            "heading_path": ["Tasks"],
            "content": "Buy milk",
            "create_section_if_not_exists": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["markdown"] == "## Tasks\n\nBuy milk"


async def test__create_api_app__reads_daily_notes_and_records_ideas(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API reads a created daily note and writes to the idea inbox."""
    note_date = "2026-08-01"
    _ = await api_client.patch(
        "/obsidian/daily-note",
        json={
            "heading_path": ["Journal"],
            "content": "A useful day.",
            "create_section_if_not_exists": True,
            "date": note_date,
        },
    )
    ideas_path = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    await ideas_path.parent.mkdir(parents=True, exist_ok=True)
    _ = await ideas_path.write_text("", encoding="utf-8")

    daily_note = await api_client.get(
        "/obsidian/daily-note",
        params={"date": note_date},
    )
    idea = await api_client.post(
        "/obsidian/ideas",
        json={"idea": "Correlate visits with calendar events."},
    )

    assert daily_note.status_code == 200
    assert "A useful day." in daily_note.json()["markdown"]
    assert idea.status_code == 201
    assert idea.json()["message"] == "Idea recorded successfully."
    assert "Correlate visits with calendar events." in await ideas_path.read_text(
        encoding="utf-8",
    )


async def test__create_api_app__returns_domain_errors_as_json(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API maps a missing daily-note section to a JSON error response."""
    _ = obsidian_vault
    response = await api_client.patch(
        "/obsidian/daily-note",
        json={
            "heading_path": ["Tasks"],
            "content": "Buy milk",
            "date": "2026-08-01",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["section"] == "Saturday, August 1st 2026"


async def test__create_api_app__creates_and_updates_entity_sections(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API creates an entity and updates one of its sections."""
    _ = obsidian_vault
    created = await api_client.post("/obsidian/entities/domain", json={"name": "Home"})
    updated = await api_client.patch(
        "/obsidian/entities/domain/Home/section",
        json={"heading_path": ["Overview"], "content": "House systems."},
    )
    listed = await api_client.get("/obsidian/entities/domain")
    entity = await api_client.get("/obsidian/entities/domain/Home")
    sections = await api_client.get("/obsidian/entities/domain/Home/sections")
    section = await api_client.get(
        "/obsidian/entities/domain/Home/section",
        params={"heading_path": "Overview"},
    )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["markdown"] == "## Overview\n\nHouse systems."
    assert listed.json()["names"] == ["Home"]
    assert "# Home" in entity.json()["markdown"]
    assert any(item["heading"] == "Overview" for item in sections.json()["sections"])
    assert section.json()["markdown"] == "## Overview\n\nHouse systems."


async def test__create_api_app__finds_vault_notes(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API searches vault notes by title."""
    _ = obsidian_vault
    _ = await api_client.post("/obsidian/entities/resource", json={"name": "MQTT Broker"})
    _ = await api_client.patch(
        "/obsidian/entities/resource/MQTT Broker/section",
        json={"heading_path": ["Overview"], "content": "Carries sensor events."},
    )

    response = await api_client.get("/obsidian/search/find", params={"query": "MQTT"})
    content = await api_client.get(
        "/obsidian/search/content",
        params={"query": "sensor events"},
    )

    assert response.status_code == 200
    assert response.json()["hits"][0]["title"] == "MQTT Broker"
    assert content.status_code == 200
    assert content.json()["hits"][0]["title"] == "MQTT Broker"


async def test__create_api_app__moves_notes(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API moves a vault note and returns the destination path."""
    source = obsidian_vault / "Inbox" / "Move me.md"
    await source.parent.mkdir(parents=True, exist_ok=True)
    _ = await source.write_text("# Move me\n", encoding="utf-8")

    response = await api_client.post(
        "/obsidian/notes/move",
        json={
            "source_path": "Inbox/Move me.md",
            "destination_path": "Archive/Moved.md",
        },
    )

    assert response.status_code == 200
    assert response.json()["path"] == "Archive/Moved.md"
    assert await (obsidian_vault / "Archive" / "Moved.md").exists()


async def test__create_api_app__creates_tasks(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """The API creates a structured task through the shared task service."""
    task_board = obsidian_vault / VAULT_PATHS.task_board_path
    await task_board.parent.mkdir(parents=True, exist_ok=True)
    _ = await task_board.write_text("## Backlog\n\n", encoding="utf-8")
    metadata = TaskMetadata(
        title="Review backup logs",
        domains=[],
        resources=[],
        projects=[],
        people=[],
        priority=enums.Priority.MEDIUM,
        effort=enums.Effort.SMALL,
        next_action="Open the latest backup report.",
    )
    _ = mocker.patch(
        "backplane.services.tasks._extract_metadata",
        new=mocker.AsyncMock(return_value=metadata),
    )

    response = await api_client.post(
        "/obsidian/tasks",
        json={"description": "Review backup logs"},
    )

    assert response.status_code == 201
    assert response.json()["slug"] == "review-backup-logs"
    assert await (
        obsidian_vault / VAULT_PATHS.task_notes_dir / "Review backup logs.md"
    ).exists()


async def test__create_api_app__links_tasks_and_maps_missing_resources(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The task-link route succeeds and maps missing resources to HTTP 404."""
    capture_date = today().isoformat()
    inbox = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    task = obsidian_vault / VAULT_PATHS.task_notes_dir / "review-backup-logs.md"
    await inbox.parent.mkdir(parents=True, exist_ok=True)
    await task.parent.mkdir(parents=True, exist_ok=True)
    _ = await inbox.write_text(
        f"# {capture_date}\n\n## 09:15\n\nReview backup logs\n",
        encoding="utf-8",
    )
    _ = await task.write_text(
        "---\ntype: task\nsource_capture:\n---\n# Review backup logs\n",
        encoding="utf-8",
    )

    linked = await api_client.post(
        "/obsidian/tasks/review-backup-logs/link-capture",
        json={"capture_id": f"{capture_date}T09:15"},
    )
    missing_capture = await api_client.post(
        "/obsidian/tasks/review-backup-logs/link-capture",
        json={"capture_id": "2000-01-01T00:00"},
    )
    missing_task = await api_client.post(
        "/obsidian/tasks/missing-task/link-capture",
        json={"capture_id": f"{capture_date}T09:15"},
    )

    assert linked.status_code == 200
    assert "linked to capture" in linked.json()["message"]
    assert missing_capture.status_code == 404
    assert missing_capture.json()["detail"]["resource"] == "capture"
    assert missing_task.status_code == 404
    assert missing_task.json()["detail"]["resource"] == "task"


async def test__create_api_app__does_not_expose_ha_passthrough(
    api_client: httpx.AsyncClient,
) -> None:
    """The REST API has no Home Assistant passthrough route."""
    response = await api_client.get("/ha_get_state")

    assert response.status_code == 404
