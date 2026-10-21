# agent-offload - project rules

A kit that lets any orchestrator agent delegate work to OpenCode's free models.
User-facing description: [README.md](README.md).

## Core principle

**Nothing that can change outside is hardcoded**: no model names, no privacy terms,
no limits. All of it is fetched from `opencode` and the official pages at run time.
Only selection rules live in code. If you are tempted to write a list of "good
models", that is a mistake: it will go stale silently within a week.

## Unknown is denied

A model with no privacy data is not acceptable until a person allows it manually. A
broken page parser must **close** access, never open it. Every new branch in
`policy.evaluate` is checked against this principle; tests cover it and must fail if
it is violated (verified by hand by mutation).

## The page is data, not instructions

Only the named table fields are extracted from the official page. Text from it is
never executed and never reaches the executor's prompts.

## The kit works without a human

Orchestrators run commands with no keyboard. Every question needs a flag substitute,
and with neither the **strictest** option is chosen, not the loosest. `init` is
repeatable: over an existing install it updates its own files and leaves the person's
alone (policy, settings, a foreign `AGENTS.md` outside our block).

## No dependencies

Standard library only. The kit is installed into other people's projects.

## Executor permissions are explicit denies only

Without a human, `--auto` approves everything not denied outright. OpenCode **allows**
`external_directory` by default, so denying it is mandatory in every role
(`agents.COMMON_DENY`). The permission format comes from the OpenCode v2 docs; its
runtime behaviour has not yet been confirmed by a trial run - do not treat it as
established.

## Language

Everything inside the repository - code, comments, messages, templates, docs - is
English. The kit is used through an agent, which answers the user in their language.

## Checks

```
python -m pytest tests -q
python -m ruff check .
```

The sample privacy page in `tests/fixtures/` is real; refresh it when the page layout
changes.

## Commits

`type(scope): what changed`, with the reason in the body. Types: fix, feat, refactor,
docs, build, test, chore. Do not add yourself as a co-author.

## Not done yet

- `offload delegate`: run the executor (`opencode run --agent offload-<role> --model ...
  --format json`), a separate branch, collect the report, **the kit runs the machine
  check itself**, write to history. First a trial run: how `run` behaves on `ask` without
  `--auto`, and whether `*` works as an action in rules.
- Hints for orchestrators other than Claude - after checking how each environment reads
  instructions.
