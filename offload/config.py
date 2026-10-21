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
    # Per-role preferences: {"build": "provider/model"}. Preferences only.
    prefer: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "verify": self.verify,
            "sources": self.sources,
            "ttl_hours": self.ttl_hours,
            "prefer": self.prefer,
        }


def load(root: Path) -> Config:
    data = jsonio.read(paths.config_file(root), {})
    base = Config()
    return Config(
        verify=str(data.get("verify", base.verify)),
        sources=list(data.get("sources", base.sources)),
        ttl_hours=int(data.get("ttl_hours", base.ttl_hours)),
        prefer=dict(data.get("prefer", {})),
    )


def save(root: Path, config: Config) -> None:
    jsonio.write(paths.config_file(root), config.to_dict())
