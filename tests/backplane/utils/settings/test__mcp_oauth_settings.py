"""Tests for public MCP OAuth settings."""

from __future__ import annotations

import pytest

from backplane.utils.async_path import AsyncPath
from backplane.utils.settings import Settings

_TEST_OAUTH_CREDENTIAL = "test-oauth-credential"


def test__mcp_oauth_configured__returns_false_when_oauth_env_vars_are_missing() -> None:
    """OAuth is considered unconfigured when any required MCP OAuth env var is absent."""
    settings = Settings(
        obsidian_vault_path=AsyncPath("/tmp/vault"),
    )

    assert settings.mcp_oauth_configured is False


def test__mcp_oauth_configured__returns_true_when_all_oauth_env_vars_are_present() -> (
    None
):
    """OAuth is configured only when every required MCP OAuth env var is set."""
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

    assert settings.mcp_oauth_configured is True


@pytest.mark.parametrize(
    ("field_name", "value", "expected"),
    [
        (
            "mcp_public_base_url",
            "https://backplane-mcp.example.com",
            "https://backplane-mcp.example.com/",
        ),
        (
            "mcp_oidc_config_url",
            "https://auth.example.com/application/o/x/.well-known/openid-configuration",
            "https://auth.example.com/application/o/x/.well-known/openid-configuration",
        ),
    ],
)
def test__settings__parse_mcp_url_fields(
    field_name: str,
    value: str,
    expected: str,
) -> None:
    """MCP OAuth URL settings accept string env values."""
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": "/tmp/vault",
            field_name: value,
        },
    )

    parsed = getattr(settings, field_name)
    assert parsed is not None
    assert str(parsed) == expected


def test__settings__allowed_client_redirect_uri_patterns__defaults_to_empty() -> None:
    """Allowed redirect patterns are empty unless configured via env."""
    settings = Settings.model_validate({"obsidian_vault_path": "/tmp/vault"})

    assert settings.allowed_client_redirect_uri_patterns == []
    assert settings.ha_mcp_client_redirect_uri_patterns == ()


def test__settings__allowed_client_redirect_uri_patterns__is_configurable() -> None:
    """A deployment may allow the redirect URIs of any downstream MCP client."""
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": "/tmp/vault",
            "allowed_client_redirect_uri_patterns": [
                "https://claude.ai/api/mcp/auth_callback",
                "https://mcp-client.example/callback",
            ],
        },
    )

    assert settings.allowed_client_redirect_uri_patterns == [
        "https://claude.ai/api/mcp/auth_callback",
        "https://mcp-client.example/callback",
    ]
    assert settings.ha_mcp_client_redirect_uri_patterns == (
        "https://claude.ai/api/mcp/auth_callback",
        "https://mcp-client.example/callback",
    )


def test__settings__allowed_client_redirect_uri_patterns__reads_json_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ALLOWED_CLIENT_REDIRECT_URI_PATTERNS configures both redirect allowlists."""
    monkeypatch.setenv(
        "ALLOWED_CLIENT_REDIRECT_URI_PATTERNS",
        '["https://claude.ai/api/mcp/auth_callback"]',
    )

    settings = Settings(obsidian_vault_path=AsyncPath("/tmp/vault"))

    assert settings.allowed_client_redirect_uri_patterns == [
        "https://claude.ai/api/mcp/auth_callback",
    ]
    assert settings.ha_mcp_client_redirect_uri_patterns == (
        "https://claude.ai/api/mcp/auth_callback",
    )


def test__settings__ha_mcp_client_redirect_uri_patterns__can_override_shared_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HA_MCP_CLIENT_REDIRECT_URI_PATTERNS can set the HA allowlist independently."""
    monkeypatch.setenv(
        "HA_MCP_CLIENT_REDIRECT_URI_PATTERNS",
        '["https://chatgpt.com/connector/oauth/*"]',
    )

    settings = Settings(obsidian_vault_path=AsyncPath("/tmp/vault"))

    assert settings.ha_mcp_client_redirect_uri_patterns == (
        "https://chatgpt.com/connector/oauth/*",
    )
    assert settings.allowed_client_redirect_uri_patterns == []
