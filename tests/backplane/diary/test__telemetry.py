"""Exercise private diary timing, completion correlation and failure outcomes."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import StatusCode, format_trace_id
from pydantic import AnyHttpUrl, ValidationError

from backplane.diary import telemetry
from backplane.diary.models import DiarySyncResult
from backplane.utils import SETTINGS
from backplane.utils.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_mock import MockerFixture


@pytest.fixture
def exporters(
    mocker: MockerFixture,
) -> Iterator[tuple[InMemorySpanExporter, InMemoryLogRecordExporter]]:
    """Capture completed SDK spans and logs before their normal network export.

    Args:
        mocker: Scoped patches for collector endpoints, exporters and sampling.

    Yields:
        In-memory span and log exporters receiving the actual telemetry.
    """
    endpoint = AnyHttpUrl("http://localhost")
    _ = mocker.patch.object(SETTINGS, "diary_otlp_traces_endpoint", endpoint)
    _ = mocker.patch.object(SETTINGS, "diary_otlp_logs_endpoint", endpoint)
    _ = mocker.patch.object(telemetry, "TraceIdRatioBased", return_value=ALWAYS_ON)

    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    _ = mocker.patch.object(telemetry, "OTLPSpanExporter", return_value=spans)
    _ = mocker.patch.object(telemetry, "OTLPLogExporter", return_value=logs)
    _ = mocker.patch.object(telemetry, "BatchSpanProcessor", SimpleSpanProcessor)
    _ = mocker.patch.object(
        telemetry,
        "BatchLogRecordProcessor",
        SimpleLogRecordProcessor,
    )

    telemetry._signals.cache_clear()
    yield spans, logs
    telemetry._signals.cache_clear()


@pytest.mark.parametrize("outcome", ["success", "partial", "error", "cancelled"])
async def test_completion_matches_timed_stage(
    exporters: tuple[InMemorySpanExporter, InMemoryLogRecordExporter],
    outcome: str,
) -> None:
    """Verify parentage, operational fields and propagated failures for sampled syncs.

    Args:
        exporters: SDK exporters holding the completed signals.
        outcome: Diary operation result to exercise.
    """
    result = DiarySyncResult(
        date=dt.date(2026, 10, 20),
        entries=1,
        missing=[],
        narrative_ready=False,
    )

    async def operation() -> DiarySyncResult:
        """Run one timed stage and propagate the selected result.

        Returns:
            A saved snapshot with no narrative.

        Raises:
            RuntimeError: A simulated source request contains a private message.
            asyncio.CancelledError: The caller cancelled the operation.
        """
        with telemetry.diary_stage("diary.home_assistant.collect"):
            if outcome == "error":
                message = "private request details"
                raise RuntimeError(message)
            if outcome == "cancelled":
                raise asyncio.CancelledError

            return await asyncio.sleep(0, result=result)

    call = telemetry.observe_sync(operation(), narrative=outcome == "partial")
    if outcome == "error":
        with pytest.raises(RuntimeError, match="private request details"):
            await call
    elif outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await call
    else:
        assert await call is result

    spans, logs = exporters
    child, root = spans.get_finished_spans()
    assert root.name == "diary.sync"
    assert child.name == "diary.home_assistant.collect"
    assert root.context is not None
    assert child.parent == root.context
    assert child.resource.attributes["service.name"] == "backplane"
    assert root.attributes == {"outcome": outcome}

    (completion,) = logs.get_finished_logs()
    record = completion.log_record
    assert record.trace_id == root.context.trace_id
    assert record.body == "diary.sync"
    assert record.attributes is not None
    duration = record.attributes["duration_ms"]
    assert isinstance(duration, int)
    assert duration >= 0
    assert record.attributes == {
        "operation": "diary.sync",
        "outcome": outcome,
        "trace_id": format_trace_id(root.context.trace_id),
        "duration_ms": duration,
    }
    if outcome == "error":
        assert child.status.status_code is StatusCode.ERROR
        assert root.status.status_code is StatusCode.ERROR
        assert not child.events
        assert not root.events


def test_incomplete_diary_enrollment() -> None:
    """Reject a partially configured pair of trace and log endpoints at startup."""
    with pytest.raises(ValidationError, match="both diary OTLP endpoints"):
        _ = Settings(
            obsidian_vault_path=SETTINGS.obsidian_vault_path,
            diary_otlp_traces_endpoint=AnyHttpUrl("http://localhost"),
        )
