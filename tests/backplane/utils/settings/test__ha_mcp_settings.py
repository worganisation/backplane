"""Tests for HA MCP settings."""

from __future__ import annotations

import pytest

from backplane.utils.async_path import AsyncPath
from backplane.utils.exceptions import UserError
from backplane.utils.settings import Settings


def test__settings__ha_mcp_defaults_are_disabled() -> None:
    """HA MCP upstream is disabled by default."""
    settings = Settings.model_validate({"obsidian_vault_path": AsyncPath("/tmp/vault")})

    assert settings.ha_mcp_enabled is False
    assert settings.ha_mcp_url is None
    assert settings.ha_mcp_namespace == "ha"


def test__require_ha_mcp_url__raises_when_enabled_without_url() -> None:
    """require_ha_mcp_url rejects enabled HA MCP without a URL."""
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": AsyncPath("/tmp/vault"),
            "ha_mcp_enabled": True,
        },
    )

    with pytest.raises(UserError, match="BACKPLANE_HA_MCP_URL"):
        settings.require_ha_mcp_url()


def test__require_ha_mcp_url__raises_when_disabled() -> None:
    """require_ha_mcp_url rejects calls when HA MCP upstream is disabled."""
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": AsyncPath("/tmp/vault"),
            "ha_mcp_enabled": False,
            "ha_mcp_url": "http://10.0.0.2:9583/secret-path",
        },
    )

    with pytest.raises(UserError, match="disabled"):
        settings.require_ha_mcp_url()
