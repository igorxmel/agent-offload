"""`offload delegate`: hand one task to an executor and return a short verdict.

What the orchestrator gets back is a verdict, not code: which model did it, what
changed, and what the check command **actually printed**. The executor's own
report is shown but never trusted.

The flow, and why:

1. Preconditions fail loudly *before* anything runs: a dirty tree would make the
   diff unattributable, and no check command means a junk generator.
2. Work happens on a scratch branch `offload/...`, checked out in a separate
   working copy (see `slots`). The person's tree is never touched, and several
   delegations can run at once.
3. Infrastructure failures (timeout, stall, provider error, empty answer) retry
   on the next acceptable model. A failed *check* does not: that is a quality
   verdict, and it goes to the orchestrator. An exhausted quota skips the rest of
   that provider's models (see `quota`).
4. The kit runs the check itself, and verifies the executor did not touch its
   own cage (`.offload/`, `.opencode/`). Tampering discards everything.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from offload import (
    checks, config, discover, gitops, history, opencode, paths, quota, report, select, slots,
)

# Exit codes. 0 passed; 3 the check failed or nothing changed; 4 every executor
# attempt failed (`quota` when every one hit an exhausted quota); 5 the executor
# touched its own limits. 1 and 2 live in the CLI.
EXIT = {
    "passed": 0, "failed": 3, "no_changes": 3, "executor_error": 4, "quota": 4, "tampered": 5,
}

MESSAGE = "Carry out the task described in the attached file."

# Paths the executor must never change; checked again after the run.
PROTECTED_PREFIXES = (".offload/", ".opencode/")
PROTECTED_FILES = ("opencode.json", "opencode.jsonc", "AGENTS.md", "CLAUDE.md")
IGNORED_PREFIXES = (".offload/state/",)
READ_ONLY = ("explore", "plan", "review")
# Characters of a read-only role's answer kept in the verdict.
ANSWER_LIMIT = 6000


class DelegateError(Exception):
    """A precondition failed. Nothing was run."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class Attempt:
    model: str
    outcome: str  # ok | timeout | stall | quota | error | empty
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
    # What the executor spent across all attempts (`opencode.USAGE_FIELDS`), or
    # None when OpenCode's statistics could not be read.
    usage: dict | None = None

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
            "executor_usage": self.usage,
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


def _resume_tip(root: Path, resume: str | None, role: str) -> str | None:
    """Commit of an earlier `offload/...` branch to continue from, checked before any run."""
    if not resume:
        return None
    if role in READ_ONLY:
        raise DelegateError("--resume continues earlier work, so it needs a role that writes")
    if not resume.startswith("offload/"):
        raise DelegateError(f"--resume takes a branch made by the kit (offload/...), not '{resume}'")
    tip = gitops.branch_tip(root, resume)
    if not tip:
        raise DelegateError(f"no such branch: {resume}")
    return tip


def _on_tip(root: Path, on: str | None, role: str) -> str | None:
    """Commit of an existing branch for a read-only role to look at."""
    if not on:
        return None
    if role not in READ_ONLY:
        raise DelegateError("--on is for read-only roles; to change a branch use --resume")
    tip = gitops.branch_tip(root, on)
    if not tip:
        raise DelegateError(f"no such branch: {on}")
    return tip


def _candidates(root, snapshot, role: str, model: str | None, skip: set[str]) -> list[str]:
    """Every model that may be tried, best first, without providers whose quota is
    exhausted. The attempt limit is applied while trying, not here: a quota stop
    met on the way removes a whole provider, and the next candidates must come
    from the others.

    A model the person named explicitly is tried even then: they asked for it.
    """
    ranked = [c.model for c in select.ranked(root, snapshot, role)]
    if not ranked:
        raise DelegateError("no acceptable model. See: offload models", code=2)
    if model:
        if model not in ranked:
            reason = next((e.reason for e in snapshot.entries if e.id == model), "unknown model")
            raise DelegateError(f"{model} is not acceptable under the project policy: {reason}", 2)
        rest = [m for m in ranked if m != model and quota.provider(m) not in skip]
        return [model] + rest
    usable = [m for m in ranked if quota.provider(m) not in skip]
    if not usable:
        raise DelegateError(
            "every acceptable model's provider reported an exhausted quota recently "
            f"({', '.join(sorted(skip))}); try later or connect another provider",
            code=4,
        )
    return usable


