"""Reconcile the dedicated capture agent through Home Assistant's supported APIs."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from pathlib import Path

import aiohttp
from loguru import logger
from pydantic import BaseModel, JsonValue, TypeAdapter

from backplane.utils.settings import SETTINGS

_JSON = TypeAdapter(JsonValue)
_ROOT = Path(__file__).resolve().parents[2]


class CaptureConfig(BaseModel):
    """Public deployment inputs for this homelab's capture assistant."""

    ollama_entry_id: str
    mcp_url: str
    agent_name: str
    pipeline_name: str
    model: str


def mapping(value: JsonValue) -> dict[str, JsonValue]:
    """Require an object response.

    Returns:
        The validated object.

    Raises:
        TypeError: If the response is not an object.
    """
    if not isinstance(value, dict):
        msg = "Home Assistant returned an unexpected response shape"
        raise TypeError(msg)
    return value


def objects(value: JsonValue) -> list[dict[str, JsonValue]]:
    """Require a list of object responses.

    Returns:
        The validated object list.

    Raises:
        TypeError: If the response is not a list.
    """
    if not isinstance(value, list):
        msg = "Home Assistant returned an unexpected list shape"
        raise TypeError(msg)
    return [mapping(item) for item in value]


def unique(
    items: list[dict[str, JsonValue]],
    **fields: JsonValue,
) -> dict[str, JsonValue] | None:
    """Find one managed object, refusing ambiguous names.

    Returns:
        The matching object, or None.

    Raises:
        ValueError: If multiple objects match.
    """
    matches = [item for item in items if all(item.get(k) == v for k, v in fields.items())]
    if len(matches) > 1:
        msg = "Multiple Home Assistant objects match the capture configuration"
        raise ValueError(msg)
    return matches[0] if matches else None


def identifier(item: dict[str, JsonValue], key: str) -> str:
    """Require a nonempty identifier.

    Returns:
        The identifier.

    Raises:
        ValueError: If the identifier is missing.
    """
    if not isinstance(value := item.get(key), str) or not value:
        msg = f"Home Assistant response is missing {key}"
        raise ValueError(msg)
    return value


