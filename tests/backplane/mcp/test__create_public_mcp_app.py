"""Tests for the public MCP HTTP app factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration

from backplane.mcp.public import create_public_mcp_app
from backplane.utils.async_path import AsyncPath
from backplane.utils.settings import Settings

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


async def test__create_public_mcp_app__builds_oauth_protected_http_app(
    mocker: MockerFixture,
    sample_oidc_configuration: OIDCConfiguration,
) -> None:
    """The public MCP app factory wires OAuth auth and exposes the /mcp route."""
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": AsyncPath("/tmp/vault"),
            "mcp_public_base_url": "https://backplane-mcp.example.com",
            "mcp_oidc_config_url": (
                "https://auth.example.com/application/o/backplane-mcp/"
                ".well-known/openid-configuration"
            ),
            "mcp_oidc_client_id": "client-id",
            "mcp_oidc_client_secret": "test-oauth-credential",
        },
    )
    mocker.patch("backplane.mcp.auth.SETTINGS", settings)
    mocker.patch(
        "backplane.mcp.auth.OIDCConfiguration.get_oidc_configuration",
        return_value=sample_oidc_configuration,
    )

    app = create_public_mcp_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://backplane-mcp.example.com",
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == httpx.codes.OK
    assert response.json()["resource"] == "https://backplane-mcp.example.com/mcp"


def test__main__starts_public_mcp_server(mocker: MockerFixture) -> None:
    """The public entrypoint main function serves the app via uvicorn."""
    mock_app = mocker.Mock()
    mocker.patch("backplane.mcp.public.create_public_mcp_app", return_value=mock_app)
    mock_uvloop = mocker.patch("backplane.mcp.public.uvloop.run")
    mock_server = mocker.patch("backplane.mcp.public.uvicorn.Server")
    mock_config = mocker.patch("backplane.mcp.public.uvicorn.Config")

    from backplane.mcp.public import main  # ruff:ignore[import-outside-top-level]

    main()

    mock_config.assert_called_once_with(
        mock_app,
        host="0.0.0.0",
        port=8001,
        log_level="info",
    )
    mock_server.assert_called_once_with(mock_config.return_value)
    mock_uvloop.assert_called_once_with(mock_server.return_value.serve.return_value)
