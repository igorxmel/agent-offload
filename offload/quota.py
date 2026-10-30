"""Exhausted quotas: telling them apart from failures, and skipping the provider.

A quota stop says nothing about a model's quality, so it must not lower the
model's rank in the history. And a quota is usually per account, not per model
(seen on 2026-10-29: every free OpenCode model refused within seconds once one
did), so after one quota stop the other models of the same provider are skipped
for a while instead of being tried and refused one by one.

The messages below are what providers actually printed through `opencode run`.
A message that is not recognised is an ordinary error, which is the safe side:
the next model is tried and the failure is recorded.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from offload import jsonio, paths

# Matched case-insensitively against the executor's error output.
QUOTA_PATTERNS = (
    r"usage limit reached",  # OpenCode Zen: "Free usage limit reached."
    r"exceeded your current quota",  # Google AI Studio
    r"quota exceeded",
    r"free-models-per-day",  # OpenRouter: "Rate limit exceeded: free-models-per-day"
    r"daily limit reached",  # OpenRouter, per model: "Daily limit reached for <model>"
    r"\blimit_rpd\b",  # the same, as the provider's error code
    r"insufficient (credits|quota|balance)",
)
_QUOTA = re.compile("|".join(QUOTA_PATTERNS), re.IGNORECASE)


def is_quota(text: str) -> bool:
    return bool(_QUOTA.search(text or ""))


def provider(model: str) -> str:
    return model.split("/", 1)[0]


def _file(root: Path) -> Path:
    return paths.state_dir(root) / "quota.json"


def mark(root: Path, model: str, now: float | None = None) -> None:
    data = jsonio.read(_file(root), {})
    data[provider(model)] = time.time() if now is None else now
    jsonio.write(_file(root), data)


def exhausted(root: Path, cooldown_hours: float, now: float | None = None) -> set[str]:
    """Providers that reported an exhausted quota within the cooldown."""
    now = time.time() if now is None else now
    data = jsonio.read(_file(root), {})
    return {p for p, ts in data.items() if now - float(ts) < cooldown_hours * 3600}
