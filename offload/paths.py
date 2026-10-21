"""Where things live inside a project.

Everything the kit creates in someone else's project lives in one folder,
`.offload/`: deleting it removes the kit. The exceptions are files that must sit
where the agents themselves look for them (`AGENTS.md`, `.opencode/agents`).
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
    """Everything that regenerates itself and stays out of the repository."""
    return offload_dir(root) / "state"


def discovery_file(root: Path) -> Path:
    return state_dir(root) / "discovery.json"


def history_file(root: Path) -> Path:
    return state_dir(root) / "history.jsonl"


def agents_dir(root: Path) -> Path:
    return root / ".opencode" / "agents"
