"""`offload delegate`: hand one task to an executor and return a short verdict.

What the orchestrator gets back is a verdict, not code: which model did it, what
changed, and what the check command **actually printed**. The executor's own
report is shown but never trusted.

The flow, and why:

1. Preconditions fail loudly *before* anything runs: a dirty tree would make the
   diff unattributable, and no check command means a junk generator.
2. Work happens on a scratch branch `offload/...`. The person's tree is never
   touched, and the original branch is checked out again at the end.
3. Infrastructure failures (timeout, provider error, empty answer) retry on the
   next acceptable model. A failed *check* does not: that is a quality verdict,
   and it goes to the orchestrator.
4. The kit runs the check itself, and verifies the executor did not touch its
   own cage (`.offload/`, `.opencode/`). Tampering discards everything.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from offload import checks, config, discover, gitops, history, opencode, paths, report, select

# Exit codes. 0 passed; 3 the check failed or nothing changed; 4 every executor
# attempt failed; 5 the executor touched its own limits. 1 and 2 live in the CLI.
EXIT = {"passed": 0, "failed": 3, "no_changes": 3, "executor_error": 4, "tampered": 5}

MESSAGE = "Carry out the task described in the attached file."

# Paths the executor must never change; checked again after the run.
PROTECTED_PREFIXES = (".offload/", ".opencode/")
PROTECTED_FILES = ("opencode.json", "opencode.jsonc", "AGENTS.md", "CLAUDE.md")
IGNORED_PREFIXES = (".offload/state/",)
READ_ONLY = ("explore", "plan", "review")


class DelegateError(Exception):
    """A precondition failed. Nothing was run."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class Attempt:
    model: str
    outcome: str  # ok | timeout | error | empty
    seconds: float
    detail: str = ""


@dataclass
class Verdict:
    status: str
    role: str
    model: str = ""
    branch: str = ""
    base: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    diffstat: str = ""
    verify: dict | None = None
    holdout: dict | None = None
    report: dict = field(default_factory=dict)
    report_ok: bool = False
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def exit_code(self) -> int:
        return EXIT[self.status]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "model": self.model,
            "role": self.role,
            "branch": self.branch,
            "base": self.base,
            "files": self.files,
            "diffstat": self.diffstat,
            "verify": self.verify,
            "holdout": self.holdout,
            "report": self.report,
            "report_well_formed": self.report_ok,
            "attempts": [vars(a) for a in self.attempts],
            "notes": self.notes,
            "seconds": round(self.seconds, 1),
        }


