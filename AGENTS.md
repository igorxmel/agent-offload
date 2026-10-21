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
- **Side effect, now closed:** the executor once ran `python -m pip install pytest`, changing
  the interpreter outside the project files. `COMMON_DENY` now blocks pip and global npm
  installs. Confirmed by a second trial: `pip install`, editing `.opencode/agents/*` and
  writing `opencode.json` all came back `permission.rejected`, files intact. Shell is still
  not sandboxed beyond the denies.
- **The task travels as an attached file** (`--file`), with a fixed safe message. On Windows
  `opencode` is an npm `.cmd` shim, so a free-form argument passes through `cmd.exe`, which
  treats `&`, `|`, `%`, `^` as syntax even inside quotes.
- End-to-end run of `delegate` against a real model: 20 s, branch created, check run by the
  kit, original branch and tree untouched. Models write a bare `DONE` header without a colon;
  the report parser accepts it.

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

- A held-out check: the executor sees the check command, so it can fit code to it. The
  kit already runs the check itself; running a *second* command the executor never saw
  (`verify_holdout`) would close the gap.
- A way to continue a failed delegation with a numbered list of discrepancies.
- Real-world run of the retry path: a provider error (`provider.quota`, HTTP 402) was seen
  once in JSON mode; its shape in text mode is unknown, so today any non-zero exit, timeout
  or empty answer counts as an infrastructure failure and moves to the next model.
- Hints for orchestrators other than Claude - after checking how each environment reads
  instructions.
