"""Texts that `init` puts into a project.

They live in code rather than in separate files: the kit installs with one
command, and a template cannot be lost while copying.
"""

from __future__ import annotations

MARK_BEGIN = "<!-- offload:begin (managed by agent-offload; edits inside will be overwritten) -->"
MARK_END = "<!-- offload:end -->"

AGENTS_SECTION = f"""{MARK_BEGIN}
## Delegating work (agent-offload)

Bulk work can be handed to OpenCode's free models: the executor writes, the
orchestrator sets the goal and verifies the result. Rules of engagement:
`.offload/protocol.md`.

Commands (`offload --help`): `offload models` lists acceptable models,
`offload pick` chooses one, `offload delegate` hands over a task.

Result check: `{{verify}}`. Do not trust the executor's report: the orchestrator
runs the check itself.
{MARK_END}
"""

PROTOCOL = """# Protocol: orchestrator and executor

Two machines talk, and both are professionals. No preamble, no apologies, no
restating the task, no explaining basics. Substance only.

## Orchestrator -> executor

Keep the task short: goal, files, definition of done (the check command and what
it must show). The executor reads the project itself, from `AGENTS.md` and the
code. Do not retell what it can find in a second.

## Executor -> orchestrator

Answer strictly in this form, with no text before or after:

```
DONE:       file - what changed (one line per file)
VERIFIED:   command -> pasted real output
NOT DONE:   what and why
DECISIONS:  where you chose yourself, one phrase on why
BLOCKERS:   what you need from the orchestrator
```

VERIFIED holds command output, not "all works". An empty section is the word "none".

## What the executor must not do

- fit code to the tests: if a test is wrong, say so in BLOCKERS;
- change anything the task does not name;
- leave the project folder, read secrets (`*.env`, keys), or `git push`;
- install anything: a missing dependency goes in BLOCKERS, the orchestrator installs it;
- edit `.offload/`, `.opencode/` or `opencode.json*`: those are the executor's own limits.

## What the orchestrator must do

- **Not trust the report.** A model can confidently write "tests are green". The
  orchestrator runs the check itself, on data the executor has not seen.
- Read code in full only where the check failed or the change is suspiciously large.
- Give the executor not explanations but a numbered list of discrepancies.
"""
