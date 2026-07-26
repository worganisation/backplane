"""Home Assistant service integration for Backplane."""

from __future__ import annotations

import asyncio

import aiohttp
from loguru import logger

from backplane import __version__
from backplane.utils.settings import SETTINGS

_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _log_ha_response(
    response: aiohttp.ClientResponse,
    domain: str,
    service: str,
) -> None:
    """Log success or error details for a Home Assistant service response."""
    if response.ok:
        logger.info("{}/{} → {}", domain, service, response.status)
        return

    body = await response.text()
    logger.error(
        "{}/{} returned {} — {}",
        domain,
        service,
        response.status,
        body,
    )


async def _call_ha_service(
    domain: str,
    service: str,
    data: dict[str, str],
) -> None:
    """POST to a Home Assistant service endpoint.

    Never raises — logs a warning on non-2xx or network error.
    """
    if not (SETTINGS.home_assistant_url and SETTINGS.home_assistant_token):
        logger.warning(
            "Skipping {domain}/{service} — HA settings not fully configured",
            domain=domain,
            service=service,
        )
        return

    url = SETTINGS.home_assistant_url / f"api/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {SETTINGS.home_assistant_token}"}

    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT) as session,
            session.post(url, json=data, headers=headers) as response,
        ):
            await _log_ha_response(response, domain, service)
    except Exception as exc:  # ruff:ignore[blind-except]
        logger.exception("{}/{} failed (url={}) — {}", domain, service, url, exc)


async def reload_mcp_integration() -> None:
    """Trigger a reload of the Backplane MCP config entry in Home Assistant.

    No-ops silently if Home Assistant settings are not fully configured.
    """
    if not SETTINGS.home_assistant_mcp_entry_id:
        logger.debug("Skipping MCP integration reload — HA MCP entry ID not configured")
        return

    await _call_ha_service(
        "homeassistant",
        "reload_config_entry",
        {"entry_id": SETTINGS.home_assistant_mcp_entry_id},
    )


async def _startup_title() -> str:
    """Return a notification title reflecting whether HEAD is a tagged release or a branch."""
    tag_proc = await asyncio.create_subprocess_exec(
        "git",
        "describe",
        "--exact-match",
        "HEAD",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _ = await tag_proc.wait()

    if tag_proc.returncode == 0:
        return f"Backplane v{__version__} started"

    branch_proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "--abbrev-ref",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await branch_proc.communicate()
    branch = stdout.decode().strip() or "unknown"

    return f"Backplane started on branch `{branch}`"


async def notify_startup(tools: list[str], resources: list[str]) -> None:
    """Create a persistent notification in Home Assistant with the running version.

    No-ops silently if Home Assistant URL or token are not configured.

    Args:
        tools: Names of registered MCP tools.
        resources: Display names of registered MCP resources and resource templates.
    """
    tool_lines = "\n".join(f"- `{t}`" for t in sorted(tools))
    resource_lines = "\n".join(f"- {r}" for r in sorted(resources))

    message = f"**Tools**\n{tool_lines}\n\n**Resources**\n{resource_lines}"

    await _call_ha_service(
        "persistent_notification",
        "create",
        {
            "title": await _startup_title(),
            "message": message,
            "notification_id": "backplane_startup",
        },
    )
