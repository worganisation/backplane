"""Functional idea-follow-up persistence, interruption and retry coverage."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

import pytest

from backplane.context.schemas import (
    CapturePolicyUpdate,
    CapturePromptDeliveryRequest,
    CapturePromptDismissRequest,
)
from backplane.mcp.tasks import capture_task, link_task_to_capture
from backplane.services.idea_followup import (
    FollowupAvailability,
    IdeaElaboration,
    IdeaFollowupService,
)
from backplane.services.ideas import IdeaService
from backplane.utils import VAULT_PATHS, exc, resolve_under_root

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backplane.utils import AsyncPath

AVAILABLE = FollowupAvailability(home=True, receptive=True, outside_quiet_hours=True)


@pytest.fixture
def followups(
    context_session_factory: async_sessionmaker[AsyncSession],
    obsidian_vault: AsyncPath,
) -> IdeaFollowupService:
    """Provide the workflow with an isolated database and vault."""
    _ = obsidian_vault
    return IdeaFollowupService(context_session_factory)


async def test_round_trip_preserves_original_and_repairs_export(
    followups: IdeaFollowupService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saved response survives an export failure and retries produce one note."""
    idea = await IdeaService.record(
        "Maybe build a rainwater monitor.\nKeep this exact wording.",
    )
    original = await (await resolve_under_root(idea.path)).read_text()
    followup = await followups.reserve(AVAILABLE)
    assert followup is not None
    assert await followups.reserve(AVAILABLE) is None
    assert await followups.get() is None
    delivered = await followups.mark_delivered(
        followup.prompt.id,
        CapturePromptDeliveryRequest(),
    )
    assert delivered.status == "delivered"
    assert await followups.get() is not None
    request = IdeaElaboration(
        capture_id=idea.id,
        text="Start with one tank and a float sensor.",
    )

    async def fail_export(*_args: object) -> None:
        await asyncio.sleep(0)
        message = "disk full"
        raise OSError(message)

    with monkeypatch.context() as patch:
        patch.setattr("backplane.services.idea_followup.atomic_write_text", fail_export)
        with pytest.raises(OSError, match="disk full"):
            await followups.elaborate(followup.prompt.id, request)

    restored = await followups.get(followup.prompt.id)
    assert restored is not None
    assert restored.elaborations == [request.text]
    link = await followups.elaborate(followup.prompt.id, request)
    assert await followups.elaborate(followup.prompt.id, request) == link
    development = await (await resolve_under_root(link[2:-2] + ".md")).read_text()
    assert request.text in development
    assert idea.id in development
    assert await (await resolve_under_root(idea.path)).read_text() == original
    with pytest.raises(exc.ConflictError):
        await followups.elaborate(
            followup.prompt.id,
            IdeaElaboration(capture_id="wrong", text="No"),
        )


@pytest.mark.parametrize("missing", ["home", "receptive", "outside_quiet_hours"])
async def test_unavailable_never_reserves(
    followups: IdeaFollowupService,
    missing: str,
) -> None:
    """Every availability signal must be affirmatively true."""
    _ = await IdeaService.record("Try a greenhouse sensor")
    assert await followups.reserve(AVAILABLE.model_copy(update={missing: False})) is None
    assert await followups.reserve(AVAILABLE) is not None