def delegate(
    root: Path,
    task: str,
    role: str = "build",
    model: str | None = None,
    verify_cmd: str | None = None,
    max_attempts: int = 3,
    scope: list[str] | None = None,
    holdout_cmd: str | None = None,
    resume: str | None = None,
    on: str | None = None,
    snapshot=None,
    executor=opencode.run_agent,
    now=time.time,
    usage_reader=None,
) -> Verdict:
    started = time.monotonic()
    cfg = config.load(root)
    verify = _preflight(root, cfg, verify_cmd, role)
    resume_tip = _resume_tip(root, resume, role)
    on_tip = _on_tip(root, on, role)
    fresh = snapshot is None
    snapshot = snapshot or discover.discover(root)
    if model and fresh and model not in {e.id for e in snapshot.entries}:
        # A provider connected after the last discovery: look again before refusing.
        snapshot = discover.discover(root, refresh=True)
    skip = quota.exhausted(root, cfg.quota_cooldown_hours)
    candidates = _candidates(root, snapshot, role, model, skip)

    base = resume_tip or gitops.head(root)
    stamp = f"{int(now())}-{uuid.uuid4().hex[:6]}"  # unique even for two runs in one second
    branch = f"offload/{_slug(task)}-{stamp}"
    writes = role not in READ_ONLY

    review_range = ""
    if on_tip:
        # A read-only look at existing work: a slot detached at that branch's tip.
        review_range = f"{gitops.merge_base(root, gitops.head(root), on_tip)[:12]}..HEAD"
        base = on_tip
    slot = None
    if writes or on_tip:
        try:
            slot = slots.acquire(
                root, base, branch if writes else None,
                stale_after=cfg.executor_timeout * max_attempts + 2 * cfg.verify_timeout + 600,
                copy=cfg.worktree_copy,
            )
        except slots.NoFreeSlot as error:
            raise DelegateError(f"{error}; wait for a running delegation to finish", 4) from error
    # Where the executor works and the check runs. Kit state (history, quota,
    # caches) stays in `root`.
    work = slot.path if slot else root

    verdict = Verdict(
        status="executor_error", role=role, branch=branch if writes else "", base=base[:12]
    )
    keep_branch = False
    usage_reader = usage_reader or opencode.usage
    usage_before = None
    try:
        # Inside `try`: whatever fails from here on, the slot is released.
        usage_before = usage_reader(root)
        task_file = paths.state_dir(work) / "tasks" / f"{stamp}.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)
        intro = (
            "The work from an earlier attempt is already in this project. Do not redo it: fix "
            "only the discrepancies listed below, then stop.\n\n" if resume_tip else ""
        )
        if review_range:
            intro = (
                f"The changes to look at are `git diff {review_range}` in this project "
                "(read the full files where the diff is not enough).\n\n"
            )
        task_file.write_text(
            f"{intro}{task.strip()}\n\nCheck command (the orchestrator runs it itself; "
            f"do not skip it): {verify}\n"
            "Work only inside this project. Install nothing: if a dependency is missing, "
            "put it in BLOCKERS.\n",
            encoding="utf-8",
        )
        relative_task = task_file.relative_to(work).as_posix()

        result = None
        # Quota stops do not count: they take seconds and say nothing about the model.
        spent = 0
        for candidate in candidates:
            if spent >= max_attempts:
                continue  # not `break`: the `else` below must still run
            if quota.provider(candidate) in skip and candidate != model:
                continue  # an earlier attempt in this run exhausted this provider
            result = executor(
                work, f"offload-{role}", candidate, MESSAGE, Path(relative_task),
                cfg.executor_timeout, cfg.stall_timeout,
            )
            outcome, detail = _classify(result)
            verdict.attempts.append(Attempt(candidate, outcome, round(result.seconds, 1), detail))
            if outcome == "ok":
                verdict.model = candidate
                break
            if outcome == "quota":
                quota.mark(root, candidate)
                skip.add(quota.provider(candidate))
            else:
                spent += 1
            if writes:
                # A failed attempt must leave no trace. Only ever in our own slot:
                # a hard reset in the person's tree would destroy their work.
                gitops.discard_changes(work, base)
        else:
            if verdict.attempts and all(a.outcome == "quota" for a in verdict.attempts):
                verdict.status = "quota"
                verdict.notes.append(
                    "every attempt hit an exhausted quota; those providers are skipped for "
                    f"{cfg.quota_cooldown_hours:g} h. Try later or connect another provider"
                )
            else:
                verdict.notes.append("every attempt failed before producing a usable answer")
            return verdict

        verdict.report = report.parse(result.stdout)
        verdict.report_ok = report.is_well_formed(verdict.report)
        if not writes:
            # Read-only roles answer in their own shape (findings, a plan, a summary):
            # the answer is the result, so it is passed on whole, not as a report.
            verdict.report = {"ANSWER": report.clip(report.strip_ansi(result.stdout).strip(),
                                                     ANSWER_LIMIT)}
            verdict.report_ok = True
        elif not verdict.report_ok:
            verdict.notes.append("executor did not follow the report format")
            verdict.report = {"RAW": report.clip(report.strip_ansi(result.stdout), 800)}

        files = _relevant(gitops.changed_paths(work))
        verdict.files = files

        touched = _tampered(files)
        if touched:
            verdict.status = "tampered"
            verdict.files = files
            if writes:
                gitops.discard_changes(work, base)
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
                gitops.discard_paths(work, stray)
                files = [f for f in files if f not in stray]
                verdict.files = files
                shown = ", ".join(stray[:6]) + (" ..." if len(stray) > 6 else "")
                verdict.notes.append(f"out of scope, discarded ({len(stray)}): {shown}")

        big = _oversized(work, files, cfg.max_file_kb)
        if big:
            gitops.discard_paths(work, big)
            files = [f for f in files if f not in big]
            verdict.files = files
            verdict.notes.append(
                f"larger than {cfg.max_file_kb} KB, discarded ({len(big)}): {', '.join(big[:6])}"
            )

        if not files:
            verdict.status = "no_changes"
            return verdict

        gitops.commit_all(work, f"offload({role}): {task.strip().splitlines()[0][:60]}")
        keep_branch = True
        verdict.diffstat = gitops.shortstat(work, base, "HEAD")

        outcome = checks.run(work, verify, cfg.verify_timeout)
        verdict.verify = outcome.to_dict()
        verdict.status = "passed" if outcome.passed else "failed"

        if holdout_cmd and outcome.passed:
            # Never written to the task file or to disk: the executor must not be able
            # to read it. Run only on a green check; a red one already decides the verdict.
            held = checks.run(work, holdout_cmd, cfg.verify_timeout)
            verdict.holdout = held.to_dict()
            if not held.passed:
                verdict.status = "failed"
                verdict.notes.append(
                    "check passed but the held-out check failed: the code may be fitted to "
                    "the visible check. Do not show the held-out output to the executor"
                )
        return verdict
    finally:
        if slot:
            slots.release(root, slot, branch if writes else None, keep_branch)
            if writes and not keep_branch:
                verdict.branch = ""
        verdict.seconds = time.monotonic() - started
        verdict.usage = opencode.usage_delta(usage_before, usage_reader(root))
        _record(root, verdict, role)


def _oversized(root: Path, files: list[str], limit_kb: int) -> list[str]:
    """Changed files above the size limit. A deleted file has no size and passes."""
    if limit_kb <= 0:
        return []
    big = []
    for name in files:
        path = root / name
        if path.is_file() and path.stat().st_size > limit_kb * 1024:
            big.append(name)
    return big


def _classify(result) -> tuple[str, str]:
    """Infrastructure outcome of one executor run, separate from result quality."""
    if getattr(result, "stalled", False):
        return "stall", f"no output for too long, killed after {result.seconds:.0f}s"
    if result.timed_out:
        return "timeout", f"killed after {result.seconds:.0f}s"
    if result.returncode != 0 and quota.is_quota(f"{result.stderr}\n{result.stdout}"):
        detail = report.strip_ansi(result.stderr or result.stdout).strip().splitlines()
        return "quota", (detail[-1][:200] if detail else "quota exhausted")
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
            verdict.seconds, outcome=verdict.status, usage=verdict.usage,
        )
