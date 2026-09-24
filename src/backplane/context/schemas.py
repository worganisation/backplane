"""Public context-capture contracts shared by REST, MCP, and service callers."""

from __future__ import annotations

import datetime as dt
import enum
import uuid
import zoneinfo
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, JsonValue, model_validator

JsonObject = dict[str, JsonValue]


class ContextEventStatus(enum.StrEnum):
    """Lifecycle status for a contextual observation."""

    OBSERVED = enum.auto()
    TENTATIVE = enum.auto()
    CONFIRMED = enum.auto()
    DISMISSED = enum.auto()
    SUPERSEDED = enum.auto()


class PrivacyClass(enum.StrEnum):
    """Sensitivity class controlling later rendering and disclosure."""

    PRIVATE = enum.auto()
    SENSITIVE = enum.auto()
    SHARED = enum.auto()


class CapturePromptStatus(enum.StrEnum):
    """Lifecycle status for a capture prompt."""

    CANDIDATE = enum.auto()
    SCHEDULED = enum.auto()
    DELIVERED = enum.auto()
    RESPONDED = enum.auto()
    DISMISSED = enum.auto()
    EXPIRED = enum.auto()
    CANCELLED = enum.auto()


class CaptureDecisionReason(enum.StrEnum):
    """Stable policy outcomes returned to prompt producers."""

    ALLOWED = enum.auto()
    IDEMPOTENT = enum.auto()
    DUPLICATE_EVENT = enum.auto()
    COOLDOWN = enum.auto()
    DAILY_BUDGET = enum.auto()
    INELIGIBLE_EVENT = enum.auto()


class CaptureBudgetClass(enum.StrEnum):
    """Independent daily prompt-budget buckets."""

    BASELINE = enum.auto()
    CONTEXT = enum.auto()


class ContextEventCreate(BaseModel, frozen=True):
    """Idempotent context-event ingestion request."""

    user_id: Annotated[str, Field(min_length=1, max_length=128)]
    source: Annotated[str, Field(min_length=1, max_length=64)]
    source_event_id: Annotated[str | None, Field(max_length=255)] = None
    correlation_key: Annotated[str | None, Field(max_length=255)] = None
    idempotency_key: Annotated[str, Field(min_length=1, max_length=255)]
    kind: Annotated[str, Field(min_length=1, max_length=96)]
    occurred_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0
    privacy_class: PrivacyClass = PrivacyClass.PRIVATE
    status: ContextEventStatus = ContextEventStatus.OBSERVED
    summary: Annotated[str | None, Field(max_length=500)] = None
    payload: JsonObject = Field(default_factory=dict)
    provenance: JsonObject = Field(default_factory=dict)
    supersedes_event_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_time_range(self) -> ContextEventCreate:
        try:
            _ = zoneinfo.ZoneInfo(self.timezone)
        except zoneinfo.ZoneInfoNotFoundError as error:
            msg = f"Unknown event timezone {self.timezone!r}"
            raise ValueError(msg) from error
        if self.ended_at is not None and self.ended_at < self.occurred_at:
            msg = "ended_at must not precede occurred_at"
            raise ValueError(msg)
        return self


class ContextEvent(BaseModel, frozen=True):
    """Canonical contextual observation."""

    id: uuid.UUID
    user_id: str
    source: str
    source_event_id: str | None
    correlation_key: str | None
    idempotency_key: str
    kind: str
    occurred_at: AwareDatetime
    ended_at: AwareDatetime | None
    timezone: str
    confidence: float
    privacy_class: PrivacyClass
    status: ContextEventStatus
    summary: str | None
    payload: JsonObject
    provenance: JsonObject
    supersedes_event_id: uuid.UUID | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ContextEventResult(BaseModel, frozen=True):
    """Single idempotent ingestion result."""

    event: ContextEvent
    created: bool


class ContextEventBatchCreate(BaseModel, frozen=True):
    """Atomic context-event batch ingestion request."""

    events: Annotated[list[ContextEventCreate], Field(min_length=1, max_length=100)]


class ContextEventBatchResult(BaseModel, frozen=True):
    """Atomic context-event batch ingestion result."""

    results: list[ContextEventResult]


class CapturePolicy(BaseModel, frozen=True):
    """Per-user prompt budget and cooldown policy."""

    user_id: str
    timezone: str
    baseline_prompt_limit: int
    context_prompt_limit: int
    cooldown_seconds: int
    minimum_event_confidence: float
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CapturePolicyUpdate(BaseModel, frozen=True):
    """Mutable capture-policy fields."""

    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    baseline_prompt_limit: Annotated[int, Field(ge=0, le=5)] = 1
    context_prompt_limit: Annotated[int, Field(ge=0, le=20)] = 2
    cooldown_seconds: Annotated[int, Field(ge=0, le=86400)] = 5400
    minimum_event_confidence: Annotated[float, Field(ge=0, le=1)] = 0.7


