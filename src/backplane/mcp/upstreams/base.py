"""Generic scoped upstream MCP provider support."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from fastmcp.prompts.base import Prompt
from fastmcp.server import create_proxy
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.providers.base import Provider
from fastmcp.server.providers.fastmcp_provider import FastMCPProvider
from fastmcp.tools.base import Tool
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from fastmcp import FastMCP
    from fastmcp.resources.base import Resource
    from fastmcp.resources.template import ResourceTemplate
    from fastmcp.utilities.components import FastMCPComponent
    from fastmcp.utilities.versions import VersionSpec


@dataclass(frozen=True)
class UpstreamMcpConfig:
    """Configuration for an MCP server proxied through Backplane."""

    name: str
    url: str
    namespace: str
    required_scope: str | None
    allowed_client_redirect_uri_patterns: tuple[str, ...] = ()


class _ScopeGatedProvider(Provider):
    """Expose an inner provider only when the request token has a required scope."""

    _inner: Provider
    _required_scope: str

    def __init__(self, inner: Provider, *, required_scope: str) -> None:
        super().__init__()
        self._inner = inner
        self._required_scope = required_scope

    def _is_authorized(self) -> bool:
        token = get_access_token()
        return token is not None and self._required_scope in token.scopes

    @override
    async def _list_tools(self) -> Sequence[Tool]:
        if not self._is_authorized():
            return []
        return await self._inner.list_tools()

    @override
    async def _get_tool(
        self,
        name: str,
        version: VersionSpec | None = None,
    ) -> Tool | None:
        if not self._is_authorized():
            return None
        return await self._inner.get_tool(name, version)

    @override
    async def _list_resources(self) -> Sequence[Resource]:
        if not self._is_authorized():
            return []
        return await self._inner.list_resources()

    @override
    async def _get_resource(
        self,
        uri: str,
        version: VersionSpec | None = None,
    ) -> Resource | None:
        if not self._is_authorized():
            return None
        return await self._inner.get_resource(uri, version)

    @override
    async def _list_resource_templates(self) -> Sequence[ResourceTemplate]:
        if not self._is_authorized():
            return []
        return await self._inner.list_resource_templates()

    @override
    async def _get_resource_template(
        self,
        uri: str,
        version: VersionSpec | None = None,
    ) -> ResourceTemplate | None:
        if not self._is_authorized():
            return None
        return await self._inner.get_resource_template(uri, version)

    @override
    async def _list_prompts(self) -> Sequence[Prompt]:
        if not self._is_authorized():
            return []
        return await self._inner.list_prompts()

    @override
    async def _get_prompt(
        self,
        name: str,
        version: VersionSpec | None = None,
    ) -> Prompt | None:
        if not self._is_authorized():
            return None
        return await self._inner.get_prompt(name, version)

    @override
    async def get_tasks(self) -> Sequence[FastMCPComponent]:
        if not self._is_authorized():
            return []
        return await self._inner.get_tasks()

    @override
    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None]:
        async with self._inner.lifespan():
            yield


def _assert_namespace_available(mcp: FastMCP[None], namespace: str) -> None:
    """Reject namespace prefixes that collide with local component names.

    Raises:
        ValueError: If a local tool or prompt already uses the namespace.
    """
    prefix = f"{namespace}_"
    components = (
        mcp.local_provider._components.values()  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    )
    collisions = sorted(
        component.name
        for component in components
        if isinstance(component, Tool | Prompt) and component.name.startswith(prefix)
    )
    if collisions:
        msg = (
            f"Upstream namespace {namespace!r} collides with local components: "
            f"{', '.join(collisions)}"
        )
        raise ValueError(msg)


def mount_upstream(
    mcp: FastMCP[None],
    config: UpstreamMcpConfig,
    *,
    gated: bool,
) -> None:
    """Mount a namespaced upstream, optionally gated by its OAuth scope.

    Raises:
        ValueError: If the namespace collides or a gated upstream has no scope.
    """
    _assert_namespace_available(mcp, config.namespace)
    logger.info(
        "Mounting {} MCP upstream with namespace {}",
        config.name,
        config.namespace,
    )
    proxy = create_proxy(config.url, name=f"{config.name} MCP")
    provider: Provider = FastMCPProvider(proxy)
    if gated:
        if config.required_scope is None:
            msg = f"Gated upstream {config.name!r} requires an OAuth scope"
            raise ValueError(msg)
        provider = _ScopeGatedProvider(
            provider,
            required_scope=config.required_scope,
        )
    mcp.add_provider(provider, namespace=config.namespace)
