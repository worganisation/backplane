"""General prompt reconciliation preserves model settings and rejects unsafe updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import JsonValue

from scripts.deploy.capture_assist import (
    GeneralConfig,
    HomeAssistant,
    configure_general,
    form_values,
    mapping,
    objects,
)

if TYPE_CHECKING:
    from unittest.mock import Mock

    from pytest_mock import MockerFixture


@pytest.fixture
def general_ha(mocker: MockerFixture) -> Mock:
    """Build the supported existing assistant and reload response.

    Returns:
        Mock Home Assistant client.
    """
    ha = mocker.Mock(spec=HomeAssistant)
    ha.entries.return_value = [{"entry_id": "openai", "domain": "openai_conversation"}]
    ha.command.return_value = [
        {"subentry_id": "general", "subentry_type": "conversation"},
    ]
    return ha


def initial_form(prompt: str = "old") -> dict[str, JsonValue]:
    """Return a configuration form retaining the existing device-control API.

    Returns:
        A simulated HA form.
    """
    return {
        "type": "form",
        "flow_id": "flow",
        "step_id": "init",
        "data_schema": [
            {"name": "prompt", "description": {"suggested_value": prompt}},
            {
                "name": "llm_hass_api",
                "description": {"suggested_value": ["assist", "mcp-tools"]},
            },
            {"name": "recommended", "default": False, "required": True},
        ],
    }


async def test_preserves_advanced_settings_and_verifies(
    general_ha: Mock,
    mocker: MockerFixture,
) -> None:
    """Updating the prompt keeps the chosen model and its nondefault controls."""
    mocker.patch("scripts.deploy.capture_assist.Path.read_text", return_value="owned")
    general_ha.request.side_effect = [
        {"require_restart": False},
        initial_form(),
        {
            "type": "form",
            "step_id": "additional",
            "data_schema": [
                {
                    "name": "chat_model",
                    "default": "default-model",
                    "description": {"suggested_value": "chosen-model"},
                },
                {
                    "name": "temperature",
                    "default": 1,
                    "description": {"suggested_value": 0},
                },
            ],
        },
        {
            "type": "form",
            "step_id": "model",
            "data_schema": [
                {
                    "name": "web_search",
                    "default": True,
                    "description": {"suggested_value": False},
                },
            ],
        },
        {"type": "abort", "reason": "reconfigure_successful"},
        initial_form("owned\n\nowned\n"),
        {},
    ]
    await configure_general(
        general_ha,
        GeneralConfig(entry_id="openai", subentry_id="general", mcp_entry_id="tools"),
    )
    calls = general_ha.request.await_args_list
    assert calls[3].args[2] == {"chat_model": "chosen-model", "temperature": 0}
    assert calls[4].args[2] == {"web_search": False}
    assert calls[2].args[2]["llm_hass_api"] == ["assist", "mcp-tools"]
    assert calls[-1].args == ("DELETE", "/api/config/config_entries/subentries/flow/flow")


async def test_missing_api_never_submits_prompt(general_ha: Mock) -> None:
    """A temporarily missing MCP registration cannot silently remove its API."""
    form = initial_form()
    fields = objects(form["data_schema"])
    mapping(fields[1]["description"])["suggested_value"] = ["assist"]
    general_ha.request.side_effect = [{"require_restart": False}, form, {}]
    with pytest.raises(RuntimeError, match="not selected or registered"):
        await configure_general(
            general_ha,
            GeneralConfig(entry_id="openai", subentry_id="general", mcp_entry_id="tools"),
        )
    assert general_ha.request.await_count == 3
    assert general_ha.request.await_args.args[0] == "DELETE"


async def test_unchanged_prompt_does_not_write(
    general_ha: Mock,
    mocker: MockerFixture,
) -> None:
    """Repeated deployment reloads tools but does not churn unchanged agent settings."""
    mocker.patch("scripts.deploy.capture_assist.Path.read_text", return_value="owned")
    general_ha.request.side_effect = [
        {"require_restart": False},
        initial_form("owned\n\nowned\n"),
        {},
    ]
    await configure_general(
        general_ha,
        GeneralConfig(entry_id="openai", subentry_id="general", mcp_entry_id="tools"),
    )
    assert general_ha.request.await_count == 3


def test_form_validation_rejects_missing_required_setting() -> None:
    """Unknown required inputs cannot be filled with guesses."""
    with pytest.raises(RuntimeError, match="Cannot preserve"):
        form_values({
            "type": "form",
            "data_schema": [{"name": "new_setting", "required": True}],
        })


@pytest.mark.parametrize("failure", ["validation", "unknown_step", "verification"])
async def test_rejected_or_unpersisted_update_is_not_success(
    general_ha: Mock,
    mocker: MockerFixture,
    failure: str,
) -> None:
    """API errors and failed readback stop deployment and clean up its flow."""
    mocker.patch("scripts.deploy.capture_assist.Path.read_text", return_value="owned")
    responses: list[dict[str, JsonValue]] = [
        {"require_restart": False},
        initial_form(),
    ]
    if failure == "validation":
        responses.extend([
            {"type": "form", "step_id": "additional", "errors": {"base": "invalid"}},
            {},
        ])
    elif failure == "unknown_step":
        responses.extend([
            {"type": "form", "step_id": "unexpected", "data_schema": []},
            {},
        ])
    else:
        responses.extend([
            {"type": "abort", "reason": "reconfigure_successful"},
            initial_form(),
            {},
        ])
    general_ha.request.side_effect = responses

    with pytest.raises(RuntimeError):
        await configure_general(
            general_ha,
            GeneralConfig(entry_id="openai", subentry_id="general", mcp_entry_id="tools"),
        )
    assert general_ha.request.await_args.args[0] == "DELETE"


@pytest.mark.parametrize("failure", ["missing_agent", "restart"])
async def test_unavailable_integration_stops_before_prompt_flow(
    general_ha: Mock,
    failure: str,
) -> None:
    """Deployment cannot create an accidental assistant or ignore a required restart."""
    if failure == "missing_agent":
        general_ha.command.return_value = []
    general_ha.request.return_value = {"require_restart": True}

    with pytest.raises(RuntimeError):
        await configure_general(
            general_ha,
            GeneralConfig(entry_id="openai", subentry_id="general", mcp_entry_id="tools"),
        )
    assert general_ha.request.await_count == (0 if failure == "missing_agent" else 1)
