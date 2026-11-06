"""What models actually did: the only honest source of quality data.

Popularity rankings do not show quality, and tables of other people's benchmarks
measure other people's tasks. So after every run we record which model passed
which task by the **check**, and what it cost. The choice among acceptable models
is built from these records, not from hearsay.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from offload import paths


@dataclass(frozen=True)
class Stats:
    runs: int
    passed: int

    @property
    def rate(self) -> float:
        return self.passed / self.runs if self.runs else 0.0


def record(root: Path, model: str, role: str, passed: bool, seconds: float = 0.0, **extra) -> None:
    path = paths.history_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": int(time.time()),
        "model": model,
        "role": role,
        "passed": passed,
        "seconds": round(seconds, 1),
        **extra,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load(root: Path) -> list[dict]:
    path = paths.history_file(root)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue  # a truncated record must not cost the whole history
    return entries


def budget_today(root: Path, now: float | None = None) -> dict[str, dict]:
    """Executor requests per provider since 00:00 UTC, when free daily quotas reset.

    `steps` counts the model requests of every recorded attempt with known usage;
    `quota_after` is the step count at which a quota stop was last seen today - the
    best estimate of that provider's daily allowance, since providers do not publish
    it reliably (OpenRouter's moved from ~500 to ~100 requests within a week).
    Per project: other projects and people sharing an account or an IP draw from
    the same allowance unseen.
    """
    now = time.time() if now is None else now
    day_start = now - now % 86400
    totals: dict[str, dict] = {}
    for entry in load(root):
        if entry.get("ts", 0) < day_start:
            continue
        provider = str(entry.get("model", "")).split("/", 1)[0]
        row = totals.setdefault(provider, {"steps": 0, "attempts": 0, "quota_after": None})
        row["attempts"] += 1
        usage = entry.get("usage") or {}
        steps = usage.get("steps")
        if isinstance(steps, (int, float)) and not isinstance(steps, bool):
            row["steps"] += int(steps)
        if entry.get("outcome") == "quota":
            row["quota_after"] = row["steps"]
    return totals


def stats(root: Path, role: str | None = None) -> dict[str, Stats]:
    """Per-model summary: how many runs and how many passed the check.

    A run stopped by an exhausted quota is kept in the file but not counted: it
    says nothing about the model, only about the account.
    """
    totals: dict[str, list[int]] = {}
    for entry in load(root):
        if role and entry.get("role") != role:
            continue
        if entry.get("outcome") == "quota":
            continue
        counter = totals.setdefault(entry["model"], [0, 0])
        counter[0] += 1
        counter[1] += 1 if entry.get("passed") else 0
    return {model: Stats(runs=c[0], passed=c[1]) for model, c in totals.items()}
