"""Настройки проекта: `.offload/config.json`.

Хранятся указатели и параметры, но не названия моделей: выбор модели делается
по свежим данным каждый раз, а в настройках может лежать только пожелание
(«для проверки возьми такую-то»), которое действует, лишь пока модель допустима.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from offload import jsonio, paths
from offload.privacy import DEFAULT_SOURCES

DEFAULT_TTL_HOURS = 24


@dataclass
class Config:
    # Команда, которой проверяется результат. Пустая — проверять нечем, и
    # делегировать нельзя: без машинной проверки это генератор мусора.
    verify: str = ""
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    ttl_hours: int = DEFAULT_TTL_HOURS
    # Пожелания по ролям: {"implement": "opencode/…"}. Только пожелания.
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
