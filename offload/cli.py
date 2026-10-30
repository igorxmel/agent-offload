"""Command line. The orchestrator calls this.

Every command supports `--json`: the orchestrator is a machine and has no use for
a table meant for humans. Exit codes: 0 success, 1 usage or environment error,
2 no acceptable models, 3 check failed or nothing changed, 4 every executor
attempt failed, 5 the executor touched its own limits (separate codes so an
orchestrator can handle each).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from offload import __version__, delegate, discover, jsonio, opencode, policy, select
from offload import init as init_mod

EXIT_NO_MODELS = 2


def _root(args) -> Path:
    return Path(args.root).resolve()


def _out(args, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else text)


def _warn(snapshot) -> None:
    for line in snapshot.warnings:
        print(f"! {line}", file=sys.stderr)


def cmd_init(args) -> int:
    for line in init_mod.init(_root(args), privacy=args.privacy, verify=args.verify):
        print(f"- {line}")
    return 0


def cmd_models(args) -> int:
    snap = discover.discover(_root(args), refresh=args.refresh)
    _warn(snap)
    entries = snap.allowed() if args.allowed else snap.entries
    data = [
        {
            "id": e.id,
            "allowed": e.allowed,
            "reason": e.reason,
            "privacy": e.privacy.to_dict() if e.privacy else None,
            "cost_per_million": e.cost,
        }
        for e in entries
    ]
    lines = [f"{'yes' if e.allowed else 'no '}  {e.id:<44} {e.reason}" for e in entries]
    _out(args, data, "\n".join(lines) or "no models")
    return 0 if snap.allowed() else EXIT_NO_MODELS


def cmd_pick(args) -> int:
    root = _root(args)
    snap = discover.discover(root, refresh=args.refresh)
    _warn(snap)
    choice = select.pick(root, snap, args.role)
    if choice is None:
        print("no acceptable model. See: offload models", file=sys.stderr)
        return EXIT_NO_MODELS
    _out(
        args,
        {"model": choice.model, "basis": choice.basis},
        f"{choice.model}  ({choice.basis})" if args.verbose else choice.model,
    )
    return 0


def cmd_discover(args) -> int:
    snap = discover.discover(_root(args), refresh=True)
    _warn(snap)
    _out(
        args,
        {"models": len(snap.entries), "allowed": len(snap.allowed())},
        f"models: {len(snap.entries)}, acceptable: {len(snap.allowed())}",
    )
    return 0


def _format_verdict(v) -> str:
    lines = [f"{v.status.upper()}  model={v.model or '-'}  role={v.role}  {v.seconds:.0f}s"]
    if v.branch:
        lines.append(f"branch: {v.branch}  (base {v.base})")
    if v.files:
        lines.append(f"files: {', '.join(v.files[:12])}" + (" ..." if len(v.files) > 12 else ""))
    if v.diffstat:
        lines.append(f"diff: {v.diffstat}")
    if v.verify:
        outcome = "PASSED" if v.verify["exit_code"] == 0 and not v.verify["timed_out"] else "FAILED"
        lines.append(f"check [{outcome}]: {v.verify['command']}")
        lines.append(v.verify["tail"] or "(no output)")
    if v.holdout:
        held = "PASSED" if v.holdout["exit_code"] == 0 and not v.holdout["timed_out"] else "FAILED"
        lines.append(f"held-out check [{held}]")
        if held == "FAILED":
            lines.append(v.holdout["tail"] or "(no output)")
    for name in ("ANSWER", "DONE", "NOT DONE", "BLOCKERS", "DECISIONS", "RAW"):
        if v.report.get(name):
            lines.append(f"{name}: {v.report[name]}")
    for attempt in v.attempts:
        if attempt.outcome != "ok":
            lines.append(f"attempt {attempt.model}: {attempt.outcome} {attempt.detail}")
    if v.usage:
        u = v.usage
        lines.append(
            f"executor spent: {u['steps']:.0f} steps, {u['input']:.0f} in / {u['output']:.0f} out / "
            f"{u['reasoning']:.0f} reasoning tokens, {u['cache_read']:.0f} from cache, "
            f"${u['cost']:g}"
        )
    lines.extend(f"note: {note}" for note in v.notes)
    for side in v.partial:
        lines.append(f"partial (unverified): {side}")
    if v.branch and v.status == "passed":
        lines.append(f"merge: git merge {v.branch}   discard: git branch -D {v.branch}")
    return "\n".join(lines)


def cmd_delegate(args) -> int:
    if bool(args.task) == bool(args.task_file):
        print("error: give exactly one of --task or --task-file", file=sys.stderr)
        return 1
    text = args.task or Path(args.task_file).read_text(encoding="utf-8")
    if not text.strip():
        print("error: the task is empty", file=sys.stderr)
        return 1
    try:
        verdict = delegate.delegate(
            _root(args), text, role=args.role, model=args.model,
            verify_cmd=args.verify, max_attempts=args.attempts,
            scope=args.scope or None, holdout_cmd=args.holdout, resume=args.resume,
            on=args.on,
        )
    except delegate.DelegateError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.code
    _out(args, verdict.to_dict(), _format_verdict(verdict))
    return verdict.exit_code


def _edit_list(args, field: str, other: str) -> int:
    root = _root(args)
    pol = policy.load(root)
    getattr(pol, other)[:] = [m for m in getattr(pol, other) if m != args.model]
    if args.model not in getattr(pol, field):
        getattr(pol, field).append(args.model)
    policy.save(root, pol)
    print(f"{args.model}: {'allowed' if field == 'allowed' else 'denied'} manually")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="offload", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", default=".", help="project folder (default: current)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="set the kit up in a project")
    p.add_argument(
        "--privacy", choices=list(policy.PRESETS), help="privacy policy, to skip the question"
    )
    p.add_argument("--verify", help="command that verifies a result")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("models", help="models and whether the policy allows them")
    p.add_argument("--allowed", action="store_true", help="acceptable ones only")
    p.add_argument("--refresh", action="store_true", help="skip the cache")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("pick", help="choose a model among the acceptable ones")
    p.add_argument("--role", default="build", help="explore | plan | build | review")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="show the basis of the choice")
    p.set_defaults(func=cmd_pick)

    p = sub.add_parser("delegate", help="hand a task to an executor and get a verdict")
    p.add_argument("--task", help="the task text")
    p.add_argument("--task-file", help="file holding the task text")
    p.add_argument("--role", default="build", help="explore | plan | build | review")
    p.add_argument("--model", help="force a model (must be acceptable under the policy)")
    p.add_argument("--verify", help="check command, overriding .offload/config.json")
    p.add_argument("--attempts", type=int, default=3, help="models to try on infrastructure failure")
    p.add_argument("--scope", action="append", metavar="PATH",
                   help="folder the executor may change (repeatable); the rest is discarded")
    p.add_argument("--resume", metavar="BRANCH",
                   help="continue from an earlier offload/... branch; --task then holds the "
                        "numbered list of discrepancies to fix")
    p.add_argument("--on", metavar="BRANCH",
                   help="read-only roles: look at this branch (e.g. --role review on an "
                        "offload/... branch) in a separate working copy")
    p.add_argument("--holdout", metavar="CMD",
                   help="second check the executor never sees; run after --verify passes. "
                        "Flag only: a config file is readable by the executor")
    p.set_defaults(func=cmd_delegate)

    p = sub.add_parser("discover", help="refresh the model list and privacy terms")
    p.set_defaults(func=cmd_discover)

    for name, field, other, text in (
        ("allow", "allowed", "denied", "allow a model manually"),
        ("deny", "denied", "allowed", "deny a model manually"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("model")
        p.set_defaults(func=lambda a, f=field, o=other: _edit_list(a, f, o))
    return parser


def main(argv: list[str] | None = None) -> int:
    # Always UTF-8 output: the orchestrator reads it as text, and the Windows
    # console code page turns non-ASCII into unreadable bytes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (opencode.OpenCodeError, jsonio.ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