def _slug(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (words[:30].strip("-") or "task")


def _relevant(paths_: list[str]) -> list[str]:
    return [p for p in paths_ if not p.startswith(IGNORED_PREFIXES)]


def _in_scope(path: str, scope: list[str]) -> bool:
    """True when `path` is one of the scope entries or lives under one of them."""
    path = path.replace("\\", "/")
    for entry in scope:
        entry = entry.replace("\\", "/").strip("/")
        if path == entry or path.startswith(entry + "/"):
            return True
    return False


def _tampered(files: list[str]) -> list[str]:
    return [f for f in files if f.startswith(PROTECTED_PREFIXES) or f in PROTECTED_FILES]


def _preflight(root: Path, cfg: config.Config, verify_cmd: str | None, role: str) -> str:
    if role not in {"explore", "plan", "build", "review"}:
        raise DelegateError(f"unknown role '{role}'")
    if not gitops.is_repo(root):
        raise DelegateError("not a git repository: delegation needs a scratch branch")
    verify = verify_cmd or cfg.verify
    if role in READ_ONLY:
        # Read-only roles change nothing, so there is nothing to branch or verify.
        return verify
    if not verify:
        raise DelegateError(
            "no check command: set verify in .offload/config.json or pass --verify. "
            "Without a machine check the result cannot be trusted."
        )
    dirty = _relevant(gitops.changed_paths(root))
    if dirty:
        shown = ", ".join(dirty[:5]) + (" ..." if len(dirty) > 5 else "")
        raise DelegateError(
            f"working tree has uncommitted changes ({shown}). Commit or stash them: "
            "otherwise the executor's diff cannot be told apart from yours."
        )
    return verify


def _candidates(root, snapshot, role: str, model: str | None, attempts: int) -> list[str]:
    ranked = [c.model for c in select.ranked(root, snapshot, role)]
    if not ranked:
        raise DelegateError("no acceptable model. See: offload models", code=2)
    if model:
        if model not in ranked:
            reason = next((e.reason for e in snapshot.entries if e.id == model), "unknown model")
            raise DelegateError(f"{model} is not acceptable under the project policy: {reason}", 2)
        ranked = [model] + [m for m in ranked if m != model]
    return ranked[:attempts]


def delegate(
    root: Path,
    task: str,
    role: str = "build",
    model: str | None = None,
    verify_cmd: str | None = None,
    max_attempts: int = 3,
    scope: list[str] | None = None,
    holdout_cmd: str | None = None,
    snapshot=None,
    executor=opencode.run_agent,
    now=time.time,
) -> Verdict:
    started = time.monotonic()
    cfg = config.load(root)
    verify = _preflight(root, cfg, verify_cmd, role)
    snapshot = snapshot or discover.discover(root)
    candidates = _candidates(root, snapshot, role, model, max_attempts)

    origin = gitops.current_ref(root)
    base = gitops.head(root)
    branch = f"offload/{_slug(task)}-{int(now())}"

    task_file = paths.state_dir(root) / "tasks" / f"{int(now())}.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(
        f"{task.strip()}\n\nCheck command (the orchestrator runs it itself; "
        f"do not skip it): {verify}\n"
        "Work only inside this project. Install nothing: if a dependency is missing, "
        "put it in BLOCKERS.\n",
        encoding="utf-8",
    )
    relative_task = task_file.relative_to(root).as_posix()

    writes = role not in READ_ONLY
    verdict = Verdict(
        status="executor_error", role=role, branch=branch if writes else "", base=base[:12]
    )
    if writes:
        gitops.create_branch(root, branch)
    keep_branch = False
    try:
        result = None
        for candidate in candidates:
            result = executor(
                root, f"offload-{role}", candidate, MESSAGE, Path(relative_task),
                cfg.executor_timeout,
            )
            outcome, detail = _classify(result)
            verdict.attempts.append(Attempt(candidate, outcome, round(result.seconds, 1), detail))
            if outcome == "ok":
                verdict.model = candidate
                break
            if writes:
                # A failed attempt must leave no trace. Only ever on our own scratch
                # branch: a hard reset on the person's branch would destroy their work.
                gitops.discard_changes(root, base)
        else:
            verdict.notes.append("every attempt failed before producing a usable answer")
            return verdict

        verdict.report = report.parse(result.stdout)
        verdict.report_ok = report.is_well_formed(verdict.report)
        if not verdict.report_ok:
            verdict.notes.append("executor did not follow the report format")
            verdict.report = {"RAW": report.clip(report.strip_ansi(result.stdout), 800)}

        files = _relevant(gitops.changed_paths(root))
        verdict.files = files

        touched = _tampered(files)
        if touched:
            verdict.status = "tampered"
            verdict.files = files
            if writes:
                gitops.discard_changes(root, base)
                verdict.files = []
                verdict.notes.append(f"executor changed its own limits, work discarded: {touched}")
            else:
                verdict.notes.append(f"executor changed its own limits: {touched}. NOT discarded "
                                     "(this is your branch): inspect with git status")
            return verdict

        if not writes:
            # Never reset here: this is the person's own branch. Report and stop.
            verdict.status = "failed" if files else "passed"
            if files:
                verdict.notes.append(
                    f"a read-only role changed files: {files}. Left as is - inspect git status"
                )
            return verdict

        limit = scope if scope is not None else cfg.scope
        if limit:
            # After the tamper check on purpose: the kit's own files are outside any
            # scope, and discarding them here would hide an attempt to edit them.
            stray = [f for f in files if not _in_scope(f, limit)]
            if stray:
                gitops.discard_paths(root, stray)
                files = [f for f in files if f not in stray]
                verdict.files = files
                shown = ", ".join(stray[:6]) + (" ..." if len(stray) > 6 else "")
                verdict.notes.append(f"out of scope, discarded ({len(stray)}): {shown}")

        if not files:
            verdict.status = "no_changes"
            return verdict

        gitops.commit_all(root, f"offload({role}): {task.strip().splitlines()[0][:60]}")
        keep_branch = True
        verdict.diffstat = gitops.shortstat(root, base, "HEAD")

        outcome = checks.run(root, verify, cfg.verify_timeout)
        verdict.verify = outcome.to_dict()
        verdict.status = "passed" if outcome.passed else "failed"

        if holdout_cmd and outcome.passed:
            # Never written to the task file or to disk: the executor must not be able
            # to read it. Run only on a green check; a red one already decides the verdict.
            held = checks.run(root, holdout_cmd, cfg.verify_timeout)
            verdict.holdout = held.to_dict()
            if not held.passed:
                verdict.status = "failed"
                verdict.notes.append(
                    "check passed but the held-out check failed: the code may be fitted to "
                    "the visible check. Do not show the held-out output to the executor"
                )
        return verdict
    finally:
        if writes:
            gitops.checkout(root, origin)
            if not keep_branch:
                gitops.delete_branch(root, branch)
                verdict.branch = ""
        verdict.seconds = time.monotonic() - started
        _record(root, verdict, role)


def _classify(result) -> tuple[str, str]:
    """Infrastructure outcome of one executor run, separate from result quality."""
    if result.timed_out:
        return "timeout", f"killed after {result.seconds:.0f}s"
    if result.returncode != 0:
        detail = report.strip_ansi(result.stderr or result.stdout).strip().splitlines()
        return "error", (detail[-1][:200] if detail else f"exit {result.returncode}")
    if not result.stdout.strip():
        return "empty", "no output"
    return "ok", ""


def _record(root: Path, verdict: Verdict, role: str) -> None:
    """Writes what happened per model: the data future choices are built from."""
    for attempt in verdict.attempts:
        if attempt.outcome != "ok":
            history.record(root, attempt.model, role, False, attempt.seconds,
                           outcome=attempt.outcome)
    if verdict.model:
        history.record(
            root, verdict.model, role, verdict.status == "passed",
            verdict.seconds, outcome=verdict.status,
        )
