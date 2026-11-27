# ruff:file-ignore[import-private-name] -- The OpenTelemetry Logs API and OTLP log exporter use underscored namespaces.
"""Export sampled diary timings and correlated completion records to private collectors."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache
from time import monotonic_ns
from typing import TYPE_CHECKING

from opentelemetry._logs import SeverityNumber
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import StatusCode

from backplane.utils import SETTINGS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Generator

    from opentelemetry._logs import Logger
    from opentelemetry.trace import Tracer

    from backplane.diary.models import DiarySyncResult

_active_tracer: ContextVar[Tracer | None] = ContextVar("diary_sync_tracer", default=None)


@cache
def _signals() -> tuple[Tracer, Logger] | None:
    """Create process-local batch exporters when the deployment enrolls diary sync.

    Returns:
        Private tracer and logger for diary operations, or None when disabled.
    """
    traces_endpoint = SETTINGS.diary_otlp_traces_endpoint
    logs_endpoint = SETTINGS.diary_otlp_logs_endpoint
    if traces_endpoint is None or logs_endpoint is None:
        return None

    resource = Resource({"service.name": "backplane"})
    traces = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(0.25)),
    )
    traces.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=str(traces_endpoint), timeout=3)),
    )

    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=str(logs_endpoint), timeout=3)),
    )
    return traces.get_tracer("backplane.diary"), logs.get_logger("backplane.diary")


@contextmanager
def diary_stage(name: str) -> Generator[None]:
    """Measure one fixed operation within a sampled diary sync.

    Args:
        name: Static stage name from the diary service.

    Yields:
        Control to the operation being timed.
    """
    if (tracer := _active_tracer.get()) is None:
        yield
        return

    with tracer.start_as_current_span(
        name,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield
        except BaseException:
            span.set_status(StatusCode.ERROR)
            raise


async def observe_sync(
    operation: Awaitable[DiarySyncResult],
    *,
    narrative: bool,
) -> DiarySyncResult:
    """Run a sync and enqueue private timing and outcome signals for sampled requests.

    Args:
        operation: The pending diary sync.
        narrative: Whether the caller requested a narrative in the exported note.

    Returns:
        The sync result, including any missing inputs or pending narrative.

    Raises:
        asyncio.CancelledError: The caller cancelled the sync.
    """
    if (signals := _signals()) is None:
        return await operation

    tracer, logger = signals
    with tracer.start_as_current_span(
        "diary.sync",
        context=Context(),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        if not span.is_recording():
            return await operation

        started = monotonic_ns()
        outcome = "error"
        try:
            with _active_tracer.set(tracer):
                result = await operation

        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        else:
            outcome = (
                "partial"
                if result.missing or (narrative and not result.narrative_ready)
                else "success"
            )
            return result
        finally:
            span.set_attribute("outcome", outcome)
            if outcome == "error":
                span.set_status(StatusCode.ERROR)

            logger.emit(
                body="diary.sync",
                severity_number=SeverityNumber.INFO
                if outcome == "success"
                else SeverityNumber.WARN,
                attributes={
                    "operation": "diary.sync",
                    "outcome": outcome,
                    "duration_ms": (monotonic_ns() - started) // 1_000_000,
                },
            )
