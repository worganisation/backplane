"""Capture deployment preserves unrelated assistants and handles failed configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts.deploy.capture_assist import (
    CaptureConfig,
    HomeAssistant,
    configure_agent,
    configure_mcp,
    configure_pipeline,
    unique,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def config() -> CaptureConfig:
    """Return isolated deployment inputs.

    Returns:
        Test capture configuration.
    """
    return CaptureConfig(
        ollama_entry_id="ollama",
        mcp_url="http://backplane.test/mcp-capture",
        agent_name="Capture agent",
        pipeline_name="Capture",
        model="qwen3:4b-instruct",
    )


async def test_existing_agent_reuses_subentry_and_only_capture_api(
    mocker: MockerFixture,
    config: CaptureConfig,
) -> None:
    """An update targets the existing capture subentry without adding device control."""
    ha = mocker.Mock(spec=HomeAssistant)
    entry = {
        "title": config.agent_name,
        "subentry_type": "conversation",
        "subentry_id": "capture",
    }
    ha.command.side_effect = [
        [entry],
        [entry],
        [
            {
                "entity_id": "conversation.capture",
                "config_entry_id": "ollama",
                "config_subentry_id": "capture",
            },
        ],
    ]

    assert await configure_agent(ha, config, "mcp") == "conversation.capture"
    args = ha.flow.await_args.args
    assert args[1]["subentry_id"] == "capture"
    assert args[2]["llm_hass_api"] == ["mcp-mcp"]
    assert "name" not in args[2]


async def test_pipeline_update_preserves_speech_settings_and_preferred(
    mocker: MockerFixture,
    config: CaptureConfig,
) -> None:
    """Existing capture speech settings survive while the general assistant stays preferred."""
    ha = mocker.Mock(spec=HomeAssistant)
    ha.command.side_effect = [
        {
            "preferred_pipeline": "general",
            "pipelines": [
                {"id": "general", "name": "General"},
                {
                    "id": "capture",
                    "name": "Capture",
                    "language": "en",
                    "conversation_language": "en",
                    "stt_engine": "stt.local",
                    "stt_language": "en",
                    "tts_engine": "tts.local",
                    "tts_language": "en",
                    "tts_voice": "voice",
                    "wake_word_entity": None,
                    "wake_word_id": None,
                },
            ],
        },
        {"id": "capture"},
    ]

    assert await configure_pipeline(ha, config, "conversation.capture") == "capture"
    assert ha.command.await_count == 2
    args = ha.command.await_args
    assert args.args == ("assist_pipeline/pipeline/update",)
    assert args.kwargs["pipeline_id"] == "capture"
    assert args.kwargs["stt_engine"] == "stt.local"
    assert args.kwargs["tts_voice"] == "voice"
    assert args.kwargs["prefer_local_intents"] is False


async def test_existing_mcp_is_reloaded_without_duplicate_creation(
    mocker: MockerFixture,
    config: CaptureConfig,
) -> None:
    """Deployment reuses the integration and refreshes its tool list."""
    ha = mocker.Mock(spec=HomeAssistant)
    ha.entries.return_value = [
        {
            "entry_id": "capture",
            "domain": "mcp",
            "title": "Backplane Capture",
            "state": "loaded",
        },
    ]
    ha.request.return_value = {"require_restart": False}
    assert await configure_mcp(ha, config) == "capture"
    ha.flow.assert_not_awaited()
    ha.request.assert_awaited_once_with(
        "POST",
        "/api/config/config_entries/entry/capture/reload",
    )


async def test_failed_flow_is_not_reported_as_success(mocker: MockerFixture) -> None:
    """HA validation errors stop deployment instead of claiming the agent is ready."""
    ha = HomeAssistant(mocker.Mock(), mocker.Mock())
    request = mocker.patch.object(ha, "request", new_callable=mocker.AsyncMock)
    request.side_effect = [
        {"type": "form", "flow_id": "flow"},
        {"type": "form", "errors": {"base": "cannot_connect"}},
    ]
    with pytest.raises(RuntimeError, match="cannot_connect"):
        await ha.flow("/flow", {}, {})


def test_duplicate_names_are_not_arbitrarily_overwritten() -> None:
    """An ambiguous object name stops reconciliation before mutation."""
    with pytest.raises(ValueError, match="Multiple"):
        unique([{"name": "Capture"}, {"name": "Capture"}], name="Capture")


async def test_mcp_retry_reloads_an_entry_in_setup_retry(
    mocker: MockerFixture,
    config: CaptureConfig,
) -> None:
    """A partially completed deployment can recover its existing integration."""
    ha = mocker.Mock(spec=HomeAssistant)
    entry = {"entry_id": "capture", "domain": "mcp", "title": "Backplane Capture"}
    ha.entries.side_effect = [
        [{**entry, "state": "setup_retry"}],
        [{**entry, "state": "loaded"}],
    ]
    ha.request.return_value = {"require_restart": False}

    assert await configure_mcp(ha, config) == "capture"
    ha.request.assert_awaited_once()
    ha.flow.assert_not_awaited()
