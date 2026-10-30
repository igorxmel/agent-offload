"""Model prices, taken from the public catalog OpenCode itself is built on.

Why this exists: once a person connects a provider with a key (OpenRouter, Groq,
Google), `opencode models` lists that provider's paid models too - hundreds of
them next to a handful of free ones. A kit for free models must not quietly pick
a paid one, so every model needs a known price.

Same rules as the privacy table: the catalog is data, not instructions; only the
`cost` fields of the listed models are read; a price that cannot be found is
unknown, and an unknown price is denied (see `policy`). No model is named here.

What the catalog cannot know: whether *your key* is on a free tier. Groq and
Google list a real price per token even though a free-tier key is not billed.
That is the person's call: `offload allow groq/*`.
"""

from __future__ import annotations

import json
import urllib.request

# Pointer, not data: the settings can override it.
DEFAULT_URL = "https://models.dev/api.json"

TIMEOUT = 60  # the catalog is several megabytes
USER_AGENT = "agent-offload"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def prices(text: str, model_ids: list[str]) -> dict[str, list[float]]:
    """`provider/model` -> [input, output] in dollars per million tokens.

    Models missing from the catalog, or without both numbers, are left out:
    absence means "unknown", never "free".
    """
    catalog = json.loads(text)
    if not isinstance(catalog, dict):
        raise TypeError("catalog is not a JSON object")
    found: dict[str, list[float]] = {}
    for model_id in model_ids:
        provider, _, name = model_id.partition("/")
        entry = (catalog.get(provider) or {}).get("models", {}).get(name) if name else None
        cost = entry.get("cost") if isinstance(entry, dict) else None
        if not isinstance(cost, dict):
            continue
        pair = [_number(cost.get("input")), _number(cost.get("output"))]
        if None not in pair and min(pair) >= 0:
            found[model_id] = pair
    return found


def tool_use(text: str, model_ids: list[str]) -> dict[str, bool]:
    """`provider/model` -> whether it can call tools. An agent cannot work without
    them: a music or moderation model is free but useless as an executor. Models
    without a boolean flag are left out (unknown)."""
    catalog = json.loads(text)
    found: dict[str, bool] = {}
    for model_id in model_ids:
        provider, _, name = model_id.partition("/")
        entry = (catalog.get(provider) or {}).get("models", {}).get(name) if name else None
        flag = entry.get("tool_call") if isinstance(entry, dict) else None
        if isinstance(flag, bool):
            found[model_id] = flag
    return found


def meta(text: str, model_ids: list[str]) -> dict[str, dict]:
    """`provider/model` -> {"context": tokens or None, "released": "YYYY-MM-DD" or None}.

    Used only to order models nobody has measured yet (see `select`), never to
    allow or deny one, so a missing value is simply None.
    """
    catalog = json.loads(text)
    found: dict[str, dict] = {}
    for model_id in model_ids:
        provider, _, name = model_id.partition("/")
        entry = (catalog.get(provider) or {}).get("models", {}).get(name) if name else None
        if not isinstance(entry, dict):
            continue
        limit = entry.get("limit") if isinstance(entry.get("limit"), dict) else {}
        context = limit.get("context")
        released = entry.get("release_date")
        found[model_id] = {
            "context": context if isinstance(context, int) and not isinstance(context, bool)
            else None,
            "released": released if isinstance(released, str) else None,
        }
    return found


def collect(
    url: str, model_ids: list[str], fetcher=fetch
) -> tuple[dict[str, list[float]], dict[str, bool], dict[str, dict], str]:
    """Prices, tool use and ordering facts, and a problem description when the
    catalog could not be used."""
    try:
        text = fetcher(url)
        return prices(text, model_ids), tool_use(text, model_ids), meta(text, model_ids), ""
    except Exception as error:  # noqa: BLE001 - any failure leaves all of it unknown
        return {}, {}, {}, f"{url}: {error}"
