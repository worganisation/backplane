"""Manually score local capture-model proposals without executing any tools."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Annotated, Literal

import aiohttp
from jinja2 import Environment, StrictUndefined
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from backplane.mcp.capture import build_capture_mcp
from backplane.utils.settings import SETTINGS
from scripts.deploy.capture_assist import CaptureConfig

ROOT = Path(__file__).resolve().parents[2]
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
CAPTURE_TEXT = {
    "record_diary": "content",
    "record_idea": "idea",
    "capture_task": "description",
}


class Scenario(BaseModel, frozen=True):
    """One grounded request with deterministic routing and argument expectations."""

    name: str
    text: str
    tool: Literal["record_diary", "record_idea", "capture_task"] | None
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    contains: list[str] = Field(default_factory=list)
    clarification: bool = False


class ProposedFunction(BaseModel, frozen=True):
    """An OpenAI-compatible function proposal; it is never dispatched."""

    name: str
    arguments: str


class ProposedCall(BaseModel, frozen=True):
    """One function call returned by the local model."""

    type: Literal["function"]
    function: ProposedFunction


class Message(BaseModel, frozen=True):
    """Assistant speech and proposed calls from one isolated scenario."""

    content: str | None = None
    tool_calls: list[ProposedCall] = Field(default_factory=list)


class Choice(BaseModel, frozen=True):
    """One completion choice from Ollama's compatible endpoint."""

    message: Message


class Completion(BaseModel, frozen=True):
    """Require exactly one model choice so malformed replies cannot silently pass."""

    choices: Annotated[list[Choice], Field(min_length=1, max_length=1)]


def score(
    scenario: Scenario,
    message: Message,
    schemas: dict[str, dict[str, JsonValue]],
    key_prefix: str,
) -> list[str]:
    """Validate actual schemas and grounded expectations without executing a proposal.

    Returns:
        All detected violations; an empty list means this bounded check passed.
    """
    issues: list[str] = []
    calls = message.tool_calls
    expected = [] if scenario.tool is None else [scenario.tool]
    if [call.function.name for call in calls] != expected:
        issues.append(
            f"Expected tools {expected!r}, got {[c.function.name for c in calls]!r}",
        )

    if scenario.tool is None and not (message.content or "").strip():
        issues.append("Expected a spoken response without capturing anything")
    if scenario.clarification and "?" not in (message.content or ""):
        issues.append("Expected a clarification question")

    for call in calls:
        function = call.function
        if function.name not in schemas:
            issues.append(f"Unknown tool: {function.name}")
            continue

        issues.extend(score_call(scenario, function, schemas[function.name], key_prefix))

    return issues


def score_call(
    scenario: Scenario,
    function: ProposedFunction,
    schema: dict[str, JsonValue],
    key_prefix: str,
) -> list[str]:
    """Check one proposed call against its schema and explicit user fields.

    Returns:
        Schema, operation-key and factual preservation violations.
    """
    try:
        arguments = JSON_OBJECT.validate_json(function.arguments)
    except ValidationError:
        return [f"{function.name}: arguments must be a JSON object"]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    issues = [
        f"{function.name}: {error.json_path}: {error.message}"
        for error in validator.iter_errors(arguments)
    ]
    key = arguments.get("idempotency_key")
    if not isinstance(key, str) or not key.startswith(key_prefix) or key == key_prefix:
        issues.append("Capture key must use this request's prefix plus a suffix")

    if function.name != scenario.tool:
        return issues

    issues.extend(
        f"{field}: expected {value!r}, got {arguments.get(field)!r}"
        for field, value in scenario.arguments.items()
        if arguments.get(field) != value
    )
    captured = arguments.get(CAPTURE_TEXT[function.name])
    issues.extend(
        f"Original wording missing: {fragment!r}"
        for fragment in scenario.contains
        if not isinstance(captured, str) or fragment.casefold() not in captured.casefold()
    )
    return issues


