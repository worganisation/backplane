"""Tests for scoped upstream MCP mounting."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.server.providers.base import Provider
from starlette.routing import Route

from backplane.mcp.app_factory import build_backplane_mcp
from backplane.mcp.asgi import (
    _compose_mcp_apps,  # pyright: ignore[reportPrivateUsage]
    compose_private_mcp_app,
    compose_public_mcp_app,
)
from backplane.mcp.auth import MCP_BASELINE_SCOPE
from backplane.mcp.upstreams.base import (
    UpstreamMcpConfig,
    _ScopeGatedProvider,  # pyright: ignore[reportPrivateUsage]
    mount_upstream,
)
from backplane.mcp.upstreams.registry import HA_MCP_SCOPE, get_enabled_upstreams
from backplane.utils.async_path import AsyncPath
from backplane.utils.exceptions import UserError
from backplane.utils.settings import Settings

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def ha_upstream_settings() -> Settings:
    """Return settings with HA MCP upstream enabled against a fake URL."""
    return Settings.model_validate(
        {
            "obsidian_vault_path": AsyncPath("/tmp/vault"),
            "ha_mcp_enabled": True,
            "ha_mcp_url": "http://fake-ha-mcp.example.com/mcp",
            "ha_mcp_namespace": "ha",
        },
    )


@pytest.fixture
def sample_ha_upstream_config(
    ha_upstream_settings: Settings,
) -> UpstreamMcpConfig:
    """Return the enabled HA upstream configuration."""
    return get_enabled_upstreams(ha_upstream_settings)[0]


def test__get_enabled_upstreams__returns_none_when_ha_disabled() -> None:
    """Disabled HA proxying produces no upstream configurations."""
    settings = Settings.model_validate(
        {"obsidian_vault_path": AsyncPath("/tmp/vault")},
    )

    assert get_enabled_upstreams(settings) == ()


def test__get_enabled_upstreams__requires_url_when_ha_enabled(
    ha_upstream_settings: Settings,
) -> None:
    """Enabled HA proxying rejects a missing upstream URL."""
    settings = ha_upstream_settings.model_copy(update={"ha_mcp_url": None})

    with pytest.raises(UserError, match="HA_MCP_URL"):
        _ = get_enabled_upstreams(settings)


def test__compose_private_mcp_app__registers_upstream_route_when_enabled(
    mocker: MockerFixture,
    ha_upstream_settings: Settings,
    sample_fake_ha_mcp: FastMCP[None],
) -> None:
    """The private HTTP app exposes core /mcp and augmented /mcp-ha."""
    _ = mocker.patch("backplane.mcp.asgi.SETTINGS", ha_upstream_settings)
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.create_proxy",
        return_value=sample_fake_ha_mcp,
    )

    app = compose_private_mcp_app()
    route_paths = {route.path for route in app.routes if isinstance(route, Route)}

    assert {"/mcp", "/mcp-ha"} <= route_paths


def test__compose_mcp_apps__raises_when_upstream_route_missing() -> None:
    """Composition fails when an expected upstream route is absent."""
    core_app = build_backplane_mcp().http_app(transport="http")
    upstream_app = StarletteWithLifespan(routes=[])

    with pytest.raises(RuntimeError, match="/mcp-ha"):
        _ = _compose_mcp_apps(
            core_app=core_app,
            upstream_apps=(("/mcp-ha", upstream_app),),
        )


def test__compose_public_mcp_app__exposes_only_single_mcp_resource(
    mocker: MockerFixture,
    sample_oidc_configuration: OIDCConfiguration,
    sample_fake_ha_mcp: FastMCP[None],
) -> None:
    """The public app keeps every component on one OAuth-bound /mcp route."""
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
            "ha_mcp_enabled": True,
            "ha_mcp_url": "http://fake-ha-mcp.example.com/mcp",
            "ha_mcp_namespace": "ha",
        },
    )
    _ = mocker.patch("backplane.mcp.auth.SETTINGS", settings)
    _ = mocker.patch("backplane.mcp.asgi.SETTINGS", settings)
    _ = mocker.patch(
        "backplane.mcp.auth.OIDCConfiguration.get_oidc_configuration",
        return_value=sample_oidc_configuration,
    )
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.create_proxy",
        return_value=sample_fake_ha_mcp,
    )

    app = compose_public_mcp_app()
    route_paths = {route.path for route in app.routes if isinstance(route, Route)}

    assert "/mcp" in route_paths
    assert "/mcp-ha" not in route_paths


@pytest.mark.parametrize("token_scopes", [None, [MCP_BASELINE_SCOPE]])
async def test__mount_upstream__hides_every_component_without_required_scope(
    mocker: MockerFixture,
    sample_ha_upstream_config: UpstreamMcpConfig,
    sample_fake_ha_mcp: FastMCP[None],
    token_scopes: list[str] | None,
) -> None:
    """Missing HA scope hides tools, resources, templates, and prompts."""
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.create_proxy",
        return_value=sample_fake_ha_mcp,
    )
    mock_token = None if token_scopes is None else mocker.Mock(scopes=token_scopes)
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.get_access_token",
        return_value=mock_token,
    )
    mcp = build_backplane_mcp()
    mount_upstream(mcp, sample_ha_upstream_config, gated=True)

    assert not any(tool.name.startswith("ha_") for tool in await mcp.list_tools())
    assert not any(
        str(resource.uri).startswith("ha://ha/")
        for resource in await mcp.list_resources()
    )
    assert not any(
        template.uri_template.startswith("ha://ha/")
        for template in await mcp.list_resource_templates()
    )
    assert not any(prompt.name.startswith("ha_") for prompt in await mcp.list_prompts())

    with pytest.raises(NotFoundError):
        _ = await mcp.call_tool(
            "ha_ha_get_state",
            {"entity_id": "light.kitchen"},
        )
    with pytest.raises(NotFoundError):
        _ = await mcp.read_resource("ha://ha/config")
    with pytest.raises(NotFoundError):
        _ = await mcp.read_resource("ha://ha/state/light.kitchen")
    with pytest.raises(NotFoundError):
        _ = await mcp.render_prompt(
            "ha_ha_control_prompt",
            {"area": "kitchen"},
        )


async def test__mount_upstream__exposes_every_component_with_required_scope(
    mocker: MockerFixture,
    sample_ha_upstream_config: UpstreamMcpConfig,
    sample_fake_ha_mcp: FastMCP[None],
) -> None:
    """HA scope reveals and permits every upstream component type."""
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.create_proxy",
        return_value=sample_fake_ha_mcp,
    )
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.get_access_token",
        return_value=mocker.Mock(scopes=[MCP_BASELINE_SCOPE, HA_MCP_SCOPE]),
    )
    mcp = build_backplane_mcp()
    mount_upstream(mcp, sample_ha_upstream_config, gated=True)

    assert "ha_ha_get_state" in {tool.name for tool in await mcp.list_tools()}
    assert "ha://ha/config" in {
        str(resource.uri) for resource in await mcp.list_resources()
    }
    assert "ha://ha/state/{entity_id}" in {
        template.uri_template for template in await mcp.list_resource_templates()
    }
    assert "ha_ha_control_prompt" in {prompt.name for prompt in await mcp.list_prompts()}
    assert await mcp.call_tool(
        "ha_ha_get_state",
        {"entity_id": "light.kitchen"},
    )
    assert await mcp.read_resource("ha://ha/config")
    assert await mcp.read_resource("ha://ha/state/light.kitchen")
    assert await mcp.render_prompt(
        "ha_ha_control_prompt",
        {"area": "kitchen"},
    )


async def test__scope_gated_provider__does_not_call_inner_when_unauthorized(
    mocker: MockerFixture,
) -> None:
    """An unauthorized request short-circuits before every upstream operation."""
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.get_access_token",
        return_value=mocker.Mock(scopes=[MCP_BASELINE_SCOPE]),
    )
    mock_inner = mocker.MagicMock(spec=Provider)
    mock_methods: dict[str, AsyncMock] = {}
    for method_name in (
        "list_tools",
        "list_resources",
        "list_resource_templates",
        "list_prompts",
        "get_tool",
        "get_resource",
        "get_resource_template",
        "get_prompt",
        "get_tasks",
    ):
        mock_method = AsyncMock()
        mock_methods[method_name] = mock_method
        setattr(mock_inner, method_name, mock_method)
    provider = _ScopeGatedProvider(mock_inner, required_scope=HA_MCP_SCOPE)

    assert await provider.list_tools() == []
    assert await provider.list_resources() == []
    assert await provider.list_resource_templates() == []
    assert await provider.list_prompts() == []
    assert await provider.get_tool("tool") is None
    assert await provider.get_resource("ha://config") is None
    assert await provider.get_resource_template("ha://state/{id}") is None
    assert await provider.get_prompt("prompt") is None
    assert await provider.get_tasks() == []

    assert all(mock_method.await_count == 0 for mock_method in mock_methods.values())


async def test__mount_upstream__does_not_leak_components_between_requests(
    mocker: MockerFixture,
    sample_ha_upstream_config: UpstreamMcpConfig,
    sample_fake_ha_mcp: FastMCP[None],
) -> None:
    """A scoped request cannot populate results for a later unscoped request."""
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.create_proxy",
        return_value=sample_fake_ha_mcp,
    )
    mock_get_token = mocker.patch(
        "backplane.mcp.upstreams.base.get_access_token",
        return_value=mocker.Mock(scopes=[MCP_BASELINE_SCOPE, HA_MCP_SCOPE]),
    )
    mcp = build_backplane_mcp()
    mount_upstream(mcp, sample_ha_upstream_config, gated=True)

    assert "ha_ha_get_state" in {tool.name for tool in await mcp.list_tools()}
    mock_get_token.return_value = mocker.Mock(scopes=[MCP_BASELINE_SCOPE])

    assert "ha_ha_get_state" not in {tool.name for tool in await mcp.list_tools()}


def test__mount_upstream__rejects_local_namespace_collision(
    mocker: MockerFixture,
    mcp_with_ha_namespace_collision: FastMCP[None],
    sample_ha_upstream_config: UpstreamMcpConfig,
) -> None:
    """An upstream namespace cannot overlap a local component name."""
    _ = mocker.patch("backplane.mcp.upstreams.base.create_proxy")

    with pytest.raises(ValueError, match="ha_local_tool"):
        mount_upstream(
            mcp_with_ha_namespace_collision,
            sample_ha_upstream_config,
            gated=True,
        )


async def test__scope_gated_upstream__failure_leaves_core_tools_available(
    mocker: MockerFixture,
) -> None:
    """A failing authorized upstream does not prevent listing core tools."""
    _ = mocker.patch(
        "backplane.mcp.upstreams.base.get_access_token",
        return_value=mocker.Mock(scopes=[MCP_BASELINE_SCOPE, HA_MCP_SCOPE]),
    )
    mock_inner = mocker.MagicMock(spec=Provider)
    mock_inner.list_tools = mocker.AsyncMock(side_effect=TimeoutError)
    provider = _ScopeGatedProvider(mock_inner, required_scope=HA_MCP_SCOPE)
    mcp = build_backplane_mcp()
    mcp.add_provider(provider, namespace="ha")

    tools = await mcp.list_tools()

    assert tools
    assert all(not tool.name.startswith("ha_") for tool in tools)
