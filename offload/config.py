"""Project settings: `.offload/config.json`.

Holds pointers and parameters but no model names: the model is chosen from fresh
data every time, and settings can only carry a preference ("use that one for
review") that applies only while the model is acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from offload import jsonio, paths
from offload.catalog import DEFAULT_URL as DEFAULT_CATALOG
from offload.privacy import DEFAULT_SOURCES

DEFAULT_TTL_HOURS = 24


@dataclass
class Config:
    # Command that verifies the result. Empty means nothing to verify with, and
    # delegating is not allowed: without a machine check this is a junk generator.
    verify: str = ""
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    # Where model prices come from (see `catalog`).
    catalog: str = DEFAULT_CATALOG
    ttl_hours: int = DEFAULT_TTL_HOURS
    # Seconds. A hung executor is killed, a hung check is reported as such.
    executor_timeout: int = 900
    verify_timeout: int = 600
    # Seconds without any output from the executor before it counts as stalled
    # and is killed. A provider that stops answering otherwise burns the whole
    # executor_timeout. 0 disables the check.
    stall_timeout: int = 600
    # Files the executor leaves behind that are larger than this (kilobytes) are
    # discarded: heap dumps and build outputs do not belong in a commit.
    max_file_kb: int = 5120
    # Hours a provider is skipped after it reported an exhausted quota.
    quota_cooldown_hours: float = 1.0
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
            "catalog": self.catalog,
            "ttl_hours": self.ttl_hours,
            "executor_timeout": self.executor_timeout,
            "verify_timeout": self.verify_timeout,
            "stall_timeout": self.stall_timeout,
            "max_file_kb": self.max_file_kb,
            "quota_cooldown_hours": self.quota_cooldown_hours,
            "scope": self.scope,
            "prefer": self.prefer,
        }


def load(root: Path) -> Config:
    data = jsonio.read(paths.config_file(root), {})
    base = Config()
    return Config(
        verify=str(data.get("verify", base.verify)),
        sources=list(data.get("sources", base.sources)),
        catalog=str(data.get("catalog", base.catalog)),
        ttl_hours=int(data.get("ttl_hours", base.ttl_hours)),
        executor_timeout=int(data.get("executor_timeout", base.executor_timeout)),
        verify_timeout=int(data.get("verify_timeout", base.verify_timeout)),
        stall_timeout=int(data.get("stall_timeout", base.stall_timeout)),
        max_file_kb=int(data.get("max_file_kb", base.max_file_kb)),
        quota_cooldown_hours=float(data.get("quota_cooldown_hours", base.quota_cooldown_hours)),
        scope=list(data.get("scope", [])),
        prefer=dict(data.get("prefer", {})),
    )


def save(root: Path, config: Config) -> None:
    jsonio.write(paths.config_file(root), config.to_dict())
