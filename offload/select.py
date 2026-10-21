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


def pick(root: Path, snapshot: Snapshot, role: str) -> Choice | None:
    allowed = {entry.id for entry in snapshot.allowed()}
    if not allowed:
        return None

    wanted = config.load(root).prefer.get(role)
    if wanted in allowed:
        return Choice(wanted, "prefer")

    measured = {m: s for m, s in history.stats(root, role).items() if m in allowed and s.runs}
    if measured:
        best = max(measured, key=lambda m: (measured[m].rate, measured[m].runs))
        return Choice(best, "history")

    first = next(entry.id for entry in snapshot.entries if entry.id in allowed)
    return Choice(first, "guess")
