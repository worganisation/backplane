"""Typed receipt, processing and completion contracts for phone review replies."""

from __future__ import annotations

import uuid
from typing import Annotated, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from backplane.diary.models import DiaryDecision

ConversationId = Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,128}$")]


class ReviewSubmissionCreate(BaseModel, frozen=True):
    """Original phone reply and destination, committed before model processing."""

    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    prompt_id: uuid.UUID
    kind: Literal["diary", "idea"]
    text: Annotated[str, Field(min_length=1, max_length=10000)]
    conversation_id: ConversationId | None = None

    @field_validator("idempotency_key", "text")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        """Reject empty submissions while preserving their exact original whitespace.

        Returns:
            The untouched input.

        Raises:
            ValueError: Input contains only whitespace.
        """
        if not value.strip():
            message = "Reply text and operation key must not be blank."
            raise ValueError(message)

        return value


class ReviewResolution(BaseModel, frozen=True):
    """First validated interpretation, reused unchanged for export retries."""

    decisions: Annotated[list[DiaryDecision], Field(max_length=100)] = Field(
        default_factory=list,
    )


class ReviewSubmission(BaseModel, frozen=True):
    """Durable receipt; only saved means its Obsidian export completed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prompt_id: uuid.UUID
    kind: Literal["diary", "idea"]
    text: str
    conversation_id: str | None
    status: Literal["pending", "processing", "needs_attention", "saved"]
    attempt_id: uuid.UUID | None
    archived_at: AwareDatetime | None
    started_at: AwareDatetime | None
    resolution: ReviewResolution | None
    result: str | None
    assistant_reply: str | None
    error: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ReviewAttempt(BaseModel, frozen=True):
    """A fenced attempt or an already completed/repaired save."""

    submission: ReviewSubmission
    request_text: str | None = None


class ReviewAttemptFinish(BaseModel, frozen=True):
    """Assistant speech is context, never proof of a successful save."""

    attempt_id: uuid.UUID
    assistant_reply: Annotated[str, Field(max_length=10000)] = ""
    conversation_id: ConversationId | None = None
