"""Tests for distinct idea capture storage and compatible retrieval."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

import pytest

from backplane.api.routers.daily_notes import create_idea, get_idea, list_ideas
from backplane.api.schemas import IdeaRequest
from backplane.mcp import obsidian
from backplane.services.ideas import IDEA_NOTES_DIR, IdeaService
from backplane.services.obsidian import ObsidianService
from backplane.services.tasks import (
    TaskMetadata,
    TaskService,
    _build_task_note,
    _load_recent_captures,
)
from backplane.services.vault_search import VaultSearchService
from backplane.utils import VAULT_PATHS, exc, today

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from backplane.utils import AsyncPath


async def test__same_minute_ideas_are_distinct_and_preserve_raw_text(
    obsidian_vault: AsyncPath,
    mocker: MockerFixture,
) -> None:
    """Separate calls in a frozen minute preserve headings, spaces and trailing newlines."""
    now = dt.datetime.now(tz=dt.UTC)
    mocker.patch("backplane.services.ideas.dt", wraps=dt).datetime.now.return_value = now
    raw = "  Maybe try this?\n\n# Original heading\n\n- [ ] First step  \n\r\n"

    first = await IdeaService.record(raw)
    second = await IdeaService.record("A different idea")

    assert first.id != second.id
    assert first.date == second.date
    assert first.time == second.time
    mocker.stopall()
    assert await IdeaService.get_idea(first.id) == first
    assert await IdeaService.get_idea(second.id) == second
    assert first.text == raw
    async with await (obsidian_vault / first.path).open(newline="") as source:
        assert (await source.read()).endswith(raw)
    assert not await (obsidian_vault / ObsidianService.IDEA_INBOX_PATH).exists()
    assert {capture.id for capture in await _load_recent_captures()} == {
        first.id,
        second.id,
    }


async def test__legacy_groups_are_retrievable_and_searchable_with_individual_ideas(
    obsidian_vault: AsyncPath,
) -> None:
    """Date/minute identities retain their grouped text and explicit legacy classification."""
    path = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    await path.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "# 2020-01-01\n\n## 09:15\n\nMQTT rain idea\n\nAnother idea\n\n↗ [[Task]]\n"
    )
    _ = await path.write_text(original)
    new = await IdeaService.record("Another MQTT idea")

    legacy = await IdeaService.get_idea("2020-01-01T09:15")
    assert legacy.kind == "legacy_group"
    assert legacy.text == "MQTT rain idea\n\nAnother idea"
    assert new.kind == "idea"
    assert await IdeaService.list_ideas(limit=1) == [new]
    assert await IdeaService.list_ideas(limit=1, offset=1) == [legacy]
    assert await IdeaService.list_ideas(offset=2) == []
    hits = await VaultSearchService.search_note_contents("MQTT", kinds=["idea"])
    assert {hit.path for hit in hits} == {legacy.path, new.path}
    assert await path.read_text() == original


async def test__new_capture_links_keep_original_note_immutable(
    obsidian_vault: AsyncPath,
) -> None:
    """Task provenance uses the stable ID and a native link back to the original note."""
    capture = await IdeaService.record("  Original idea\n\n# Heading\n\n")
    raw = await (obsidian_vault / capture.path).read_text()
    task = obsidian_vault / VAULT_PATHS.task_notes_dir / "my-task.md"
    await task.parent.mkdir(parents=True, exist_ok=True)
    _ = await task.write_text("---\ntype: task\n---\n# My task\n")

    _ = await TaskService.link_capture("my-task", capture.id)

    task_text = await task.read_text()
    assert f"source_capture: {capture.id}" in task_text
    assert f"[[Inbox/Ideas/{capture.id}|{capture.id}]]" in task_text
    assert await (obsidian_vault / capture.path).read_text() == raw
    assert await IdeaService.get_idea(capture.id) == capture

    legacy = obsidian_vault / ObsidianService.IDEA_INBOX_PATH
    _ = await legacy.write_text("# 2020-01-01\n\n## 09:15\n\nOlder idea\n")
    _ = await TaskService.link_capture("my-task", "2020-01-01T09:15")
    task_text = await task.read_text()
    assert "source_capture: 2020-01-01T09:15" in task_text
    assert "source_capture_link:\n" in task_text
    assert f"[[Inbox/Ideas/{capture.id}" not in task_text


async def test__retrieval_adapters_share_stable_ids(obsidian_vault: AsyncPath) -> None:
    """REST and MCP adapters expose the same captures and IDs returned from recording."""
    _ = obsidian_vault
    response = await create_idea(IdeaRequest(idea="Rain alerts"))
    mcp_message = await obsidian.record_idea(idea="Wind alerts")
    captures = await list_ideas(limit=100)

    assert len(captures) == 2
    assert response.message == "Idea recorded successfully."
    assert await get_idea(response.id) == await obsidian.get_idea(response.id)
    assert await obsidian.list_ideas(limit=100) == captures
    assert mcp_message.startswith("Idea recorded successfully. ID: idea-")
    assert any(capture.id in mcp_message for capture in captures)


async def test__missing_inbox_reads_are_empty_and_invalid_requests_are_explicit(
    obsidian_vault: AsyncPath,
) -> None:
    """Read-only retrieval creates nothing and validates bounds and missing IDs."""
    assert await IdeaService.list_ideas() == []
    assert not await (obsidian_vault / IDEA_NOTES_DIR).exists()
    with pytest.raises(exc.NotFoundError, match="not found"):
        _ = await IdeaService.get_idea("missing")
    for limit, offset in [(0, 0), (101, 0), (1, -1)]:
        with pytest.raises(exc.UserError, match="limit 1-100"):
            _ = await IdeaService.list_ideas(limit=limit, offset=offset)


async def test__capture_lookback_and_edited_metadata(obsidian_vault: AsyncPath) -> None:
    """Old individual captures support exact lookup and extra metadata does not hide them."""
    capture = await IdeaService.record("Original text\n")
    path = obsidian_vault / capture.path
    raw = await path.read_text()
    created = dt.datetime.combine(
        today() - dt.timedelta(days=40),
        dt.time(),
        tzinfo=dt.UTC,
    )
    header, _, text = raw.partition("\n---\n")
    header = "\n".join([
        *header.splitlines()[:2],
        f"created: {created.isoformat()}",
        "tags: [idea]",
    ])
    _ = await path.write_text(header + "\n---\n" + text)

    assert await IdeaService.load_captures(days=30) == []
    assert (await IdeaService.get_idea(capture.id)).text == capture.text
    _ = await path.write_text(raw.replace("created: ", "created: invalid-"))
    with pytest.raises(exc.UserError, match="timestamp"):
        _ = await IdeaService.list_ideas()
    _ = await path.write_text(raw.replace(f"id: {capture.id}", "id: wrong"))
    with pytest.raises(exc.UserError, match="metadata"):
        _ = await IdeaService.list_ideas()


async def test__new_task_links_to_original_idea(obsidian_vault: AsyncPath) -> None:
    """A created task has a native source link so Obsidian can show backlinks."""
    _ = obsidian_vault
    idea = await IdeaService.record("Original idea")
    capture = (await IdeaService.load_captures())[0]
    note = _build_task_note(
        title="My task",
        now=dt.datetime.now(tz=dt.UTC),
        metadata=TaskMetadata(
            title="My task",
            domains=[],
            resources=[],
            projects=[],
            people=[],
        ),
        capture=capture,
        description="Expanded task",
        due=None,
    )

    assert f"source_capture: {idea.id}" in note
    assert f"source_capture_link: '[[Inbox/Ideas/{idea.id}|{idea.id}]]'" in note


async def test__idea_retries_preserve_one_identity_and_reject_changed_text(
    obsidian_vault: AsyncPath,
) -> None:
    """Concurrent retries use the same immutable note; a new key is a separate capture."""
    _ = obsidian_vault
    captures = await asyncio.gather(
        *(
            IdeaService.record("Maybe build this\n", idempotency_key="idea-request-1")
            for _ in range(3)
        ),
    )
    assert captures == [captures[0]] * 3
    assert await IdeaService.list_ideas() == [captures[0]]
    with pytest.raises(exc.ConflictError):
        await IdeaService.record("Changed idea", idempotency_key="idea-request-1")
    second = await IdeaService.record(
        "Maybe build this\n",
        idempotency_key="idea-request-2",
    )
    assert second.id != captures[0].id


@pytest.mark.parametrize(("idea", "key"), [(" ", "valid"), ("An idea", " ")])
async def test__idea_rejects_empty_capture_or_key(
    obsidian_vault: AsyncPath,
    idea: str,
    key: str,
) -> None:
    """Invalid requests never create an idea note."""
    _ = obsidian_vault
    with pytest.raises(exc.BadRequestError):
        await IdeaService.record(idea, idempotency_key=key)
    assert await IdeaService.list_ideas() == []
