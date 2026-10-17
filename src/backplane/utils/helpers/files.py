"""Async file I/O and path resolution helpers."""

from __future__ import annotations

import asyncio
import fcntl
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from anyio import NamedTemporaryFile

from backplane.utils.async_path import AsyncPath
from backplane.utils.settings import SETTINGS

if TYPE_CHECKING:
    import pathlib
    from collections.abc import AsyncGenerator


_VAULT_LOCK_OWNER: ContextVar[asyncio.Task[object] | None] = ContextVar(
    "vault_write_lock_owner",
    default=None,
)


@asynccontextmanager
async def vault_write_lock() -> AsyncGenerator[None]:
    """Serialize cooperating vault writers across tasks and server processes.

    Nested edits in the owning task share the lock. Child tasks must acquire their
    own lock and must not be awaited while their parent holds it. The persistent
    lock file must not be removed or replaced while servers are running. Obsidian
    and Sync do not participate, so callers still need external-change detection.

    Yields:
        Control while the current task owns the vault write lock.
    """
    task = asyncio.current_task()
    if task is not None and _VAULT_LOCK_OWNER.get() is task:
        yield
        return

    await SETTINGS.obsidian_vault_path.mkdir(parents=True, exist_ok=True)
    lock_path = SETTINGS.obsidian_vault_path / ".backplane-write.lock"
    async with await lock_path.open("a+b") as lock_file:
        descriptor = lock_file.wrapped.fileno()
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.01)

            token = _VAULT_LOCK_OWNER.set(task)
            try:
                yield
            finally:
                _VAULT_LOCK_OWNER.reset(token)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)


async def atomic_write_text(path: AsyncPath, content: str) -> None:
    """Write text atomically using a temporary file on the destination filesystem."""
    await path.parent.mkdir(parents=True, exist_ok=True)
    async with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix="backplane-",
        suffix=".tmp",
    ) as tmp_file:
        _ = await tmp_file.write(content)

        await tmp_file.flush()
        _ = await AsyncPath(tmp_file.wrapped.name).replace(path)


async def resolve_under_root(
    relative: AsyncPath | pathlib.PurePath | str,
) -> AsyncPath:
    """Resolve a path relative to the Obsidian vault and ensure it stays inside.

    Args:
        relative: Path relative to the configured vault root.

    Returns:
        Resolved absolute path under the vault.

    Raises:
        ValueError: If ``relative`` is absolute, contains ``..``, or escapes the vault.
    """
    path = relative if isinstance(relative, AsyncPath) else AsyncPath(relative)
    if path.is_absolute() or ".." in path.parts:
        msg = f"Unsafe path: {path!s}"
        raise ValueError(msg)

    root_resolved = await SETTINGS.obsidian_vault_path.resolve()
    resolved = AsyncPath((await (root_resolved / path).resolve()).as_posix())

    try:
        _ = resolved.relative_to(root_resolved)
    except ValueError as exc:
        msg = f"Path escapes root: {path!s}"
        raise ValueError(msg) from exc

    return resolved
