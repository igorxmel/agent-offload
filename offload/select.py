"""Choosing a model among the acceptable ones.

No names here. The order: the preference from settings (if that model is
acceptable), then the best by the project's **own runs**, then the models nobody
has measured, still honestly called a guess. Judging quality by a model's name
would be the same hardcoding, hidden in code; the guess uses only catalog facts
that matter to an agent: a context window too small to hold an agent's prompt
and tool definitions goes last, then the newest release first, then the larger
context.
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

    facts = {entry.id: entry.meta or {} for entry in snapshot.allowed()}
    for model in sorted(allowed, key=lambda m: _guess_order(facts[m])):
        if model not in {c.model for c in chosen}:
            chosen.append(Choice(model, "guess"))
    return chosen


# An agent's first request (system prompt + tool definitions + task) runs to
# thousands of tokens and grows every step; below this a model chokes early.
MIN_AGENT_CONTEXT = 128_000


def _guess_order(fact: dict) -> tuple:
    context = fact.get("context") or 0
    released = fact.get("released") or ""
    # Python sorts ascending: negate what should come first.
    return (context < MIN_AGENT_CONTEXT, not released, [-ord(c) for c in released], -context)


def pick(root: Path, snapshot: Snapshot, role: str) -> Choice | None:
    options = ranked(root, snapshot, role)
    return options[0] if options else None
