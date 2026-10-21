"""Thin wrapper around the `opencode` command line program.

The kit does not know how OpenCode works inside and should not: it calls it like
any console program. So there are two things here - find the executable and get
the model list - and both fail with a clear message.
"""

from __future__ import annotations

import shutil
import subprocess


class OpenCodeError(Exception):
    """OpenCode is missing or did not answer."""


def find() -> str:
    path = shutil.which("opencode")
    if not path:
        raise OpenCodeError(
            "opencode not found in PATH. Install and docs: https://opencode.ai/docs"
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
        raise OpenCodeError(f"opencode {' '.join(args)}: no answer in {timeout}s") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:300]
        raise OpenCodeError(f"opencode {' '.join(args)}: exit {result.returncode}. {detail}")
    return result.stdout


def version() -> str:
    return run(["--version"], timeout=20).strip()


def models() -> list[str]:
    """Model identifiers as `provider/model`."""
    lines = (line.strip() for line in run(["models"]).splitlines())
    return [line for line in lines if line and "/" in line and " " not in line]
