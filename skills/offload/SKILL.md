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
task that belongs in one place: stray files elsewhere are discarded and reported. Pass
`--holdout "<cmd>"` with a check the executor must not know about (kept outside the repo);
never show its output to the executor. If the result is close but wrong, retry with
`--resume offload/<branch> --task "1. ... 2. ..."` (numbered discrepancies) instead of starting over. The tree must be clean
(commit or stash first). Work happens on a branch `offload/...` in a separate working copy
under `.offload/state/worktrees/`; your tree is never touched. Git-ignored files the build
needs (an SDK path in `local.properties`, say) go into `worktree_copy` in
`.offload/config.json`.

Put the task in a file and pass `--task-file`: a task with quotes or `$` passed as
`--task` on a command line gets mangled by the shell. `--json` goes before `delegate`.

## Saving time and your own tokens

Measured on one medium task (see AGENTS.md, "Measuring the saving"): delegating cut the
orchestrator's output 2.6x but its total cost only ~20%, because every turn spent waiting
or reviewing re-reads the whole session. So:

- **Run independent tasks at the same time.** Each delegation takes its own working
  copy, so start them as separate background commands (one per `--scope`, e.g. `rust`
  and `kotlin`) and handle each verdict when it arrives. Do not poll in between.
- **Fewer, larger tasks.** Each delegation costs you a few turns of reading; six small
  ones cost more than three larger ones.
- **Let a free model do the first review:**
  `offload delegate --role review --on offload/<branch> --task-file <what the change was for>`.
  It reads the diff in its own working copy and returns findings; you read the findings
  and spot-check, instead of reading the whole diff. Hidden checks (`--holdout`) remain
  the real safety net.
- **Put what you would catch in review into the visible check.** A bug the check catches
  is fixed by the executor in the same run; a bug only you catch costs a `--resume` round.
- **A cheaper orchestrator for the loop.** Writing the spec and the hidden checks needs a
  strong model; delegating, reading verdicts and merging does not. If your environment
  lets you choose, run that loop in a short session on a cheaper model.

Read the verdict, then act on the exit code:

- **0** - the check passed. Review the diff (`git diff <base>..<branch>`), then
  `git merge <branch>` or `git branch -D <branch>`.
- **3** - the check failed or nothing changed. Send the executor a numbered list of
  discrepancies in a new task; do not explain basics.
- **4** - every model failed for infrastructure reasons. With status `quota` the free
  quota is used up: say so to the human (another provider can be connected) instead of
  retrying. Otherwise retry later or write it yourself.
- **5** - the executor edited its own limits. Its work was discarded. Do not retry blindly.
- **2** - no acceptable model. Tell the human.

Install dependencies yourself before delegating: the executor is not allowed to.
Read-only roles (`explore`, `plan`, `review`) return a summary and need no branch or check.

## Protocol

Read `.offload/protocol.md`. In short: the task is goal, files, definition of done; the
executor answers DONE / VERIFIED / NOT DONE / DECISIONS / BLOCKERS. **Do not trust the
report**: run `verify` yourself.
