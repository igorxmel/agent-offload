"""Separate working copies for delegations, so several can run at once.

Each writing delegation takes a free slot - a git worktree under
`.offload/state/worktrees/slot-N` - checks its scratch branch out there, and lets
the executor work and the check run inside it. The person's own tree is never
checked out, reset or cleaned, and two delegations never share files.

Slots are kept between runs on purpose: a fresh worktree would rebuild every
project from nothing, while a kept one keeps its ignored build outputs (`target/`,
`.gradle/`, `build/`) warm. Only tracked and untracked files are reset between
uses; ignored ones survive.

A slot is taken with a lock file created exclusively. A lock older than
`stale_after` seconds belongs to a run that died and is taken over.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from offload import gitops, paths

MAX_SLOTS = 8


class NoFreeSlot(Exception):
    """Every slot is busy."""


@dataclass
class Slot:
    number: int
    path: Path
    lock: Path


def _dir(root: Path) -> Path:
    return paths.state_dir(root) / "worktrees"


def _take(lock: Path, stale_after: float) -> bool:
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return False
        if age < stale_after:
            return False
        lock.unlink(missing_ok=True)  # a dead run's lock
        return _take(lock, float("inf"))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {time.time():.0f}\n")
    return True


def _prepare(root: Path, path: Path, base: str, branch: str | None, copy: list[str]) -> None:
    if path.exists() and not (path / ".git").exists():
        shutil.rmtree(path)  # a leftover that is no longer a worktree; ours to remove
    if not path.exists():
        gitops.git(root, "worktree", "prune")
        gitops.git(root, "worktree", "add", "-q", "--detach", str(path), base)
    # -f and clean throw away whatever an earlier run left; ignored files stay warm.
    if branch:
        gitops.git(path, "checkout", "-q", "-f", "-B", branch, base)
    else:
        gitops.git(path, "checkout", "-q", "-f", "--detach", base)  # read-only: no branch
    gitops.git(path, "clean", "-fdq")
    for rel in copy:
        # Machine-local files the project needs but git ignores (an SDK path, say).
        source = root / rel
        if source.is_file():
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def acquire(
    root: Path, base: str, branch: str | None, stale_after: float,
    copy: list[str] | None = None,
) -> Slot:
    """A free slot with `branch` created at `base`, or `base` detached when `branch`
    is None (a read-only look at existing work)."""
    folder = _dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    for number in range(1, MAX_SLOTS + 1):
        lock = folder / f"slot-{number}.lock"
        if not _take(lock, stale_after):
            continue
        path = folder / f"slot-{number}"
        try:
            _prepare(root, path, base, branch, copy or [])
        except BaseException:
            lock.unlink(missing_ok=True)
            raise
        return Slot(number, path, lock)
    raise NoFreeSlot(f"all {MAX_SLOTS} delegation slots are busy")


def release(root: Path, slot: Slot, branch: str | None, keep_branch: bool) -> None:
    """Frees the slot. The branch stays in the repository unless it is discarded."""
    try:
        gitops.git(slot.path, "checkout", "-q", "--detach", check=False)
        if branch and not keep_branch:
            gitops.delete_branch(root, branch)
    finally:
        slot.lock.unlink(missing_ok=True)