class HomeAssistant:
    """Authenticated HTTP and WebSocket calls without logging credentials or payloads."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        socket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        """Bind the authenticated session and socket."""
        self.session = session
        self.socket = socket
        self.sequence = 0

    async def request(
        self,
        method: str,
        path: str,
        data: dict[str, JsonValue] | None = None,
    ) -> JsonValue:
        """Call a configuration REST endpoint.

        Returns:
            The decoded response.
        """
        async with self.session.request(method, path, json=data) as response:
            response.raise_for_status()
            return _JSON.validate_json(await response.text())

    async def command(self, command: str, **data: JsonValue) -> JsonValue:
        """Run one WebSocket command and validate its result.

        Returns:
            The command result.

        Raises:
            RuntimeError: If the command fails.
        """
        self.sequence += 1
        await self.socket.send_json({"id": self.sequence, "type": command, **data})
        result = mapping(_JSON.validate_json(await self.socket.receive_str(timeout=30)))
        if result.get("id") != self.sequence or result.get("success") is not True:
            msg = f"Home Assistant command failed: {command}"
            raise RuntimeError(msg)
        return result.get("result")

    async def flow(
        self,
        path: str,
        initial: dict[str, JsonValue],
        values: dict[str, JsonValue],
    ) -> None:
        """Complete a single-form configuration flow and reject errors or extra steps.

        Raises:
            RuntimeError: If the flow does not complete successfully.
        """
        flow = mapping(await self.request("POST", path, initial))
        flow_id = identifier(flow, "flow_id")
        if flow.get("type") != "form":
            msg = "Unexpected Home Assistant configuration flow"
            raise RuntimeError(msg)

        result = mapping(await self.request("POST", f"{path}/{flow_id}", values))
        if result.get("type") == "create_entry":
            return
        if (
            result.get("type") == "abort"
            and result.get("reason") == "reconfigure_successful"
        ):
            return
        reason = result.get("errors") or result.get("reason") or result.get("type")
        msg = f"Home Assistant configuration failed: {reason}"
        raise RuntimeError(msg)

    async def entries(self) -> list[dict[str, JsonValue]]:
        """List config entries without reading their private data.

        Returns:
            Public config entry metadata.
        """
        return objects(await self.command("config_entries/get"))


async def configure_mcp(ha: HomeAssistant, config: CaptureConfig) -> str:
    """Create or reload the capture-only integration and wait for its API registration.

    Returns:
        The capture MCP entry ID.

    Raises:
        RuntimeError: If the integration does not become ready.
    """
    existing = unique(await ha.entries(), domain="mcp", title="Backplane Capture")
    if existing:
        entry_id = identifier(existing, "entry_id")
        result = mapping(
            await ha.request(
                "POST",
                f"/api/config/config_entries/entry/{entry_id}/reload",
            ),
        )
        if result.get("require_restart") is not False:
            msg = "Capture MCP integration requires a Home Assistant restart"
            raise RuntimeError(msg)
    else:
        await ha.flow(
            "/api/config/config_entries/flow",
            {"handler": "mcp", "show_advanced_options": False},
            {"url": config.mcp_url},
        )

    for _ in range(30):
        entry = unique(await ha.entries(), domain="mcp", title="Backplane Capture")
        if entry and entry.get("state") == "loaded":
            return identifier(entry, "entry_id")
        await asyncio.sleep(1)
    msg = "Capture MCP integration did not become ready"
    raise RuntimeError(msg)


async def configure_agent(ha: HomeAssistant, config: CaptureConfig, mcp_id: str) -> str:
    """Reconcile only the dedicated Ollama conversation subentry.

    Returns:
        The capture conversation entity ID.

    Raises:
        RuntimeError: If the subentry or entity is unavailable.
    """
    subentries = objects(
        await ha.command(
            "config_entries/subentries/list",
            entry_id=config.ollama_entry_id,
        ),
    )
    existing = unique(subentries, title=config.agent_name, subentry_type="conversation")
    initial: dict[str, JsonValue] = {"handler": [config.ollama_entry_id, "conversation"]}
    values: dict[str, JsonValue] = {
        "model": config.model,
        "prompt": (_ROOT / "deploy/capture-prompt.jinja").read_text(),
        "llm_hass_api": [f"mcp-{mcp_id}"],
        "num_ctx": 4096,
        "max_history": 4,
        "keep_alive": 600,
        "think": False,
    }
    if existing:
        initial["subentry_id"] = identifier(existing, "subentry_id")
    else:
        values["name"] = config.agent_name

    await ha.flow("/api/config/config_entries/subentries/flow", initial, values)
    subentries = objects(
        await ha.command(
            "config_entries/subentries/list",
            entry_id=config.ollama_entry_id,
        ),
    )
    subentry = unique(subentries, title=config.agent_name, subentry_type="conversation")
    if not subentry:
        msg = "Capture conversation subentry was not created"
        raise RuntimeError(msg)
    subentry_id = identifier(subentry, "subentry_id")

    for _ in range(30):
        entities = objects(await ha.command("config/entity_registry/list"))
        matches = [
            entry
            for entry in entities
            if str(entry.get("entity_id", "")).startswith("conversation.")
        ]
        if entity := unique(
            matches,
            config_entry_id=config.ollama_entry_id,
            config_subentry_id=subentry_id,
        ):
            return identifier(entity, "entity_id")
        await asyncio.sleep(1)
    msg = "Capture conversation entity did not become ready"
    raise RuntimeError(msg)


async def configure_pipeline(
    ha: HomeAssistant,
    config: CaptureConfig,
    agent_id: str,
) -> str:
    """Create a capture pipeline with the preferred speech engines, preserving the default.

    Returns:
        The capture pipeline ID.

    Raises:
        RuntimeError: If no preferred pipeline exists.
    """
    inventory = mapping(await ha.command("assist_pipeline/pipeline/list"))
    pipelines = objects(inventory["pipelines"])
    existing = unique(pipelines, name=config.pipeline_name)
    base = existing or unique(pipelines, id=inventory["preferred_pipeline"])
    if not base:
        msg = "No preferred Assist pipeline to supply speech settings"
        raise RuntimeError(msg)

    fields = (
        "language",
        "conversation_language",
        "stt_engine",
        "stt_language",
        "tts_engine",
        "tts_language",
        "tts_voice",
        "wake_word_entity",
        "wake_word_id",
    )
    values = {key: base.get(key) for key in fields}
    values.update(
        name=config.pipeline_name,
        conversation_engine=agent_id,
        prefer_local_intents=False,
    )
    if existing:
        values["pipeline_id"] = identifier(existing, "id")
        result = await ha.command("assist_pipeline/pipeline/update", **values)
    else:
        result = await ha.command("assist_pipeline/pipeline/create", **values)
    return identifier(mapping(result), "id")


async def wait_for_backplane() -> None:
    """Wait for the private service to finish its startup lifecycle.

    Raises:
        RuntimeError: If Backplane does not become healthy within 60 seconds.
    """
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
        for _ in range(20):
            try:
                async with session.get(
                    "http://127.0.0.1:8000/api/health/check",
                ) as response:
                    if response.status == HTTPStatus.OK:
                        return
            except aiohttp.ClientError, TimeoutError:
                pass
            await asyncio.sleep(1)

    msg = "Backplane did not become healthy for capture configuration"
    raise RuntimeError(msg)


async def main() -> None:
    """Apply the repository-owned capture configuration after a release deployment.

    Raises:
        ValueError: If required HA settings are absent.
        RuntimeError: If HA authentication fails.
    """
    await wait_for_backplane()
    config = CaptureConfig.model_validate_json(
        (_ROOT / "deploy/capture-assist.json").read_text(),
    )
    if not SETTINGS.home_assistant_url or not SETTINGS.home_assistant_token:
        msg = "Home Assistant URL and token are required for capture deployment"
        raise ValueError(msg)

    async with (
        aiohttp.ClientSession(
            base_url=str(SETTINGS.home_assistant_url),
            headers={"Authorization": f"Bearer {SETTINGS.home_assistant_token}"},
            timeout=aiohttp.ClientTimeout(total=45),
        ) as session,
        session.ws_connect("/api/websocket") as socket,
    ):
        _ = await socket.receive_str(timeout=10)
        await socket.send_json({
            "type": "auth",
            "access_token": SETTINGS.home_assistant_token,
        })
        auth = mapping(_JSON.validate_json(await socket.receive_str(timeout=10)))
        if auth.get("type") != "auth_ok":
            msg = "Home Assistant authentication failed"
            raise RuntimeError(msg)

        ha = HomeAssistant(session, socket)
        mcp_id = await configure_mcp(ha, config)
        agent_id = await configure_agent(ha, config, mcp_id)
        pipeline_id = await configure_pipeline(ha, config, agent_id)
        logger.info("Capture Assist ready: agent={}, pipeline={}", agent_id, pipeline_id)


if __name__ == "__main__":
    asyncio.run(main())