async def test_snooze_is_bounded_and_idempotent(
    followups: IdeaFollowupService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snooze allows exactly one later notification, never immediate repeats."""
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr("backplane.services.idea_followup.utc_now", lambda: now)
    _ = await IdeaService.record("Try a greenhouse sensor")
    first = await followups.reserve(AVAILABLE)
    assert first is not None
    _ = await followups.mark_delivered(first.prompt.id, CapturePromptDeliveryRequest())
    _ = await followups.snooze(first.prompt.id)
    _ = await followups.snooze(first.prompt.id)
    assert await followups.get() is None
    assert await followups.reserve(AVAILABLE) is None
    now += dt.timedelta(days=1, minutes=1)
    second = await followups.reserve(AVAILABLE)
    assert second is not None
    assert second.idea.id == first.idea.id
    assert second.prompt.id != first.prompt.id
    _ = await followups.mark_delivered(second.prompt.id, CapturePromptDeliveryRequest())
    _ = await followups.snooze(second.prompt.id)
    now += dt.timedelta(days=2)
    assert await followups.reserve(AVAILABLE) is None


@pytest.mark.parametrize("action", ["dismiss", "ignore", "elaborate"])
async def test_no_nagging_after_prompt(
    followups: IdeaFollowupService,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """Ignored, dismissed or expanded captures do not receive another prompt."""
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr("backplane.services.idea_followup.utc_now", lambda: now)
    _ = await IdeaService.record("GPT-IDEA-1710 test probe")
    idea = await IdeaService.record("Try a greenhouse sensor")
    first = await followups.reserve(AVAILABLE)
    assert first is not None
    assert first.idea.id == idea.id
    _ = await followups.mark_delivered(first.prompt.id, CapturePromptDeliveryRequest())
    if action == "dismiss":
        _ = await followups.dismiss(first.prompt.id, CapturePromptDismissRequest())
    elif action == "elaborate":
        _ = await followups.elaborate(
            first.prompt.id,
            IdeaElaboration(capture_id=idea.id, text="Use one probe"),
        )

    now += dt.timedelta(days=2)
    assert await followups.get() is None
    assert await followups.reserve(AVAILABLE) is None


async def test_concurrent_reservations_claim_once(followups: IdeaFollowupService) -> None:
    """Concurrent callers share a database interruption lock."""
    _ = await IdeaService.record("Try a greenhouse sensor")
    _ = await IdeaService.record("Try a rain sensor")
    results = await asyncio.gather(*(followups.reserve(AVAILABLE) for _ in range(3)))
    assert sum(result is not None for result in results) == 1


async def test_zero_budget_and_empty_vault(followups: IdeaFollowupService) -> None:
    """No candidate and owner-disabled policies both suppress notifications."""
    assert await followups.reserve(AVAILABLE) is None
    _ = await IdeaService.record("Try a greenhouse sensor")
    _ = await followups.update_policy("will", CapturePolicyUpdate(context_prompt_limit=0))
    assert await followups.reserve(AVAILABLE) is None


async def test_linked_task_excludes_capture(followups: IdeaFollowupService) -> None:
    """An idea already turned into an actionable task needs no automatic prompt."""
    idea = await IdeaService.record("Build the greenhouse sensor")
    task = await resolve_under_root("Tasks/Tasks/sensor.md")
    await task.parent.mkdir(parents=True, exist_ok=True)
    _ = await task.write_text(f"---\nsource_capture: {idea.id}\n---\n# Build sensor\n")
    assert await followups.reserve(AVAILABLE) is None


async def test_snooze_recovers_missed_submission_callback(
    followups: IdeaFollowupService,
) -> None:
    """A real button action can recover a lost submission acknowledgement."""
    _ = await IdeaService.record("Try a greenhouse sensor")
    first = await followups.reserve(AVAILABLE)
    assert first is not None
    snoozed = await followups.snooze(first.prompt.id)
    assert snoozed.status == "responded"
    submitted = await followups.mark_submitted(first.prompt.id)
    assert submitted.delivery_context["receipt_confirmed"] is False
    assert await followups.reserve(AVAILABLE) is None


async def test_commit_to_projectless_task_without_model(
    followups: IdeaFollowupService,
    mocker: MockerFixture,
) -> None:
    """Explicit commitment uses fast capture then an exact link without inference."""
    extraction = mocker.patch("backplane.services.tasks._extract_metadata")
    board = await resolve_under_root(VAULT_PATHS.task_board_path)
    await board.parent.mkdir(parents=True, exist_ok=True)
    _ = await board.write_text("## Backlog\n\n")

    idea = await IdeaService.record("Maybe build a greenhouse sensor")
    first = await followups.reserve(AVAILABLE)
    assert first is not None
    _ = await followups.mark_submitted(first.prompt.id)
    _ = await followups.elaborate(
        first.prompt.id,
        IdeaElaboration(capture_id=idea.id, text="Build one outdoor temperature probe."),
    )

    task = await capture_task(
        description="Build one outdoor temperature probe.",
        idempotency_key="commit-probe",
    )
    _ = await link_task_to_capture(task_slug=task.metadata.path.stem, capture_id=idea.id)
    extraction.assert_not_called()

    stored = await (await resolve_under_root(task.metadata.path)).read_text()
    assert f"source_capture: {idea.id}" in stored
    assert "Build one outdoor temperature probe." in stored
    assert (await IdeaService.get_idea(idea.id)).text == idea.text