def render_prompt(source: str, clock: dt.datetime) -> str:
    """Render the deployment prompt with a fixed request-local clock.

    Returns:
        The exact text supplied as the system message.
    """
    template = Environment(undefined=StrictUndefined, autoescape=False).from_string(  # ruff:ignore[jinja2-autoescape-false] -- Plain-text model instructions, never HTML.
        source,
    )
    return template.render(now=lambda: clock, timedelta=dt.timedelta)


async def evaluate(*, model: str | None = None, dry_run: bool = False) -> int:
    """Print a JSON report for the fixed corpus, sending only text/schema data to Ollama.

    Returns:
        Zero for a passing run or dry run, one for any failed scenario.
    """
    model = (
        model
        or CaptureConfig.model_validate_json(
            (ROOT / "deploy/capture-assist.json").read_text(encoding="utf-8"),
        ).model
    )
    scenarios = TypeAdapter(list[Scenario]).validate_json(
        (ROOT / "scripts/fixtures/capture-evaluation.json").read_text(encoding="utf-8"),
    )
    prompt_source = (ROOT / "deploy/capture-prompt.jinja").read_text(encoding="utf-8")
    schemas: dict[str, dict[str, JsonValue]] = {}
    tools: list[dict[str, JsonValue]] = []
    for tool in await build_capture_mcp().list_tools():
        schemas[tool.name] = JSON_OBJECT.validate_python(tool.parameters)
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schemas[tool.name],
            },
        })

    anchor = dt.datetime(2026, 10, 18, 21, 15, tzinfo=SETTINGS.local_timezone)
    report: dict[str, JsonValue] = {
        "model": model,
        "dry_run": dry_run,
        "clock": anchor.isoformat(),
        "prompt_sha256": hashlib.sha256(prompt_source.encode()).hexdigest(),
        "tools_sha256": hashlib.sha256(
            json.dumps(tools, sort_keys=True).encode(),
        ).hexdigest(),
        "cases": [],
    }
    results: list[JsonValue] = []
    failed = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        for index, scenario in enumerate(scenarios):
            clock = anchor + dt.timedelta(seconds=index)
            prompt = render_prompt(prompt_source, clock)
            if dry_run:
                results.append({
                    "scenario": scenario.model_dump(mode="json"),
                    "prompt": prompt,
                })
                continue

            began = time.monotonic()
            message: Message | None = None
            try:
                async with session.post(
                    str(SETTINGS.ollama_base_url).rstrip("/") + "/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": scenario.text},
                        ],
                        "tools": tools,
                        "tool_choice": "auto",
                        "temperature": 0,
                        "max_tokens": 1024,
                        "stream": False,
                    },
                ) as response:
                    response.raise_for_status()
                    message = (
                        Completion
                        .model_validate_json(
                            await response.text(),
                        )
                        .choices[0]
                        .message
                    )

                issues = score(scenario, message, schemas, clock.isoformat())
            except (aiohttp.ClientError, TimeoutError, ValidationError) as error:
                issues = [f"Request or response failed: {type(error).__name__}"]
                if isinstance(error, aiohttp.ClientResponseError):
                    issues.append(f"HTTP status: {error.status}")

            failed += bool(issues)
            results.append({
                "name": scenario.name,
                "passed": not issues,
                "issues": issues,
                "seconds": round(time.monotonic() - began, 3),
                "response": message.model_dump(mode="json") if message else None,
            })
            _ = sys.stderr.write(f"{scenario.name}: {'FAIL' if issues else 'PASS'}\n")

    report["cases"] = results
    report["failed"] = failed
    _ = sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return int(failed > 0)


def main() -> None:
    """Run the opt-in local evaluation; no proposed tool is ever executed.

    Raises:
        SystemExit: Return the aggregate evaluation status to the shell.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--model",
        help="Override the model in deploy/capture-assist.json",
    )
    _ = parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print cases/prompts without contacting Ollama",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(evaluate(model=args.model, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
