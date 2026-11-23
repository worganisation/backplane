"""Read structured tasks by their durable frontmatter identity."""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Annotated, Final

from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from ruamel.yaml.error import YAMLError

from backplane.utils import VAULT_PATHS, YAML_LOADER, AsyncPath, exc, resolve_under_root
from backplane.utils.markdown import note_title_from_markdown

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_TASK_PAGE_SIZE: Final = 100

_FRONTMATTER: Final = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)


class TaskRecord(BaseModel, frozen=True):
    """Exact task identity, current metadata and original Markdown body."""

    id: Annotated[str, Field(min_length=1)]
    title: str
    path: AsyncPath
    status: str = "backlog"
    projects: list[str] = Field(default_factory=list)
    due: str | None = None
    source_capture: str | None = None
    completed: str | None = None
    updated: str | None = None
    body: str


async def read_task(path: AsyncPath) -> TaskRecord | None:
    """Read a task without rewriting its Markdown or interpreting its content.

    Returns:
        The structured task, or None for a note without task frontmatter.

    Raises:
        UserError: A task has invalid metadata.
    """
    resolved = await resolve_under_root(path)
    async with await resolved.open(encoding="utf-8", newline="") as note:
        raw = await note.read()
    if (header := _FRONTMATTER.match(raw)) is None:
        return None

    try:
        loaded: object = YAML_LOADER.load(header[1]) or {}  # pyright: ignore[reportUnknownMemberType]
        values = TypeAdapter(dict[str, object]).validate_python(loaded)
    except (ValidationError, YAMLError) as error:
        raise exc.UserError(message=f"Invalid task metadata in {path}.") from error

    metadata = {
        key: value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value
        for key, value in values.items()
    }
    if metadata.get("type") != "task":
        return None

    try:
        return TaskRecord.model_validate(
            metadata
            | {
                "title": note_title_from_markdown(raw) or path.stem,
                "path": path,
                "body": raw[header.end() :],
            },
        )
    except ValidationError as error:
        raise exc.UserError(message=f"Invalid task metadata in {path}.") from error


async def _all_tasks() -> list[TaskRecord]:
    """Read task notes with unambiguous IDs in deterministic order.

    Returns:
        Tasks sorted by case-insensitive title and stable ID.

    Raises:
        ConflictError: Multiple notes claim the same task identity.
    """
    directory = await resolve_under_root(VAULT_PATHS.task_notes_dir)
    if not await directory.is_dir():
        return []

    records: dict[str, TaskRecord] = {}
    async for path in directory.rglob("*.md"):
        relative = VAULT_PATHS.task_notes_dir / path.relative_to(directory)
        if (task := await read_task(relative)) is None:
            continue

        if task.id in records:
            raise exc.ConflictError(message=f"Duplicate task identity: {task.id}.")
        records[task.id] = task

    return sorted(records.values(), key=lambda task: (task.title.casefold(), task.id))


def _matches_project(projects: Sequence[str], requested: str) -> bool:
    """Match an exact project display name or wiki-link target, ignoring case.

    Returns:
        Whether a stored project link matches the requested name.
    """
    for project in projects:
        target, _, alias = project.removeprefix("[[").removesuffix("]]").partition("|")
        names = (project, target, target.rsplit("/", maxsplit=1)[-1], alias)
        if requested.casefold() in (name.casefold() for name in names if name):
            return True

    return False


async def list_tasks(
    *,
    project: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[TaskRecord]:
    """Browse tasks with exact filters; an empty project filter means unassigned.

    Returns:
        A bounded page, ordered by title and stable ID.

    Raises:
        BadRequestError: Pagination exceeds the supported bounds.
    """
    if not 1 <= limit <= MAX_TASK_PAGE_SIZE or offset < 0:
        raise exc.BadRequestError(message="Use limit 1-100 and a nonnegative offset.")

    tasks = [
        task
        for task in await _all_tasks()
        if (status is None or task.status == status)
        and (
            project is None
            or (
                not task.projects
                if not project
                else _matches_project(task.projects, project)
            )
        )
    ]
    return tasks[offset : offset + limit]


async def get_task(task_id: str) -> TaskRecord:
    """Retrieve exactly one durable task ID, including after a note rename.

    Returns:
        The identified task with its original Markdown body.

    Raises:
        NotFoundError: No task has that identity.
    """
    for task in await _all_tasks():
        if task.id == task_id:
            return task

    raise exc.NotFoundError(message=f"Task {task_id!r} not found.")
