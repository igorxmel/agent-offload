"""OpenCode agent profiles that `init` puts into a project.

Format follows the OpenCode v2 docs: a markdown file in `.opencode/agents/` with
permissions in the frontmatter. Permissions are built from **explicit denies
only**: when running without a human the `--auto` flag approves everything not
denied outright, and relying on an "allow?" prompt is pointless - nobody is there
to answer it.

One deny is shared by every role and is mandatory: by default OpenCode allows
leaving the project folder (`external_directory`), and without the rule below the
executor could read and write anywhere.
"""

from __future__ import annotations

PREFIX = "offload-"

# Denies shared by every role. Order matters: the last matching rule wins.
COMMON_DENY = [
    ("external_directory", "*"),
    ("read", "*.env"),
    ("read", "*.env.*"),
    ("read", "*.pem"),
    ("read", "*.key"),
    ("shell", "git push *"),
    ("shell", "git reset --hard *"),
    ("shell", "rm -rf *"),
]

ROLES: dict[str, dict] = {
    "explore": {
        "mode": "primary",
        "description": "Reads code and returns a summary. Changes nothing.",
        "deny": [("edit", "*"), ("shell", "*")],
        "prompt": (
            "You investigate code and answer the orchestrator, not a human. "
            "Output: a bulleted summary with file paths and line numbers. "
            "No preamble, no restating the task, no explaining basics. "
            "If you do not know, say so; do not guess."
        ),
    },
    "plan": {
        "mode": "primary",
        "description": "Reads code and returns a work plan. Changes nothing.",
        "deny": [("edit", "*"), ("shell", "*")],
        "prompt": (
            "You write a plan for the orchestrator. Output: numbered steps, each with "
            "its files and a way to check the step is done. Separately: risks and "
            "questions that must be answered before starting. No filler."
        ),
    },
    "build": {
        "mode": "primary",
        "description": "Implements the task and runs the check until it is green.",
        "deny": [],
        "prompt": (
            "You are the executor. Report to the orchestrator strictly in the format of "
            ".offload/protocol.md: DONE / VERIFIED / NOT DONE / DECISIONS / BLOCKERS. "
            "In VERIFIED paste real command output, not the words 'all works'. "
            "Do not fit code to the tests: if a test is wrong, say so in BLOCKERS. "
            "Change only what the task names."
        ),
    },
    "review": {
        "mode": "primary",
        "description": "Reviews someone else's changes and lists problems. Changes nothing.",
        "deny": [("edit", "*")],
        "prompt": (
            "You are a reviewer for the orchestrator. Output: findings in descending "
            "severity, each with file, line and why it is bad. No findings - say so in one "
            "line. Do not praise and do not summarise the change."
        ),
    },
}


def render(role: str) -> str:
    spec = ROLES[role]
    rules = [("deny", action, resource) for action, resource in COMMON_DENY + spec["deny"]]
    lines = ["---", f"description: {spec['description']}", f"mode: {spec['mode']}", "permissions:"]
    for effect, action, resource in rules:
        lines += [
            f"  - action: {action}",
            f'    resource: "{resource}"',
            f"    effect: {effect}",
        ]
    lines += ["---", "", spec["prompt"], ""]
    return "\n".join(lines)


def files() -> dict[str, str]:
    """File name -> contents for every role."""
    return {f"{PREFIX}{role}.md": render(role) for role in ROLES}
