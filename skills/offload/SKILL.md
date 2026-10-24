---
name: offload
description: Delegate bulk, machine-verifiable work (porting a module, mass edits, tests, boilerplate, code exploration) to OpenCode's free models to save the orchestrator's own tokens. Use when a task is large and a command can verify the result.
---

# offload

You are the orchestrator. The executor is OpenCode's free models, run from the console.
Your tokens go to the goal, a short verdict and the check - not to writing code.

## When to delegate and when not

Delegate when the task is **large** and the result is checkable by a **command**.
Do not delegate small things or anything you cannot verify: reviewing a weak model's
bad code costs more than writing it yourself. If `verify` in `.offload/config.json` is
empty, delegating is not allowed.

## First time in a project

```
offload init
```

Sets up `.offload/`, the agent profiles in `.opencode/agents/` and a block in
`AGENTS.md`. With no keyboard pass `--privacy strict|private|open`; without the flag the
strictest is chosen. **Do not loosen the privacy policy yourself** - that is the project
owner's decision: free models run on someone else's servers, and some of them train on
prompts. If the owner is available, tell them about the choice you made.

## Choosing a model

```
offload models --allowed --json     # what the project policy allows
offload pick --role build -v        # choose one; basis=guess means "no data yet"
```

The model list and its terms are fetched from official pages at run time; none are in
the repository. A model with no privacy data is **denied**. Exit code 2 means no
acceptable model: tell the human, do not work around the policy.

## Delegating

```
offload delegate --task "<goal, files, definition of done>" [--role build] [--json]
```

Keep the task short; the executor reads the project itself. Pass `--scope <folder>` for a
task that belongs in one place: stray files elsewhere are discarded and reported. The tree must be clean
(commit or stash first). Work happens on a branch `offload/...`; your branch is never touched.

Read the verdict, then act on the exit code:

- **0** - the check passed. Review the diff (`git diff <base>..<branch>`), then
  `git merge <branch>` or `git branch -D <branch>`.
- **3** - the check failed or nothing changed. Send the executor a numbered list of
  discrepancies in a new task; do not explain basics.
- **4** - every model failed for infrastructure reasons. Retry later or write it yourself.
- **5** - the executor edited its own limits. Its work was discarded. Do not retry blindly.
- **2** - no acceptable model. Tell the human.

Install dependencies yourself before delegating: the executor is not allowed to.
Read-only roles (`explore`, `plan`, `review`) return a summary and need no branch or check.

## Protocol

Read `.offload/protocol.md`. In short: the task is goal, files, definition of done; the
executor answers DONE / VERIFIED / NOT DONE / DECISIONS / BLOCKERS. **Do not trust the
report**: run `verify` yourself.
