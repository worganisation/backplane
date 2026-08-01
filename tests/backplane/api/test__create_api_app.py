"""Tests for the private REST API application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

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


async def test__create_api_app__returns_domain_errors_as_json(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API maps a missing daily-note section to a JSON error response."""
    _ = obsidian_vault
    response = await api_client.patch(
        "/obsidian/daily-note",
        json={"heading_path": ["Tasks"], "content": "Buy milk"},
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

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["markdown"] == "## Overview\n\nHouse systems."


async def test__create_api_app__finds_vault_notes(
    api_client: httpx.AsyncClient,
    obsidian_vault: AsyncPath,
) -> None:
    """The API searches vault notes by title."""
    _ = obsidian_vault
    _ = await api_client.post("/obsidian/entities/resource", json={"name": "MQTT Broker"})

    response = await api_client.get("/obsidian/search/find", params={"query": "MQTT"})

    assert response.status_code == 200
    assert response.json()["hits"][0]["title"] == "MQTT Broker"


async def test__create_api_app__does_not_expose_ha_passthrough(
    api_client: httpx.AsyncClient,
) -> None:
    """The REST API has no Home Assistant passthrough route."""
    response = await api_client.get("/ha_get_state")

    assert response.status_code == 404
