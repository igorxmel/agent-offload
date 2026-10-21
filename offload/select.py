"""Выбор модели среди допустимых.

Названий здесь нет. Порядок такой: пожелание из настроек (если модель
допустима), затем лучшая по **собственным прогонам** проекта, затем — пока
прогонов нет — первая в списке OpenCode. Последнее честно называется догадкой:
угадывать качество по названию модели было бы тем же хардкодом, только
спрятанным в код.
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
