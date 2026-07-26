"""Upstream MCP servers proxied through Backplane."""

from __future__ import annotations

from .base import UpstreamMcpConfig, mount_upstream
from .registry import HA_MCP_SCOPE, get_enabled_upstreams

__all__ = [
    "HA_MCP_SCOPE",
    "UpstreamMcpConfig",
    "get_enabled_upstreams",
    "mount_upstream",
]
