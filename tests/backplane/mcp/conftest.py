"""Shared fixtures for Backplane MCP tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration

from backplane.mcp.public import create_public_mcp_app
from backplane.utils.async_path import AsyncPath
from backplane.utils.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pytest_mock import MockerFixture
    from starlette.applications import Starlette

PUBLIC_MCP_BASE_URL: str = "https://backplane-mcp.example.com"
_TEST_OAUTH_CREDENTIAL: str = "test-oauth-credential"
_FAKE_HA_MCP = FastMCP("Fake HA MCP")


@_FAKE_HA_MCP.tool
def ha_get_state(entity_id: str) -> dict[str, str]:
    """Return a fake entity state."""
    return {"entity_id": entity_id, "state": "off"}


@_FAKE_HA_MCP.tool
def ha_call_service(
    domain: str,
    service: str,
    target: dict[str, object],
) -> dict[str, bool]:
    """Pretend to call a Home Assistant service."""
    _ = domain, service, target
    return {"changed": True}


@_FAKE_HA_MCP.resource("ha://config")
def ha_config() -> str:
    """Return fake Home Assistant configuration."""
    return '{"location_name": "Home"}'


@_FAKE_HA_MCP.resource("ha://state/{entity_id}")
def ha_state_resource(entity_id: str) -> str:
    """Return a fake templated entity state."""
    return f'{{"entity_id": "{entity_id}", "state": "off"}}'


@_FAKE_HA_MCP.prompt
def ha_control_prompt(area: str) -> str:
    """Return a fake Home Assistant control prompt."""
    return f"Control Home Assistant devices in {area}."


@pytest.fixture
def sample_fake_ha_mcp() -> FastMCP[None]:
    """Return the in-process fake HA MCP server used by upstream tests."""
    return _FAKE_HA_MCP


@pytest.fixture
def mcp_with_ha_namespace_collision() -> FastMCP[None]:
    """Return an MCP server with a local tool in the HA namespace."""
    mcp: FastMCP[None] = FastMCP("Collision")

    def local_tool() -> None:
        """Provide a colliding local tool."""

    _ = mcp.tool(name="ha_local_tool")(local_tool)
    return mcp


@pytest.fixture
def sample_oidc_configuration() -> OIDCConfiguration:
    """Return a minimal Authentik-like OIDC configuration for public MCP tests."""
    return OIDCConfiguration.model_validate(
        {
            "strict": False,
            "issuer": "https://auth.example.com/application/o/backplane-mcp/",
            "authorization_endpoint": (
                "https://auth.example.com/application/o/authorize/"
            ),
            "token_endpoint": "https://auth.example.com/application/o/token/",
            "jwks_uri": "https://auth.example.com/application/o/jwks/",
            "introspection_endpoint": (
                "https://auth.example.com/application/o/introspect/"
            ),
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        },
    )


def _public_mcp_oauth_settings(**ha_overrides: object) -> Settings:
    """Build Settings for the public MCP OAuth test app."""
    return Settings.model_validate(
        {
            "obsidian_vault_path": AsyncPath("/tmp/vault"),
            "mcp_public_base_url": PUBLIC_MCP_BASE_URL,
            "mcp_oidc_config_url": (
                "https://auth.example.com/application/o/backplane-mcp/"
                ".well-known/openid-configuration"
            ),
            "mcp_oidc_client_id": "client-id",
            "mcp_oidc_client_secret": _TEST_OAUTH_CREDENTIAL,
            **ha_overrides,
        },
    )


@pytest.fixture
def public_mcp_http_app(
    mocker: MockerFixture,
    sample_oidc_configuration: OIDCConfiguration,
) -> Starlette:
    """Create a public MCP HTTP app configured for testing with mocked OIDC.

    Returns:
        A Starlette ASGI app with test settings and mocked OIDC configuration.
    """
    settings = _public_mcp_oauth_settings()
    _ = mocker.patch("backplane.mcp.auth.SETTINGS", settings)
    _ = mocker.patch("backplane.mcp.asgi.SETTINGS", settings)
    _ = mocker.patch(
        "backplane.mcp.auth.OIDCConfiguration.get_oidc_configuration",
        return_value=sample_oidc_configuration,
    )

    return create_public_mcp_app()


@pytest.fixture
def public_mcp_http_app_with_ha(
    mocker: MockerFixture,
    sample_oidc_configuration: OIDCConfiguration,
) -> Starlette:
    """Create a public MCP HTTP app with HA upstream enabled and mocked OIDC.

    Returns:
        A Starlette ASGI app exposing authenticated ``/mcp`` with HA tools mounted.
    """
    settings = _public_mcp_oauth_settings(
        ha_mcp_enabled=True,
        ha_mcp_url="http://fake-ha-mcp.example.com/mcp",
        ha_mcp_namespace="ha",
        # Trusted ChatGPT clients receive the HA scope; untrusted localhost
        # clients in the HTTP OAuth tests stay on baseline scopes only.
        allowed_client_redirect_uri_patterns=[
            "https://chatgpt.com/connector/oauth/*",
            "http://127.0.0.1:6274/oauth/callback/debug",
        ],
        ha_mcp_client_redirect_uri_patterns=("https://chatgpt.com/connector/oauth/*",),
    )
    _ = mocker.patch("backplane.mcp.auth.SETTINGS", settings)
    _ = mocker.patch("backplane.mcp.asgi.SETTINGS", settings)
    _ = mocker.patch(
        "backplane.mcp.auth.OIDCConfiguration.get_oidc_configuration",
        return_value=sample_oidc_configuration,
    )
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.create_proxy",
        return_value=_FAKE_HA_MCP,
    )

    return create_public_mcp_app()


@pytest.fixture
async def public_mcp_client(
    public_mcp_http_app: Starlette,
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the public MCP ASGI app.

    Yields:
        Async HTTP client bound to the public MCP ASGI app.
    """
    transport = httpx.ASGITransport(app=public_mcp_http_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=PUBLIC_MCP_BASE_URL,
    ) as client:
        yield client


@pytest.fixture
async def public_mcp_client_with_ha(
    public_mcp_http_app_with_ha: Starlette,
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the public MCP ASGI app with HA upstream enabled.

    Yields:
        Async HTTP client bound to the HA-enabled public MCP ASGI app.
    """
    transport = httpx.ASGITransport(app=public_mcp_http_app_with_ha)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=PUBLIC_MCP_BASE_URL,
    ) as client:
        yield client
