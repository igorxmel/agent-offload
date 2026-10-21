"""The few git operations delegation needs.

Delegation works on a scratch branch so that the person's working tree is never
touched: the executor's changes live on `offload/...`, and the original branch
is checked out again when the run ends. The orchestrator then inspects, merges
or discards the branch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def git(root: Path, *args: str, check: bool = True) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout


def is_repo(root: Path) -> bool:
    try:
        return git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except (GitError, OSError):
        return False


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD").strip()


def current_ref(root: Path) -> str:
    """The branch name, or the commit when HEAD is detached."""
    name = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return head(root) if name == "HEAD" else name


def changed_paths(root: Path) -> list[str]:
    """Paths with uncommitted changes, untracked files included, ignored ones not."""
    paths = []
    for line in git(root, "status", "--porcelain=v1", "-uall").splitlines():
        entry = line[3:]
        paths.append(entry.split(" -> ")[-1].strip('"'))
    return paths


def create_branch(root: Path, name: str) -> None:
    git(root, "checkout", "-q", "-b", name)


def checkout(root: Path, ref: str) -> None:
    git(root, "checkout", "-q", ref)


def discard_changes(root: Path, base: str) -> None:
    """Throws away everything since `base`. Only ever used on our own scratch branch."""
    git(root, "reset", "--hard", "-q", base)
    git(root, "clean", "-fdq")


def delete_branch(root: Path, name: str) -> None:
    git(root, "branch", "-D", name, check=False)


def commit_all(root: Path, message: str) -> bool:
    """Commits everything on the scratch branch. False when there was nothing."""
    git(root, "add", "-A")
    # The kit's own scratch state (task files, caches) never rides along. Unstaging
    # rather than excluding by pathspec: git refuses a pathspec that is already ignored.
    git(root, "reset", "-q", "--", ".offload/state", check=False)
    if subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--quiet"], check=False
    ).returncode == 0:
        return False
    # Hooks are skipped: this is a scratch branch, and a slow or failing hook of
    # the host project must not decide whether the executor's work is kept.
    git(
        root,
        "-c", "user.name=agent-offload",
        "-c", "user.email=agent-offload@localhost",
        "commit", "-q", "--no-verify", "-m", message,
    )
    return True


def shortstat(root: Path, base: str, ref: str) -> str:
    return git(root, "diff", "--shortstat", base, ref, check=False).strip()
