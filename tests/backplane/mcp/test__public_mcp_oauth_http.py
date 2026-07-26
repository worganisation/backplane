"""Integration checks for public MCP OAuth HTTP endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from backplane.mcp.auth import HA_MCP_SCOPE, MCP_BASELINE_SCOPE

_PUBLIC_MCP_BASE_URL = "https://backplane-mcp.example.com"
_EXPECTED_SCOPES = [MCP_BASELINE_SCOPE, "offline_access", HA_MCP_SCOPE]

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test__public_mcp_oauth__protected_resource_metadata_is_exposed(
    public_mcp_client: AsyncClient,
) -> None:
    """The public MCP HTTP app exposes OAuth protected resource metadata for /mcp."""
    response = await public_mcp_client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == httpx.codes.OK
    assert response.json() == {
        "resource": f"{_PUBLIC_MCP_BASE_URL}/mcp",
        "authorization_servers": [f"{_PUBLIC_MCP_BASE_URL}/"],
        "scopes_supported": _EXPECTED_SCOPES,
        "bearer_methods_supported": ["header"],
    }


async def test__public_mcp_oauth__authorization_server_metadata_supports_chatgpt_dcr(
    public_mcp_client: AsyncClient,
) -> None:
    """FastMCP exposes the authorization-server metadata ChatGPT uses for DCR and refresh."""
    response = await public_mcp_client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == httpx.codes.OK
    payload = response.json()
    assert payload["issuer"] == f"{_PUBLIC_MCP_BASE_URL}/"
    assert payload["registration_endpoint"] == f"{_PUBLIC_MCP_BASE_URL}/register"
    assert payload["scopes_supported"] == _EXPECTED_SCOPES
    assert "refresh_token" in payload["grant_types_supported"]
    assert payload["code_challenge_methods_supported"] == ["S256"]


async def test__public_mcp_oauth__discovery_uses_host_level_authorization_server_metadata(
    public_mcp_client: AsyncClient,
) -> None:
    """Protected-resource metadata links to host-level auth-server metadata (not /mcp suffix)."""
    protected = await public_mcp_client.get("/.well-known/oauth-protected-resource/mcp")
    auth_server_url = protected.json()["authorization_servers"][0]

    response = await public_mcp_client.get("/.well-known/oauth-authorization-server")
    suffix_response = await public_mcp_client.get(
        "/.well-known/oauth-authorization-server/mcp",
    )

    assert response.status_code == httpx.codes.OK
    assert response.json()["issuer"] == auth_server_url
    assert suffix_response.status_code == httpx.codes.NOT_FOUND


async def test__public_mcp_oauth__dynamic_client_registration_succeeds(
    public_mcp_client: AsyncClient,
) -> None:
    """ChatGPT can dynamically register against Backplane's /register endpoint."""
    response = await public_mcp_client.post(
        "/register",
        json={
            "redirect_uris": ["https://chatgpt.com/connector/oauth/example"],
        },
    )

    assert response.status_code == httpx.codes.CREATED
    payload = response.json()
    assert payload["redirect_uris"] == [
        "https://chatgpt.com/connector/oauth/example",
    ]
    assert payload["scope"] == " ".join(_EXPECTED_SCOPES)
    assert payload["client_id"]
    assert payload["client_secret"]


async def test__public_mcp_oauth__unauthenticated_post_mcp_returns_401(
    public_mcp_client: AsyncClient,
) -> None:
    """Unauthenticated MCP POST requests receive a WWW-Authenticate challenge."""
    response = await public_mcp_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert "WWW-Authenticate" in response.headers
    assert response.headers["WWW-Authenticate"].startswith("Bearer ")


async def test__public_mcp_oauth__unauthenticated_get_mcp_returns_401_not_405(
    public_mcp_client: AsyncClient,
) -> None:
    """Session-based transport allows GET /mcp; unauthenticated probes get a 401 challenge."""
    response = await public_mcp_client.get(
        "/mcp",
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert "WWW-Authenticate" in response.headers
    assert response.headers["WWW-Authenticate"].startswith("Bearer ")


async def test__public_mcp_oauth__resource_stays_mcp_when_ha_enabled(
    public_mcp_client_with_ha: AsyncClient,
) -> None:
    """HA upstream does not move the OAuth protected resource away from /mcp."""
    response = await public_mcp_client_with_ha.get(
        "/.well-known/oauth-protected-resource/mcp",
    )

    assert response.status_code == httpx.codes.OK
    assert response.json()["resource"] == f"{_PUBLIC_MCP_BASE_URL}/mcp"


async def test__public_mcp_oauth__unauthenticated_post_mcp_still_401_when_ha_enabled(
    public_mcp_client_with_ha: AsyncClient,
) -> None:
    """Unauthenticated POST /mcp still challenges when HA upstream is mounted."""
    response = await public_mcp_client_with_ha.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert "WWW-Authenticate" in response.headers
