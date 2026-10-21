# agent-offload

Hand bulk work to [OpenCode](https://opencode.ai)'s free models, and leave your main
agent - Claude, Codex, Antigravity, anything - only the goal, a short verdict and the
check. Expensive tokens go to decisions, not to typing.

> **Status: early.** `init`, acceptable-model discovery and selection are done.
> `offload delegate` (run the executor, branch, machine check, compressed verdict)
> is the next step.

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
```

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
it by default), reading `*.env` and keys, and `git push`. The denies are explicit:
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
