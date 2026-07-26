"""Configured upstream MCP server registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from backplane.mcp.upstreams.base import UpstreamMcpConfig

if TYPE_CHECKING:
    from backplane.utils.settings import Settings

HA_MCP_SCOPE: Final = "backplane.home-assistant"


def get_enabled_upstreams(settings: Settings) -> tuple[UpstreamMcpConfig, ...]:
    """Return all upstream MCP servers enabled by the supplied settings."""
    if not settings.ha_mcp_enabled:
        return ()

    return (
        UpstreamMcpConfig(
            name="Home Assistant",
            url=settings.require_ha_mcp_url(),
            namespace=settings.ha_mcp_namespace,
            required_scope=HA_MCP_SCOPE,
            allowed_client_redirect_uri_patterns=(
                settings.ha_mcp_client_redirect_uri_patterns
            ),
        ),
    )
