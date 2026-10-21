"""Thin wrapper around the `opencode` command line program.

The kit does not know how OpenCode works inside and should not: it calls it like
any console program. So there are two things here - find the executable and get
the model list - and both fail with a clear message.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


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


@dataclass
class AgentResult:
    returncode: int
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False


def _kill_tree(process: subprocess.Popen) -> None:
    """Stops the process and everything it spawned.

    The `opencode` command on Windows is a shim that starts other processes, so
    killing only the direct child would leave the real work running.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def run_agent(
    root: Path, agent: str, model: str, message: str, task_file: Path, timeout: int
) -> AgentResult:
    """Runs one executor and waits for it, killing it on timeout.

    The task travels as an attached file and the message is a fixed safe phrase:
    on Windows `opencode` is a `.cmd` shim, so a free-form argument would pass
    through `cmd.exe`, which treats `&`, `|`, `%` and `^` as syntax even in quotes.
    """
    started = time.monotonic()
    extra = {"start_new_session": True} if os.name != "nt" else {}
    process = subprocess.Popen(
        [
            find(), "run", "--auto", "--agent", agent, "--model", model,
            "--file", str(task_file), message,
        ],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **extra,
    )
    try:
        out, err = process.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        out, err = process.communicate()
        timed_out = True
    return AgentResult(
        returncode=process.returncode,
        stdout=out or "",
        stderr=err or "",
        seconds=time.monotonic() - started,
        timed_out=timed_out,
    )
