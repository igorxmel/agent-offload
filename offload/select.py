"""Choosing a model among the acceptable ones.

No names here. The order: the preference from settings (if that model is
acceptable), then the best by the project's **own runs**, then - while there are
no runs - the first in OpenCode's list. The last one is honestly called a guess:
judging quality by a model's name would be the same hardcoding, hidden in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from offload import config, history
from offload.discover import Snapshot


@dataclass(frozen=True)
class Choice:
    model: str
    basis: str  # prefer | history | guess


def ranked(root: Path, snapshot: Snapshot, role: str) -> list[Choice]:
    """Every acceptable model, best first. Delegation walks this list on failure."""
    allowed = [entry.id for entry in snapshot.allowed()]
    if not allowed:
        return []

    chosen: list[Choice] = []
    wanted = config.load(root).prefer.get(role)
    if wanted in allowed:
        chosen.append(Choice(wanted, "prefer"))

    measured = {m: s for m, s in history.stats(root, role).items() if m in allowed and s.runs}
    for model in sorted(measured, key=lambda m: (measured[m].rate, measured[m].runs), reverse=True):
        if model not in {c.model for c in chosen}:
            chosen.append(Choice(model, "history"))

    for model in allowed:
        if model not in {c.model for c in chosen}:
            chosen.append(Choice(model, "guess"))
    return chosen


def pick(root: Path, snapshot: Snapshot, role: str) -> Choice | None:
    options = ranked(root, snapshot, role)
    return options[0] if options else None
