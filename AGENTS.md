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
(`agents.COMMON_DENY`). Confirmed by trial, see the next section.

## Verified behaviour of `opencode run` (v2.0.32, trial on 2026-10-21)

Facts, each observed rather than read in the docs. Re-verify after an OpenCode upgrade.

- **Denies are enforced by the engine, not by the model's good will.** An agent with our
  `COMMON_DENY` got `permission.rejected` for `read ../outside/secret.txt`
  (`external_directory`), `read .env` and `git push` (`shell`); no secret leaked.
- **Without our denies the leak is real.** The built-in `build` agent with `--auto` read a
  file outside the project and printed it. The mandatory denies are not superstition.
- **Do not trust a refusal as evidence.** The first trial looked safe because the model
  declined, citing `.offload/protocol.md`. That was the model complying, not the permission
  system. Test enforcement with an agent whose prompt has no such rules.
- **`--format json` hangs when the agent uses file tools.** Plain prompts work in JSON
  mode; reading a file does not return (killed by timeout, zero bytes of output).
  Plain text output with `--auto` works. `delegate` must use text output and parse the
  fixed report format (`DONE/VERIFIED/...`) itself.
- `--standalone` is **not** required: text mode works without it in about 7 seconds. It is
  only a way to keep the run off the shared background service.
- Free models fail in ways a delegating tool must survive: one returned
  `provider.quota` / HTTP 402 "Endpoint is unavailable" immediately.
- The build agent followed the report format and reported honestly what it refused.
- **Side effect to decide on:** the executor ran `python -m pip install pytest`, changing
  the interpreter environment outside the project files. Shell is not sandboxed beyond the
  denies. Consider denying `pip install *` / global installs, or require a project venv.

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

- `offload delegate`: run the executor in **text mode** (`opencode run --auto --agent
  offload-<role> --model ...`), a separate git branch, parse the report, **the kit runs the
  machine check itself**, write to history, survive provider errors by trying the next
  acceptable model.
- Decide on the pip-install side effect above.
- Hints for orchestrators other than Claude - after checking how each environment reads
  instructions.
