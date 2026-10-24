"""Project settings: `.offload/config.json`.

Holds pointers and parameters but no model names: the model is chosen from fresh
data every time, and settings can only carry a preference ("use that one for
review") that applies only while the model is acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from offload import jsonio, paths
from offload.privacy import DEFAULT_SOURCES

DEFAULT_TTL_HOURS = 24


@dataclass
class Config:
    # Command that verifies the result. Empty means nothing to verify with, and
    # delegating is not allowed: without a machine check this is a junk generator.
    verify: str = ""
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    ttl_hours: int = DEFAULT_TTL_HOURS
    # Seconds. A hung executor is killed, a hung check is reported as such.
    executor_timeout: int = 900
    verify_timeout: int = 600
    # Folders the executor may change, relative to the project root. Empty means no
    # limit. Anything outside is discarded: a green check says nothing about files
    # the task never named.
    scope: list[str] = field(default_factory=list)
    # Per-role preferences: {"build": "provider/model"}. Preferences only.
    prefer: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "verify": self.verify,
            "sources": self.sources,
            "ttl_hours": self.ttl_hours,
            "executor_timeout": self.executor_timeout,
            "verify_timeout": self.verify_timeout,
            "scope": self.scope,
            "prefer": self.prefer,
        }


def load(root: Path) -> Config:
    data = jsonio.read(paths.config_file(root), {})
    base = Config()
    return Config(
        verify=str(data.get("verify", base.verify)),
        sources=list(data.get("sources", base.sources)),
        ttl_hours=int(data.get("ttl_hours", base.ttl_hours)),
        executor_timeout=int(data.get("executor_timeout", base.executor_timeout)),
        verify_timeout=int(data.get("verify_timeout", base.verify_timeout)),
        scope=list(data.get("scope", [])),
        prefer=dict(data.get("prefer", {})),
    )


def save(root: Path, config: Config) -> None:
    jsonio.write(paths.config_file(root), config.to_dict())