class CapturePromptEvaluationRequest(BaseModel, frozen=True):
    """Candidate prompt submitted for deterministic global policy evaluation."""

    user_id: Annotated[str, Field(min_length=1, max_length=128)]
    source: Annotated[str, Field(min_length=1, max_length=64)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=255)]
    kind: Annotated[str, Field(min_length=1, max_length=96)]
    budget_class: CaptureBudgetClass = CaptureBudgetClass.CONTEXT
    event_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=20)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    priority: Annotated[int, Field(ge=0, le=100)] = 50
    wording: Annotated[str | None, Field(max_length=500)] = None
    scheduled_for: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    provenance: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_schedule(self) -> CapturePromptEvaluationRequest:
        if (
            self.scheduled_for is not None
            and self.expires_at is not None
            and self.expires_at <= self.scheduled_for
        ):
            msg = "expires_at must follow scheduled_for"
            raise ValueError(msg)
        if len(set(self.event_ids)) != len(self.event_ids):
            msg = "event_ids must not contain duplicates"
            raise ValueError(msg)
        return self


class CapturePromptStatusChange(BaseModel, frozen=True):
    """One durable transition in a prompt's lifecycle."""

    id: uuid.UUID
    prompt_id: uuid.UUID
    status: CapturePromptStatus
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    reason: str | None


class CapturePrompt(BaseModel, frozen=True):
    """Canonical prompt and policy-decision record."""

    id: uuid.UUID
    user_id: str
    source: str
    idempotency_key: str
    kind: str
    budget_class: CaptureBudgetClass
    event_ids: list[uuid.UUID]
    status_history: list[CapturePromptStatusChange]
    reason: str
    priority: int
    wording: str | None
    status: CapturePromptStatus
    decision_reason: CaptureDecisionReason
    scheduled_for: AwareDatetime | None
    expires_at: AwareDatetime | None
    delivered_at: AwareDatetime | None
    responded_at: AwareDatetime | None
    dismissed_at: AwareDatetime | None
    dismissal_reason: str | None
    expired_at: AwareDatetime | None
    expiration_reason: str | None
    cancelled_at: AwareDatetime | None
    cancellation_reason: str | None
    delivery_context: JsonObject
    provenance: JsonObject
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CapturePromptEvaluationResult(BaseModel, frozen=True):
    """Prompt-policy outcome and canonical prompt record."""

    allowed: bool
    reason: CaptureDecisionReason
    prompt: CapturePrompt
    created: bool


class CapturePromptDeliveryRequest(BaseModel, frozen=True):
    """Successful notification-delivery record."""

    delivered_at: AwareDatetime | None = None
    delivery_context: JsonObject = Field(default_factory=dict)


class CapturePromptResponseRequest(BaseModel, frozen=True):
    """Idempotent response captured from a delivered prompt."""

    idempotency_key: Annotated[str, Field(min_length=1, max_length=255)]
    response_kind: Annotated[str, Field(min_length=1, max_length=64)]
    text: Annotated[str | None, Field(max_length=10000)] = None
    payload: JsonObject = Field(default_factory=dict)
    response_context: JsonObject = Field(default_factory=dict)
    provenance: JsonObject = Field(default_factory=dict)
    responded_at: AwareDatetime | None = None


class CapturePromptDismissRequest(BaseModel, frozen=True):
    """Prompt dismissal record."""

    dismissed_at: AwareDatetime | None = None
    reason: Annotated[str, Field(min_length=1, max_length=500)] = "user_dismissed"


class CapturePromptExpireRequest(BaseModel, frozen=True):
    """Prompt expiry record."""

    expired_at: AwareDatetime | None = None
    reason: Annotated[str, Field(min_length=1, max_length=500)] = "stale"


class CaptureResponse(BaseModel, frozen=True):
    """Canonical user response attached to a capture prompt."""

    id: uuid.UUID
    prompt_id: uuid.UUID
    idempotency_key: str
    response_kind: str
    text: str | None
    payload: JsonObject
    response_context: JsonObject
    provenance: JsonObject
    responded_at: AwareDatetime
    created_at: AwareDatetime


class ContextEventList(BaseModel, frozen=True):
    """Bounded context query response."""

    events: list[ContextEvent]


class CapturePromptResponseResult(BaseModel, frozen=True):
    """Prompt plus its idempotent response."""

    prompt: CapturePrompt
    response: CaptureResponse
    created: bool


PromptTerminalAction = Literal["dismiss", "expire"]


def utc_now() -> dt.datetime:
    """Return a timezone-aware UTC timestamp."""
    return dt.datetime.now(tz=dt.UTC)
