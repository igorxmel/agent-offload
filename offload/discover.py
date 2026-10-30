"""What exists right now: models, data-handling terms, the policy verdict.

The result is cached for a day: the page rarely changes, and hitting it on every
call would slow the orchestrator down at every step. If the network is down the
stale cache is used with a warning; if there is none either, models stay without
privacy data and are therefore denied (see `policy`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from offload import config as config_mod
from offload import catalog, jsonio, opencode, paths, policy, privacy


@dataclass
class Entry:
    id: str
    privacy: privacy.Privacy | None
    allowed: bool
    reason: str
    # [input, output] dollars per million tokens; None when the catalog does not know.
    cost: list[float] | None = None


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
    # A cache written before prices and tool use were collected is refreshed rather
    # than read as "every price unknown". Both keys are written together.
    data["stale"] = age_hours > ttl_hours or "tools" not in data
    return data


def _facts(
    root: Path, cfg: config_mod.Config, refresh: bool, fetcher, lister, price_fetcher, now: float
):
    """Models and the privacy table: from cache or from the source."""
    cached = _read_cache(root, cfg.ttl_hours, now)
    if cached and not cached["stale"] and not refresh:
        return cached, []

    warnings: list[str] = []
    try:
        model_ids = lister()
    except opencode.OpenCodeError as error:
        if cached:
            return cached, [f"model list not refreshed ({error}); using the previous one"]
        raise

    rows, problems = privacy.collect(cfg.sources, fetcher)
    warnings.extend(problems)
    if not rows and cached:
        # Page unreachable or changed: previous data beats no data.
        rows = [privacy.Privacy(**row) for row in cached.get("privacy", [])]
        warnings.append("privacy table not retrieved; using previous data")

    costs, tools, problem = catalog.collect(cfg.catalog, model_ids, price_fetcher)
    if problem:
        warnings.append(f"price catalog: {problem}")
        if cached:
            costs = {m: c for m, c in cached.get("costs", {}).items() if m in model_ids}
            tools = {m: t for m, t in cached.get("tools", {}).items() if m in model_ids}
            warnings.append("price catalog not retrieved; using previous prices")

    data = {
        "fetched_at": now,
        "models": model_ids,
        "privacy": [row.to_dict() for row in rows],
        "costs": costs,
        "tools": tools,
    }
    jsonio.write(paths.discovery_file(root), data)
    return data, warnings


def discover(
    root: Path,
    refresh: bool = False,
    fetcher=privacy.fetch,
    lister=opencode.models,
    price_fetcher=catalog.fetch,
    now: float | None = None,
) -> Snapshot:
    """Builds the current picture and applies the project policy to it."""
    now = time.time() if now is None else now
    cfg = config_mod.load(root)
    pol = policy.load(root)

    data, warnings = _facts(root, cfg, refresh, fetcher, lister, price_fetcher, now)

    by_key = {
        privacy.normalize(row["name"]): privacy.Privacy(**row) for row in data.get("privacy", [])
    }
    costs = data.get("costs", {})
    tools = data.get("tools", {})
    entries: list[Entry] = []
    for model_id in data.get("models", []):
        info = by_key.get(privacy.normalize(policy.short_id(model_id)))
        cost = costs.get(model_id)
        verdict = policy.evaluate(model_id, info, pol, cost=cost, tools=tools.get(model_id))
        entries.append(Entry(model_id, info, verdict.allowed, verdict.reason, cost))

    if data.get("stale") and not refresh:
        warnings.append("data is stale; refresh with: offload discover")
    return Snapshot(fetched_at=data["fetched_at"], entries=entries, warnings=warnings)
