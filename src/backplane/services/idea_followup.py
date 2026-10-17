"""Bounded idea follow-ups using the canonical context event and prompt store."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from typing import TYPE_CHECKING, Annotated, final

from pydantic import BaseModel, Field
from sqlalchemy import select

from backplane.context.schemas import (
    CaptureDecisionReason,
    CapturePrompt,
    CapturePromptDeliveryRequest,
    CapturePromptEvaluationRequest,
    CapturePromptResponseRequest,
    CapturePromptStatus,
    ContextEventCreate,
    utc_now,
)
from backplane.context.tables import (
    CapturePromptEventRow,
    CapturePromptRow,
    CaptureResponseRow,
)
from backplane.services.context_capture import ContextCaptureService
from backplane.services.ideas import IdeaCapture, IdeaService
from backplane.utils import (
    SETTINGS,
    VAULT_PATHS,
    MarkdownDocument,
    atomic_write_text,
    exc,
    resolve_under_root,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from backplane.services.ideas import Capture

_USER = "will"
_SOURCE = "idea_followup"
_CADENCE = dt.timedelta(hours=24)
_MAX_ATTEMPTS = 2
_PROBE = re.compile(r"\b(?:GPT|QWEN)-(?:IDEA|TASK|\d{4})-", re.IGNORECASE)


class FollowupAvailability(BaseModel, frozen=True):
    """Live HA facts; missing or unknown signals must be sent as false."""

    home: bool = False
    receptive: bool = False
    outside_quiet_hours: bool = False


class IdeaFollowup(BaseModel, frozen=True):
    """A notification's exact idea and durable prompt identity."""

    prompt: CapturePrompt
    idea: IdeaCapture
    elaborations: list[str] = Field(default_factory=list)


class IdeaElaboration(BaseModel, frozen=True):
    """An immutable elaboration associated with the original idea ID."""

    capture_id: Annotated[str, Field(min_length=1)]
    text: Annotated[str, Field(min_length=1, max_length=10000)]


