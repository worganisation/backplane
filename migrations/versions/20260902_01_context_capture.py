"""Create canonical context-capture tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260902_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def upgrade() -> None:
    """Create the context event, policy, prompt, and response ledger."""
    op.create_table(
        "context_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.String(length=255)),
        sa.Column("correlation_key", sa.String(length=255)),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=96), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("privacy_class", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.String(length=500)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("supersedes_event_id", sa.Uuid()),
        *_timestamps(),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_context_events_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_event_id"],
            ["context_events.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source",
            "idempotency_key",
            name="uq_context_events_idempotency",
        ),
        sa.UniqueConstraint(
            "user_id",
            "source",
            "source_event_id",
            name="uq_context_events_source_event",
        ),
    )
    op.create_index(
        "ix_context_events_user_correlation",
        "context_events",
        ["user_id", "correlation_key"],
    )
    op.create_index(
        "ix_context_events_user_kind",
        "context_events",
        ["user_id", "kind"],
    )
    op.create_index(
        "ix_context_events_user_occurred",
        "context_events",
        ["user_id", "occurred_at"],
    )

    op.create_table(
        "capture_policies",
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("baseline_prompt_limit", sa.Integer(), nullable=False),
        sa.Column("context_prompt_limit", sa.Integer(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("minimum_event_confidence", sa.Float(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "baseline_prompt_limit >= 0 AND baseline_prompt_limit <= 5",
            name="ck_capture_policies_baseline_limit",
        ),
        sa.CheckConstraint(
            "context_prompt_limit >= 0 AND context_prompt_limit <= 20",
            name="ck_capture_policies_context_limit",
        ),
        sa.CheckConstraint(
            "cooldown_seconds >= 0 AND cooldown_seconds <= 86400",
            name="ck_capture_policies_cooldown",
        ),
        sa.CheckConstraint(
            "minimum_event_confidence >= 0 AND minimum_event_confidence <= 1",
            name="ck_capture_policies_minimum_confidence",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "capture_prompts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=96), nullable=False),
        sa.Column("budget_class", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("wording", sa.String(length=500)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision_reason", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_request_fingerprint", sa.String(length=64)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("dismissal_request_fingerprint", sa.String(length=64)),
        sa.Column("dismissal_reason", sa.String(length=500)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("expiration_request_fingerprint", sa.String(length=64)),
        sa.Column("expiration_reason", sa.String(length=500)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancellation_reason", sa.String(length=500)),
        sa.Column("delivery_context", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 100",
            name="ck_capture_prompts_priority",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source",
            "idempotency_key",
            name="uq_capture_prompts_idempotency",
        ),
    )
    op.create_index(
        "ix_capture_prompts_user_created",
        "capture_prompts",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_capture_prompts_user_delivered",
        "capture_prompts",
        ["user_id", "delivered_at"],
    )

    op.create_table(
        "capture_prompt_events",
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["context_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["capture_prompts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("prompt_id", "event_id"),
    )

    op.create_table(
        "capture_prompt_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reason", sa.String(length=500)),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["capture_prompts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_capture_prompt_status_prompt_recorded",
        "capture_prompt_status_history",
        ["prompt_id", "recorded_at"],
    )

    op.create_table(
        "capture_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_kind", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("response_context", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["capture_prompts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prompt_id",
            "idempotency_key",
            name="uq_capture_responses_idempotency",
        ),
    )


def downgrade() -> None:
    """Drop all context-capture tables."""
    op.drop_table("capture_responses")
    op.drop_index(
        "ix_capture_prompt_status_prompt_recorded",
        table_name="capture_prompt_status_history",
    )
    op.drop_table("capture_prompt_status_history")
    op.drop_table("capture_prompt_events")
    op.drop_index("ix_capture_prompts_user_delivered", table_name="capture_prompts")
    op.drop_index("ix_capture_prompts_user_created", table_name="capture_prompts")
    op.drop_table("capture_prompts")
    op.drop_table("capture_policies")
    op.drop_index("ix_context_events_user_occurred", table_name="context_events")
    op.drop_index("ix_context_events_user_kind", table_name="context_events")
    op.drop_index("ix_context_events_user_correlation", table_name="context_events")
    op.drop_table("context_events")
