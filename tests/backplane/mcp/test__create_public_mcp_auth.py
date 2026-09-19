"""Tests for public MCP OAuth auth factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backplane.mcp.auth import (
    MCP_AUTHORIZE_SCOPES,
    MCP_BASELINE_SCOPE,
    create_public_mcp_auth,
    oauth_tool_meta,
    oauth_tool_registration_kwargs,
)
from backplane.utils.async_path import AsyncPath
from backplane.utils.exceptions import UserError
from backplane.utils.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_TEST_OAUTH_CREDENTIAL = "test-oauth-credential"


def test__create_public_mcp_auth__raises_when_oauth_is_not_configured(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """The public MCP auth factory refuses to start without OAuth env vars."""
    settings = Settings(obsidian_vault_path=AsyncPath(tmp_path))
    mocker.patch("backplane.mcp.auth.SETTINGS", settings)

    with pytest.raises(UserError, match="Public MCP requires OAuth"):
        create_public_mcp_auth()


def test__create_public_mcp_auth__builds_oidc_proxy_when_oauth_is_configured(
    mocker: MockerFixture,
) -> None:
    """The public MCP auth factory returns an OIDCProxy when OAuth env vars are complete."""
    mock_oidc_proxy = mocker.patch("backplane.mcp.auth.ScopedClientOIDCProxy")
    mock_introspection = mocker.patch("backplane.mcp.auth.IntrospectionTokenVerifier")
    mock_oidc_config = mocker.patch(
        "backplane.mcp.auth.OIDCConfiguration.get_oidc_configuration",
    )
    mock_oidc_config.return_value.introspection_endpoint = (
        "https://auth.example.com/application/o/introspect/"
    )
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": "/tmp/vault",
            "mcp_public_base_url": "https://backplane-mcp.example.com",
            "mcp_oidc_config_url": (
                "https://auth.example.com/application/o/backplane-mcp/"
                ".well-known/openid-configuration"
            ),
            "mcp_oidc_client_id": "client-id",
            "mcp_oidc_client_secret": _TEST_OAUTH_CREDENTIAL,
        },
    )
    mocker.patch("backplane.mcp.auth.SETTINGS", settings)

    mock_auth = mock_oidc_proxy.return_value
    auth = create_public_mcp_auth()

    assert auth is mock_auth
    mock_introspection.assert_called_once_with(
        introspection_url="https://auth.example.com/application/o/introspect/",
        client_id="client-id",
        client_secret=_TEST_OAUTH_CREDENTIAL,
        client_auth_method="client_secret_post",
        required_scopes=[MCP_BASELINE_SCOPE],
        cache_ttl_seconds=60,
    )
    mock_oidc_proxy.assert_called_once_with(
        config_url=settings.mcp_oidc_config_url,
        client_id="client-id",
        client_secret=_TEST_OAUTH_CREDENTIAL,
        base_url=settings.mcp_public_base_url,
        require_authorization_consent="external",
        allowed_client_redirect_uris=None,
        token_verifier=mock_introspection.return_value,
    )
    mock_auth.configure_client_scope_policy.assert_called_once_with(
        direct_client_id="client-id",
        scope_redirect_uri_patterns={},
    )
    assert mock_auth.required_scopes == [MCP_BASELINE_SCOPE]
    mock_auth.update_default_scopes.assert_called_once_with(
        list(MCP_AUTHORIZE_SCOPES),
    )


def test__create_public_mcp_auth__raises_when_introspection_endpoint_is_missing(
    mocker: MockerFixture,
) -> None:
    """The public MCP auth factory refuses to start without an introspection endpoint."""
    mocker.patch("backplane.mcp.auth.ScopedClientOIDCProxy")
    mock_oidc_config = mocker.patch(
        "backplane.mcp.auth.OIDCConfiguration.get_oidc_configuration",
    )
    mock_oidc_config.return_value.introspection_endpoint = None
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": "/tmp/vault",
            "mcp_public_base_url": "https://backplane-mcp.example.com",
            "mcp_oidc_config_url": (
                "https://auth.example.com/application/o/backplane-mcp/"
                ".well-known/openid-configuration"
            ),
            "mcp_oidc_client_id": "client-id",
            "mcp_oidc_client_secret": _TEST_OAUTH_CREDENTIAL,
        },
    )
    mocker.patch("backplane.mcp.auth.SETTINGS", settings)

    with pytest.raises(UserError, match="introspection endpoint"):
        create_public_mcp_auth()


def test__oauth_tool_meta__advertises_openid_oauth2_scheme() -> None:
    """OAuth tool metadata advertises the baseline openid scope to ChatGPT."""
    assert oauth_tool_meta() == {
        "securitySchemes": [{"type": "oauth2", "scopes": [MCP_BASELINE_SCOPE]}],
    }


def test__oauth_tool_registration_kwargs__defaults_to_baseline_scope() -> None:
    """OAuth registration kwargs advertise and require the baseline scope by default."""
    kwargs = oauth_tool_registration_kwargs()
    expected_meta = oauth_tool_meta()

    assert kwargs.get("meta") == {"securitySchemes": expected_meta["securitySchemes"]}
    assert kwargs.get("auth") is not None


def test__oauth_tool_registration_kwargs__forwards_explicit_scopes_to_meta() -> None:
    """Explicit scopes are advertised in tool metadata for future per-tool enforcement."""
    kwargs = oauth_tool_registration_kwargs("mcp.read")
    expected_meta = oauth_tool_meta("mcp.read")

    assert kwargs.get("meta") == {"securitySchemes": expected_meta["securitySchemes"]}
    assert kwargs.get("auth") is not None
