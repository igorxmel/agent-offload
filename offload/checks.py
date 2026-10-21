"""Running the project's check command: the kit's own verdict, not the executor's.

The executor's report says "tests are green" because it wants to be done. The
kit runs the check itself, on the branch the executor produced, and reports what
the command actually printed.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from offload import report

TAIL_LINES = 25


@dataclass
class CheckResult:
    command: str
    exit_code: int | None
    timed_out: bool
    seconds: float
    tail: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "seconds": round(self.seconds, 1),
            "tail": self.tail,
        }


def run(root: Path, command: str, timeout: int) -> CheckResult:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=root,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        code, timed_out = result.returncode, False
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") if isinstance(error.stdout, str) else ""
        code, timed_out = None, True

    lines = report.strip_ansi(output).strip().splitlines()
    tail = "\n".join(lines[-TAIL_LINES:])
    return CheckResult(command, code, timed_out, time.monotonic() - started, tail)
