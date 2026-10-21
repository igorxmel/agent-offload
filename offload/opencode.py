"""Тонкая обёртка над консольной программой `opencode`.

Набор не знает, как OpenCode устроен внутри, и знать не должен: он вызывает
его как любую консольную программу. Поэтому здесь ровно две вещи — найти
исполняемый файл и получить список моделей, — и обе падают понятным текстом.
"""

from __future__ import annotations

import shutil
import subprocess


class OpenCodeError(Exception):
    """OpenCode не найден или не ответил."""


def find() -> str:
    path = shutil.which("opencode")
    if not path:
        raise OpenCodeError(
            "opencode не найден в PATH. Установка и документация: https://opencode.ai/docs"
        )
    return path


def run(args: list[str], timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            [find(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise OpenCodeError(f"opencode {' '.join(args)}: нет ответа за {timeout} с") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:300]
        raise OpenCodeError(f"opencode {' '.join(args)}: код {result.returncode}. {detail}")
    return result.stdout


def version() -> str:
    return run(["--version"], timeout=20).strip()


def models() -> list[str]:
    """Идентификаторы моделей в виде `провайдер/модель`."""
    lines = (line.strip() for line in run(["models"]).splitlines())
    return [line for line in lines if line and "/" in line and " " not in line]
