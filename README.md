# agent-offload

Hand bulk work to [OpenCode](https://opencode.ai)'s free models, and leave your main
agent - Claude, Codex, Antigravity, anything - only the goal, a short verdict and the
check. Expensive tokens go to decisions, not to typing.

> **Status: early but working end to end.** `init`, acceptable-model discovery, selection
> and `delegate` are done and have been run against real models.

## The easy way to use it

You do not need to learn the commands. Give this repository to your agent and say:

> Install agent-offload and run `offload init` in this project.

Then it can delegate on its own. The commands below are what it calls.

## How it works

The orchestrator needs one ability - run a shell command - so the kit is not tied to a
particular agent. Everything shared lives in neutral files (`AGENTS.md`, `.offload/`),
and `skills/offload/SKILL.md` is a hint for environments that read skills.

```
offload init                       set the kit up in a project
offload models [--allowed]         models, and whether the policy allows them
offload pick --role build -v       choose a model
offload allow|deny <model>         manual exception
offload discover                   refresh data from the official pages
offload delegate --task "..."      hand a task over, get a verdict
```

`delegate` works on a scratch branch `offload/...` and never touches your tree. It picks an
acceptable model, runs the executor, then **runs your check command itself** and returns a
short verdict: model, changed files, diffstat and what the check actually printed. If a
model fails for infrastructure reasons (timeout, provider error, empty answer) it tries the
next acceptable one. A failed *check* is not retried: that is a quality verdict, and it
goes to you. If the executor edits its own limits, all its work is discarded. With
`--scope PATH` (repeatable, or `scope` in `.offload/config.json`) anything the executor
changed outside those folders is discarded and reported: a green check says nothing about
files the task never named. With `--holdout CMD` the kit runs a second check the executor
never saw (after the visible one passes); if it fails, the verdict is `failed`. Pass it on
the command line only: a config file would be readable by the executor.
To fix a failed result, run `--resume offload/<branch>` with a numbered list of discrepancies
as the task: the earlier branch stays as it is and the fix goes on a new one.

| Exit | Meaning |
|---|---|
| 0 | check passed |
| 2 | no acceptable model |
| 3 | check failed, or nothing changed |
| 4 | every executor attempt failed |
| 5 | the executor touched its own limits |

Roles: `build` (writes), and read-only `explore`, `plan`, `review` that return a summary,
a plan or a review without a branch or a check.

Every command has `--json` for machine parsing.

## Nothing is hardcoded

The repository contains no model name and no verdict about one. The model list comes
from `opencode` itself, data-handling terms from the official page, and the result is
cached for a day. The choice among acceptable models is based on **your own runs**:
popularity rankings do not show quality, and other people's benchmarks measure other
people's tasks. Until there are runs the choice is honestly labelled a guess
(`basis: guess`).

## Privacy

Free models run on someone else's servers: your code **leaves your machine**, and for
some models prompts are used for training. So `init` asks what kind of code this is:

| Preset | What it allows |
|---|---|
| `strict` | no training, no retention of prompts |
| `private` | no training, retention up to 30 days |
| `open` | anything, including models that train on prompts |

Without a human (an orchestrator ran `init` itself) `strict` is chosen. The core rule:
**unknown is denied.** A model with no privacy data is not allowed until you allow it
manually - otherwise a broken page parser would silently open access to everything.

Agent profiles forbid the executor from leaving the project folder (OpenCode **allows**
it by default), reading `*.env` and keys, `git push`, installing packages, and editing its
own limits (`.offload/`, `.opencode/`). The denies are explicit:
without a human the `--auto` flag approves everything not denied outright.

## Install

```
pip install .        # or run in place: python -m offload ...
```

No dependencies: the kit is installed into other people's projects, and pulling extras
into them would be rude. Needs `opencode` on `PATH` and Python 3.10+.

## Honest note on savings

The gain grows with task size and shrinks with a weak check. Do not delegate small
things or anything you cannot verify: reviewing a weak model's bad code costs more than
writing it yourself. Without a check command (`verify`) the kit refuses to delegate.

License: MIT.
