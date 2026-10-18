"""Explicit task state changes with recoverable Kanban projection."""

from __future__ import annotations

import datetime as dt
import io
import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backplane.services.task_catalog import TaskRecord, get_task
from backplane.services.vault_entities import VaultEntityService
from backplane.utils import (
    SETTINGS,
    VAULT_PATHS,
    YAML_LOADER,
    atomic_write_text,
    build_obsidian_link,
    enums,
    exc,
    resolve_under_root,
)
from backplane.utils.helpers.files import vault_write_lock

TaskStatus = Literal["backlog", "doing", "done"]


class TaskUpdate(BaseModel, frozen=True):
    """Explicit desired state; no unspecified field is changed."""

    status: TaskStatus | None = None
    project: Annotated[str | None, Field(min_length=1)] = None
    clear_project: bool = False


class TaskUpdateResult(BaseModel, frozen=True):
    """Persisted task state and warnings for its secondary board projection."""

    task: TaskRecord
    warnings: list[str] = Field(default_factory=list)


def reconcile_task_card(board: str, task: TaskRecord) -> str:
    """Place exactly one existing card in the desired section, preserving its metadata.

    Returns:
        Updated board text with unrelated cards and settings retained.
    """
    target = str(task.path).removesuffix(".md")
    link = re.compile(r"\[\[" + re.escape(target) + r"(?:\.md)?(?:\|[^\]]*)?\]\]")
    section = {"backlog": "Backlog", "doing": "Doing", "done": "Done"}[task.status]
    lines = board.splitlines(keepends=True)
    current_section = ""
    matching_sections: list[str] = []
    card: str | None = None
    retained: list[str] = []
    for line in lines:
        if line.startswith("## "):
            current_section = line[3:].strip()
        if re.match(r"^- \[[ xX]\] ", line) and link.search(line):
            matching_sections.append(current_section)
            if card is None:
                card = line.rstrip("\r\n")
            continue

        retained.append(line)

    if matching_sections == [section] and card is not None:
        checked = card.startswith(("- [x]", "- [X]"))
        if checked == (task.status == "done"):
            return board

    card = card or f"- [ ] {build_obsidian_link(task.path)}"
    card = re.sub(r"^- \[[ xX]\]", "- [x]" if task.status == "done" else "- [ ]", card)
    text = "".join(retained)
    heading = re.search(r"^## " + section + r"[ \t]*$", text, re.MULTILINE)
    if heading is not None:
        return text[: heading.end()] + "\n\n" + card + text[heading.end() :]

    body, separator, settings = text.partition("\n%% kanban:settings")
    return body.rstrip() + f"\n\n## {section}\n\n{card}\n" + separator + settings


async def _project_links(change: TaskUpdate) -> list[str] | None:
    """Resolve an explicitly selected existing project.

    Returns:
        New project links, or None when assignment is unchanged.

    Raises:
        BadRequestError: Assignment and removal conflict or the name is blank.
        NotFoundError: The requested project does not exist.
    """
    if change.clear_project and change.project is not None:
        raise exc.BadRequestError(message="Choose a project or clear it, not both.")
    if change.clear_project:
        return []
    if change.project is None:
        return None
    if not (name := change.project.strip()):
        raise exc.BadRequestError(message="Project must not be blank.")

    path = await VaultEntityService.resolve_entity_path(
        enums.VaultEntityKind.PROJECT,
        name,
    )
    if path is None:
        raise exc.NotFoundError(
            message=f"Project {name!r} not found; create it explicitly first.",
        )

    return [build_obsidian_link(VAULT_PATHS.projects_dir / path.name, alias=name)]


async def _persist_change(task: TaskRecord, change: TaskUpdate) -> TaskRecord:
    """Update frontmatter while preserving the Markdown body byte for byte.

    Returns:
        The persisted current task.

    Raises:
        ConflictError: An external writer changed the note during the operation.
    """
    path = await resolve_under_root(task.path)
    async with await path.open(encoding="utf-8", newline="") as note:
        original = await note.read()

    header, separator, body = original.partition("\n---\n")
    if not separator:
        header, separator, body = original.partition("\r\n---\r\n")
    if not separator:
        raise exc.ConflictError(message="Task frontmatter changed; read the task again.")

    yaml_text = header.removeprefix("---").lstrip("\r\n")
    metadata: dict[str, object] = YAML_LOADER.load(yaml_text) or {}  # pyright: ignore[reportUnknownMemberType]
    if metadata.get("id") != task.id:
        raise exc.ConflictError(message="Task identity changed; read the task again.")

    changed = False
    if change.status is not None and metadata.get("status") != change.status:
        metadata["status"] = change.status
        metadata["completed"] = (
            dt.datetime.now(SETTINGS.local_timezone).isoformat()
            if change.status == "done"
            else None
        )
        changed = True

    projects = await _project_links(change)
    if projects is not None and metadata.get("projects") != projects:
        metadata["projects"] = projects
        changed = True

    if changed:
        metadata["updated"] = dt.datetime.now(SETTINGS.local_timezone).isoformat()
        buffer = io.StringIO()
        YAML_LOADER.dump(metadata, buffer)  # pyright: ignore[reportUnknownMemberType]
        async with await path.open(encoding="utf-8", newline="") as note:
            if await note.read() != original:
                raise exc.ConflictError(message="Task changed externally; read it again.")

        await atomic_write_text(path, buffer.getvalue() + "---\n" + body)

    return await get_task(task.id)


async def update_task(task_id: str, change: TaskUpdate) -> TaskUpdateResult:
    """Apply explicit task fields and repair its board card on identical retries.

    Returns:
        Saved task state; board failures are actionable warnings, not failed saves.
    """
    async with vault_write_lock():
        task = await _persist_change(await get_task(task_id), change)
        warnings: list[str] = []
        if task.status in {"backlog", "doing", "done"}:
            try:
                await reconcile_task_board(task)
            except (OSError, exc.ConflictError) as error:
                warnings.append(
                    f"Task saved; board update failed. Retry the same update to repair it: {error}",
                )

        return TaskUpdateResult(task=task, warnings=warnings)


async def reconcile_task_board(task: TaskRecord) -> None:
    """Write the secondary board atomically, rejecting observed external edits.

    Raises:
        ConflictError: An external writer changed the board during the operation.
    """
    path = await resolve_under_root(VAULT_PATHS.task_board_path)
    original = await path.read_text(encoding="utf-8")
    updated = reconcile_task_card(original, task)
    if updated == original:
        return
    if await path.read_text(encoding="utf-8") != original:
        raise exc.ConflictError(message="Board changed externally.")

    await atomic_write_text(path, updated)
