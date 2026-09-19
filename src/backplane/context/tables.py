"""SQLAlchemy tables for canonical context capture."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import final

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import SchemaItem

from backplane.context.schemas import JsonObject, utc_now


class ContextBase(DeclarativeBase):
    """Declarative base for Backplane's context database."""


@final
class ContextEventRow(ContextBase):
    """Durable source observation with idempotency and provenance."""

    __tablename__ = "context_events"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint(
            "user_id",
            "source",
            "idempotency_key",
            name="uq_context_events_idempotency",
        ),
        UniqueConstraint(
            "user_id",
            "source",
            "source_event_id",
            name="uq_context_events_source_event",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_context_events_confidence",
        ),
        Index("ix_context_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_context_events_user_kind", "user_id", "kind"),
        Index("ix_context_events_user_correlation", "user_id", "correlation_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(255))
    correlation_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(96), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    privacy_class: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    provenance: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    supersedes_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("context_events.id", ondelete="SET NULL"),
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


@final
class CapturePolicyRow(ContextBase):
    """Per-user prompt interruption policy."""

    __tablename__ = "capture_policies"
    __table_args__: tuple[SchemaItem, ...] = (
        CheckConstraint(
            "baseline_prompt_limit >= 0 AND baseline_prompt_limit <= 5",
            name="ck_capture_policies_baseline_limit",
        ),
        CheckConstraint(
            "context_prompt_limit >= 0 AND context_prompt_limit <= 20",
            name="ck_capture_policies_context_limit",
        ),
        CheckConstraint(
            "cooldown_seconds >= 0 AND cooldown_seconds <= 86400",
            name="ck_capture_policies_cooldown",
        ),
        CheckConstraint(
            "minimum_event_confidence >= 0 AND minimum_event_confidence <= 1",
            name="ck_capture_policies_minimum_confidence",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    baseline_prompt_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    context_prompt_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5400)
    minimum_event_confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.7,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


@final
class CapturePromptRow(ContextBase):
    """Canonical policy decision and prompt lifecycle."""

    __tablename__ = "capture_prompts"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint(
            "user_id",
            "source",
            "idempotency_key",
            name="uq_capture_prompts_idempotency",
        ),
        CheckConstraint(
            "priority >= 0 AND priority <= 100",
            name="ck_capture_prompts_priority",
        ),
        Index("ix_capture_prompts_user_created", "user_id", "created_at"),
        Index("ix_capture_prompts_user_delivered", "user_id", "delivered_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(96), nullable=False)
    budget_class: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    wording: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decision_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_for: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    dismissal_request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    dismissal_reason: Mapped[str | None] = mapped_column(String(500))
    expired_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expiration_request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    expiration_reason: Mapped[str | None] = mapped_column(String(500))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    delivery_context: Mapped[JsonObject] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    provenance: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


@final
class CapturePromptEventRow(ContextBase):
    """Many-to-many association between prompts and triggering events."""

    __tablename__ = "capture_prompt_events"

    prompt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("capture_prompts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("context_events.id", ondelete="CASCADE"),
        primary_key=True,
    )


@final
class CapturePromptStatusRow(ContextBase):
    """Durable prompt lifecycle transition."""

    __tablename__ = "capture_prompt_status_history"
    __table_args__: tuple[SchemaItem, ...] = (
        Index(
            "ix_capture_prompt_status_prompt_recorded",
            "prompt_id",
            "recorded_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("capture_prompts.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    recorded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    reason: Mapped[str | None] = mapped_column(String(500))


@final
class CaptureResponseRow(ContextBase):
    """Idempotent user response to a delivered prompt."""

    __tablename__ = "capture_responses"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint(
            "prompt_id",
            "idempotency_key",
            name="uq_capture_responses_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("capture_prompts.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    response_context: Mapped[JsonObject] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    provenance: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    responded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
