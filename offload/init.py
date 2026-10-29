"""`offload init`: sets the kit up in any project with one command.

The properties it is written for:

- **Repeatable.** Running over an existing install updates what belongs to the
  kit and leaves what belongs to the person alone (policy, settings, their own
  `AGENTS.md` outside our block).
- **Works without a human.** Orchestrators run commands with no keyboard, so
  every question must be avoidable with a flag, and with neither the strictest
  privacy policy is chosen, not the loosest.
- **Breaks nothing.** Foreign files are never overwritten: if something cannot be
  done safely, that is said out loud instead of done silently.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from offload import agents, config, opencode, paths, policy, texts


def detect_verify(root: Path) -> str:
    """Guesses the check command from project markers; empty means no guess."""
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        return "python -m pytest -q"
    if (root / "package.json").exists():
        return "npm test"
    if (root / "Cargo.toml").exists():
        return "cargo test"
    if (root / "go.mod").exists():
        return "go test ./..."
    return ""


def ask_preset(stream_in=None, stream_out=None) -> str:
    """Asks what kind of code this is. Returns the policy preset name."""
    stream_in = stream_in or sys.stdin
    stream_out = stream_out or sys.stdout

    names = list(policy.PRESETS)
    print(
        "\nWhat kind of code is in this project? It decides which models your code may be "
        "sent to.\nFree models run on someone else's servers.\n",
        file=stream_out,
    )
    for index, name in enumerate(names, 1):
        print(f"  {index}. {name:<8} {policy.PRESETS[name]['about']}", file=stream_out)
    print(file=stream_out)

    while True:
        stream_out.write(f"Number [1 = {names[0]}]: ")
        stream_out.flush()
        raw = stream_in.readline()
        if raw == "":
            # End of input, not an empty line: there is nobody to ask.
            raise EOFError("input closed")
        answer = raw.strip()
        if not answer:
            return names[0]
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        if answer in policy.PRESETS:
            return answer
        print("Enter a number from the list.", file=stream_out)


def _managed_block(section: str, verify: str) -> str:
    return section.replace("{verify}", verify or "not set: define it in .offload/config.json")


def write_agents_md(root: Path, verify: str) -> str:
    """Inserts or updates our block in AGENTS.md. Touches nothing else."""
    path = root / "AGENTS.md"
    block = _managed_block(texts.AGENTS_SECTION, verify)

    if not path.exists():
        path.write_text(f"# Project rules\n\n{block}", encoding="utf-8")
        return "created AGENTS.md"

    text = path.read_text(encoding="utf-8")
    begin, end = text.find(texts.MARK_BEGIN), text.find(texts.MARK_END)
    if begin != -1 and end > begin:
        end += len(texts.MARK_END)
        new = text[:begin] + block.rstrip("\n") + text[end:]
        if new == text:
            return "AGENTS.md is up to date"
        path.write_text(new, encoding="utf-8")
        return "updated the block in AGENTS.md"

    separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + separator + block, encoding="utf-8")
    return "added a block to AGENTS.md"


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def ensure_gitignore(root: Path) -> str:
    line = f"{paths.DIR_NAME}/state/"
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if line in text.splitlines():
        return ""
    separator = "" if text.endswith("\n") or not text else "\n"
    path.write_text(text + separator + line + "\n", encoding="utf-8")
    return f"added {line} to .gitignore"


def stdin_is_terminal() -> bool:
    """A real terminal on stdin. On Windows `isatty()` is also true for the null
    device, so the console mode is asked for as well."""
    try:
        if not sys.stdin.isatty():
            return False
        if os.name != "nt":
            return True
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_uint32())))
    except (AttributeError, OSError, ValueError):
        return False


def init(
    root: Path,
    privacy: str | None = None,
    verify: str | None = None,
    interactive: bool | None = None,
) -> list[str]:
    """Sets the kit up. Returns report lines for the person."""
    report: list[str] = []
    if interactive is None:
        interactive = stdin_is_terminal()

    # Privacy: a flag beats the question, and with neither the strictest wins.
    first_time = not paths.policy_file(root).exists()
    if first_time:
        if privacy is None:
            try:
                if not interactive:
                    raise EOFError
                privacy = ask_preset()
            except EOFError:
                privacy = policy.DEFAULT_PRESET
                report.append(
                    f"privacy: chose the strictest ({privacy}) because there is nobody to ask. "
                    "To change: edit .offload/policy.json, or delete it and run "
                    "offload init --privacy open|private|strict"
                )
        if privacy not in policy.PRESETS:
            raise SystemExit(f"unknown policy '{privacy}'; choose from: {', '.join(policy.PRESETS)}")
        policy.save(root, policy.Policy.from_preset(privacy))
        report.append(f"privacy policy: {privacy} - {policy.PRESETS[privacy]['about']}")
    else:
        report.append("privacy policy already set - leaving it alone")

    cfg = config.load(root)
    if verify is not None:
        cfg.verify = verify
    elif not cfg.verify:
        cfg.verify = detect_verify(root)
    if first_time or verify is not None or not paths.config_file(root).exists():
        config.save(root, cfg)
    report.append(
        f"result check: {cfg.verify}"
        if cfg.verify
        else "result check: NOT DEFINED - delegating is impossible without one, "
        f"set verify in {paths.DIR_NAME}/config.json"
    )

    if write_if_changed(paths.offload_dir(root) / "protocol.md", texts.PROTOCOL):
        report.append("wrote .offload/protocol.md")
    report.append(write_agents_md(root, cfg.verify))

    changed = [
        name
        for name, body in agents.files().items()
        if write_if_changed(paths.agents_dir(root) / name, body)
    ]
    report.append(f"OpenCode agents: updated {len(changed)} of {len(agents.files())}")

    if note := ensure_gitignore(root):
        report.append(note)

    claude = root / "CLAUDE.md"
    if not claude.exists():
        claude.write_text("# Project rules - see [AGENTS.md](AGENTS.md)\n", encoding="utf-8")
        report.append("created a CLAUDE.md pointer (Claude Code reads it, not AGENTS.md)")
    elif "AGENTS.md" not in claude.read_text(encoding="utf-8"):
        report.append(
            "CLAUDE.md does not link to AGENTS.md - add a link, or Claude Code "
            "will not see the delegation rules"
        )

    try:
        report.append(f"opencode found: {opencode.version()}")
    except opencode.OpenCodeError as error:
        report.append(f"WARNING: {error}")
    return report