@final
class IdeaFollowupService(ContextCaptureService):
    """Single-user follow-up workflow over the shared durable context tables."""

    async def reserve(self, availability: FollowupAvailability) -> IdeaFollowup | None:
        """Claim at most one notification; retries never return an existing claim.

        Returns:
            A newly reserved prompt, or None when unavailable or budget-limited.
        """
        if not all((
            availability.home,
            availability.receptive,
            availability.outside_quiet_hours,
        )):
            return None

        linked = await self._linked_captures()
        captures = [
            capture
            for capture in await IdeaService.load_captures()
            if capture.id not in linked
        ]
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            policy = await self._policy_row(session, _USER, lock=True)
            prompts = list(
                (
                    await session.scalars(
                        select(CapturePromptRow)
                        .where(
                            CapturePromptRow.user_id == _USER,
                            CapturePromptRow.source == _SOURCE,
                        )
                        .order_by(CapturePromptRow.created_at),
                    )
                ).all(),
            )
            if any(now - prompt.created_at < _CADENCE for prompt in prompts):
                return None

            capture = await self._candidate(session, captures, prompts, now)
            if capture is None:
                return None

            attempt = 1 + sum(
                prompt.provenance.get("capture_id") == capture.id for prompt in prompts
            )
            event = await self._ingest_event(
                session,
                ContextEventCreate(
                    user_id=_USER,
                    source=_SOURCE,
                    source_event_id=capture.id,
                    idempotency_key=capture.id,
                    kind="idea",
                    occurred_at=dt.datetime.fromisoformat(
                        f"{capture.date}T{capture.time}",
                    ).replace(tzinfo=SETTINGS.local_timezone),
                    timezone=str(SETTINGS.local_timezone),
                    payload={"capture_id": capture.id, "original_text": capture.text},
                ),
            )
            request = CapturePromptEvaluationRequest(
                user_id=_USER,
                source=_SOURCE,
                idempotency_key=f"{capture.id}:{attempt}",
                kind="idea_development",
                event_ids=[event.event.id],
                reason="Home, receptive and outside quiet hours",
                wording=f"Have a moment to develop this idea? {capture.text[:350]}",
                expires_at=now + dt.timedelta(hours=12),
                provenance={"capture_id": capture.id, "attempt": attempt},
            )
            day_start, day_end = self._local_day_bounds(now, policy.timezone)
            if (
                await self._next_allowed_schedule(session, policy, _USER, now) > now
                or await self._reserved_prompt_count(session, request, day_start, day_end)
                >= policy.context_prompt_limit
            ):
                return None

            prompt_id = uuid.uuid4()
            row, created = await self._persist_prompt(
                session,
                request,
                prompt_id=prompt_id,
                values=self._prompt_insert_values(
                    request,
                    prompt_id=prompt_id,
                    request_fingerprint=self._prompt_request_fingerprint(request),
                    reason=CaptureDecisionReason.ALLOWED,
                    scheduled_for=now,
                    now=now,
                ),
            )
            if not created:
                return None

            session.add(CapturePromptEventRow(prompt_id=row.id, event_id=event.event.id))
            self._record_prompt_status(
                session,
                prompt_id=row.id,
                status=CapturePromptStatus.SCHEDULED,
                occurred_at=now,
            )
            await session.flush()
            prompt = await self._prompt_from_row(session, row)

        return IdeaFollowup(prompt=prompt, idea=await IdeaService.get_idea(capture.id))

    @staticmethod
    async def _linked_captures() -> set[str]:
        directory = await resolve_under_root(VAULT_PATHS.task_notes_dir)
        linked: set[str] = set()
        if not await directory.is_dir():
            return linked

        async for path in directory.rglob("*.md"):
            relative = VAULT_PATHS.task_notes_dir / path.relative_to(directory)
            async with MarkdownDocument(
                vault_path=relative,
                read_only=True,
            ) as note:
                if isinstance(capture_id := note.frontmatter.get("source_capture"), str):
                    linked.add(capture_id)

        return linked

    @staticmethod
    async def _candidate(
        session: AsyncSession,
        captures: Sequence[Capture],
        prompts: Sequence[CapturePromptRow],
        now: dt.datetime,
    ) -> Capture | None:
        for capture in captures:
            if capture.kind != "idea" or _PROBE.search(capture.text):
                continue

            previous = [
                prompt
                for prompt in prompts
                if prompt.provenance.get("capture_id") == capture.id
            ]
            if not previous:
                return capture
            if len(previous) >= _MAX_ATTEMPTS:
                continue

            latest = previous[-1]
            responses = list(
                (
                    await session.scalars(
                        select(CaptureResponseRow).where(
                            CaptureResponseRow.prompt_id.in_([
                                prompt.id for prompt in previous
                            ]),
                        ),
                    )
                ).all(),
            )
            snooze = next(
                (
                    response
                    for response in responses
                    if response.prompt_id == latest.id
                    and response.response_kind == "snooze"
                ),
                None,
            )
            if (
                latest.status == CapturePromptStatus.RESPONDED.value
                and snooze is not None
                and now >= snooze.responded_at + _CADENCE
                and not any(
                    response.response_kind == "elaboration" for response in responses
                )
            ):
                return capture

        return None

    async def get(self, prompt_id: uuid.UUID | None = None) -> IdeaFollowup | None:
        """Read an exact notification or the current unexpired conversational context.

        Returns:
            Original idea plus saved elaborations, or None when no prompt is active.
        """
        async with self._session_factory() as session:
            query = select(CapturePromptRow).where(
                CapturePromptRow.source == _SOURCE,
                CapturePromptRow.user_id == _USER,
            )
            if prompt_id is not None:
                query = query.where(CapturePromptRow.id == prompt_id)
            else:
                query = query.where(
                    CapturePromptRow.status.in_([
                        CapturePromptStatus.DELIVERED.value,
                        CapturePromptStatus.RESPONDED.value,
                    ]),
                    CapturePromptRow.expires_at > utc_now(),
                )
            row = await session.scalar(
                query.order_by(CapturePromptRow.created_at.desc()).limit(1),
            )
            if row is None:
                return None

            if (
                prompt_id is None
                and await session.scalar(
                    select(CaptureResponseRow.id).where(
                        CaptureResponseRow.prompt_id == row.id,
                        CaptureResponseRow.response_kind == "snooze",
                    ),
                )
                is not None
            ):
                return None

            prompt = await self._prompt_from_row(session, row)
            capture_id = str(row.provenance["capture_id"])
            related_ids = [
                related.id
                for related in (
                    await session.scalars(
                        select(CapturePromptRow).where(
                            CapturePromptRow.source == _SOURCE,
                            CapturePromptRow.user_id == _USER,
                        ),
                    )
                ).all()
                if related.provenance.get("capture_id") == capture_id
            ]
            elaborations = list(
                (
                    await session.scalars(
                        select(CaptureResponseRow.text)
                        .join(
                            CapturePromptRow,
                            CaptureResponseRow.prompt_id == CapturePromptRow.id,
                        )
                        .where(
                            CapturePromptRow.source == _SOURCE,
                            CaptureResponseRow.response_kind == "elaboration",
                        )
                        .where(CaptureResponseRow.prompt_id.in_(related_ids))
                        .order_by(CaptureResponseRow.created_at),
                    )
                ).all(),
            )

        return IdeaFollowup(
            prompt=prompt,
            idea=await IdeaService.get_idea(capture_id),
            elaborations=[text for text in elaborations if text],
        )

    async def mark_submitted(self, prompt_id: uuid.UUID) -> CapturePrompt:
        """Record HA submission without claiming confirmed phone receipt.

        Returns:
            The durable notification submission record.
        """
        return await self.mark_delivered(
            prompt_id,
            CapturePromptDeliveryRequest(
                delivery_context={
                    "transport": "script.notify_will",
                    "receipt_confirmed": False,
                },
            ),
        )

    async def snooze(self, prompt_id: uuid.UUID) -> CapturePrompt:
        """Snooze once for at least 24 hours, recording the button press idempotently.

        Returns:
            Updated prompt; a second notification has no automatic retry.

        Raises:
            NotFoundError: If this is not an idea-follow-up prompt.
        """
        followup = await self.get(prompt_id)
        if followup is None:
            raise exc.NotFoundError(message="Idea follow-up not found.")

        if followup.prompt.status == CapturePromptStatus.SCHEDULED:
            _ = await self.mark_submitted(prompt_id)

        result = await self.respond(
            prompt_id,
            CapturePromptResponseRequest(
                idempotency_key="snooze",
                response_kind="snooze",
            ),
        )
        return result.prompt

    async def elaborate(self, prompt_id: uuid.UUID, request: IdeaElaboration) -> str:
        """Append exact user wording and export an immutable Obsidian development note.

        Returns:
            Wikilink to the saved elaboration. Retrying the same text repairs its export.

        Raises:
            ConflictError: If the supplied idea does not match the notification.
        """
        followup = await self.get(prompt_id)
        if followup is None or followup.idea.id != request.capture_id:
            raise exc.ConflictError(
                message="Read the follow-up and use its exact capture ID before saving.",
            )

        result = await self.respond(
            prompt_id,
            CapturePromptResponseRequest(
                idempotency_key=hashlib.sha256(request.text.encode()).hexdigest(),
                response_kind="elaboration",
                text=request.text,
                payload={"capture_id": request.capture_id},
            ),
        )
        relative = (
            VAULT_PATHS.inbox_dir
            / "Idea development"
            / request.capture_id
            / f"{result.response.id}.md"
        )
        original = followup.idea.path.with_suffix("").as_posix()
        content = (
            f"---\ncapture_id: {request.capture_id}\nprompt_id: {prompt_id}\n"
            f"response_id: {result.response.id}\ncreated: {result.response.created_at.isoformat()}\n---\n"
            f"# Idea development\n\nOriginal: [[{original}]]\n\n{request.text}\n"
        )
        await atomic_write_text(await resolve_under_root(relative), content)
        return f"[[{relative.with_suffix('').as_posix()}]]"
