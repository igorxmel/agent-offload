"""Где что лежит внутри проекта.

Всё, что набор создаёт в чужом проекте, живёт в одной папке `.offload/`:
удалить её значит убрать набор целиком. Исключение — файлы, которые обязаны
лежать там, где их ищут сами агенты (`AGENTS.md`, `.opencode/agents`).
"""

from __future__ import annotations

from pathlib import Path

DIR_NAME = ".offload"


def offload_dir(root: Path) -> Path:
    return root / DIR_NAME


def config_file(root: Path) -> Path:
    return offload_dir(root) / "config.json"


def policy_file(root: Path) -> Path:
    return offload_dir(root) / "policy.json"


def state_dir(root: Path) -> Path:
    """Всё, что пересоздаётся само и в репозиторий не едет."""
    return offload_dir(root) / "state"


def discovery_file(root: Path) -> Path:
    return state_dir(root) / "discovery.json"


def history_file(root: Path) -> Path:
    return state_dir(root) / "history.jsonl"


def agents_dir(root: Path) -> Path:
    return root / ".opencode" / "agents"
