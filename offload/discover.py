"""Что есть сейчас: модели, условия обработки данных, итог по политике.

Результат кэшируется на сутки: страница меняется редко, а ходить на неё при
каждом вызове значило бы тормозить оркестратора на каждом шаге. Если сеть
недоступна, берётся устаревший кэш с предупреждением; если нет и его — модели
остаются без данных о приватности, а значит запрещены (см. `policy`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from offload import config as config_mod
from offload import jsonio, opencode, paths, policy, privacy


@dataclass
class Entry:
    id: str
    privacy: privacy.Privacy | None
    allowed: bool
    reason: str


@dataclass
class Snapshot:
    fetched_at: float
    entries: list[Entry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def allowed(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.allowed]


def _read_cache(root: Path, ttl_hours: int, now: float) -> dict | None:
    data = jsonio.read(paths.discovery_file(root), None)
    if not data:
        return None
    age_hours = (now - data.get("fetched_at", 0)) / 3600
    data["stale"] = age_hours > ttl_hours
    return data


def _facts(root: Path, cfg: config_mod.Config, refresh: bool, fetcher, lister, now: float):
    """Модели и таблица приватности: из кэша или с источника."""
    cached = _read_cache(root, cfg.ttl_hours, now)
    if cached and not cached["stale"] and not refresh:
        return cached, []

    warnings: list[str] = []
    try:
        model_ids = lister()
    except opencode.OpenCodeError as error:
        if cached:
            return cached, [f"список моделей не обновлён ({error}); взят прошлый"]
        raise

    rows, problems = privacy.collect(cfg.sources, fetcher)
    warnings.extend(problems)
    if not rows and cached:
        # Страница недоступна или изменилась: прежние данные лучше, чем их отсутствие.
        rows = [privacy.Privacy(**row) for row in cached.get("privacy", [])]
        warnings.append("таблица приватности не получена; использованы прошлые данные")

    data = {
        "fetched_at": now,
        "models": model_ids,
        "privacy": [row.to_dict() for row in rows],
    }
    jsonio.write(paths.discovery_file(root), data)
    return data, warnings


def discover(
    root: Path,
    refresh: bool = False,
    fetcher=privacy.fetch,
    lister=opencode.models,
    now: float | None = None,
) -> Snapshot:
    """Собирает актуальную картину и применяет к ней политику проекта."""
    now = time.time() if now is None else now
    cfg = config_mod.load(root)
    pol = policy.load(root)

    data, warnings = _facts(root, cfg, refresh, fetcher, lister, now)

    by_key = {
        privacy.normalize(row["name"]): privacy.Privacy(**row) for row in data.get("privacy", [])
    }
    entries: list[Entry] = []
    for model_id in data.get("models", []):
        info = by_key.get(privacy.normalize(policy.short_id(model_id)))
        verdict = policy.evaluate(model_id, info, pol)
        entries.append(Entry(model_id, info, verdict.allowed, verdict.reason))

    if data.get("stale") and not refresh:
        warnings.append("данные устарели; обновить: offload discover --refresh")
    return Snapshot(fetched_at=data["fetched_at"], entries=entries, warnings=warnings)
