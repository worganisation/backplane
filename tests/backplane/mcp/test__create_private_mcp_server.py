"""Tests for the private MCP server entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backplane.mcp.__main__ import create_private_mcp_server, main

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test__create_private_mcp_server__notifies_home_assistant_on_startup(
    mocker: MockerFixture,
) -> None:
    """The private MCP entrypoint enables Home Assistant startup notifications."""
    mock_create = mocker.patch("backplane.mcp.__main__.create_mcp_server")
    mock_server = mocker.Mock()
    mock_create.return_value = mock_server

    server = create_private_mcp_server()

    mock_create.assert_called_once_with(notify_home_assistant=True)
    assert server is mock_server


def test__main__starts_private_mcp_server(mocker: MockerFixture) -> None:
    """The private entrypoint main function runs the SSE MCP server."""
    run_target = object()
    mock_server = mocker.Mock()
    mock_server.run_async.return_value = run_target
    mocker.patch(
        "backplane.mcp.__main__.create_private_mcp_server",
        return_value=mock_server,
    )
    mocker.patch("backplane.mcp.__main__.SETTINGS.ha_mcp_enabled", new=False)
    mock_uvloop = mocker.patch("backplane.mcp.__main__.uvloop.run")

    main()

    mock_server.run_async.assert_called_once_with(
        transport="sse",
        host="0.0.0.0",
        port=8000,
    )
    mock_uvloop.assert_called_once_with(run_target)


def test__main__starts_private_http_server_when_ha_upstream_enabled(
    mocker: MockerFixture,
) -> None:
    """The private entrypoint serves HTTP when HA upstream is enabled."""
    mock_app = mocker.Mock()
    mocker.patch("backplane.mcp.__main__.compose_private_mcp_app", return_value=mock_app)
    mocker.patch("backplane.mcp.__main__.SETTINGS.ha_mcp_enabled", new=True)
    mock_uvloop = mocker.patch("backplane.mcp.__main__.uvloop.run")
    mock_server = mocker.patch("backplane.mcp.__main__.uvicorn.Server")
    mock_config = mocker.patch("backplane.mcp.__main__.uvicorn.Config")

    main()

    mock_config.assert_called_once_with(
        mock_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    mock_server.assert_called_once_with(mock_config.return_value)
    mock_uvloop.assert_called_once_with(mock_server.return_value.serve.return_value)
