"""Что модели реально делали: единственный честный источник качества.

Рейтинги популярности качества не показывают, а таблицы с чужими замерами
меряют чужие задачи. Поэтому после каждого прогона записывается, какая модель
какую задачу прошла по **проверке** и во что это обошлось. Выбор среди
допустимых моделей строится по этим записям, а не по слухам.
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
            continue  # оборванная запись не должна лишать всей истории
    return entries


def stats(root: Path, role: str | None = None) -> dict[str, Stats]:
    """Сводка по моделям: сколько прогонов и сколько из них прошло проверку."""
    totals: dict[str, list[int]] = {}
    for entry in load(root):
        if role and entry.get("role") != role:
            continue
        counter = totals.setdefault(entry["model"], [0, 0])
        counter[0] += 1
        counter[1] += 1 if entry.get("passed") else 0
    return {model: Stats(runs=c[0], passed=c[1]) for model, c in totals.items()}
