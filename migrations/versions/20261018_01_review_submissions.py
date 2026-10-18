"""Persist review replies and their fenced processing/export state."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261018_01"
down_revision = "20260902_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the durable review-reply inbox."""
    op.create_table(
        "review_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.String(128)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("resolution", sa.JSON()),
        sa.Column("result", sa.Text()),
        sa.Column("assistant_reply", sa.Text()),
        sa.Column("error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["prompt_id"], ["capture_prompts.id"]),
        sa.UniqueConstraint("idempotency_key", name="uq_review_submissions_key"),
        sa.CheckConstraint(
            "kind IN ('diary', 'idea')",
            name="ck_review_submissions_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'needs_attention', 'saved')",
            name="ck_review_submissions_status",
        ),
    )
    op.create_index(
        "ix_review_submissions_status_created",
        "review_submissions",
        ["status", "created_at"],
    )


def downgrade() -> None:
    """Remove the review-reply inbox."""
    op.drop_table("review_submissions")
