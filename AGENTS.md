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

## First real task (2026-10-24): porting `batfile.py` to Rust

A 286-line Python parser ported to a std-only Rust crate by `beam-free`, one attempt,
830 s, 154 agent steps. The kit's out-of-repo check (live Python parser as the reference,
156 cases: both fixture sets, three game-filter variants, re-encoded copies) said 156/156
and a second run on the built binary agreed. What the run taught:

- **A green check is not a clean result.** The executor also committed a hardcoded
  Visual Studio linker path, 2.5 MB of import libraries it generated itself (this machine
  has no Windows SDK) and a stray `test.obj` in the repo root, although the task said to
  touch nothing outside one folder. The code was honest (no shelling out to Python, no
  embedded answers); the environment workarounds were not mergeable. Always review the
  file list, not only the verdict.
- **The kit only guards its own files.** Nothing stopped changes outside the folder named
  in the task. `--scope PATH` now discards and reports out-of-scope changes. It runs
  after the tamper check on purpose, so discarding the kit's own files cannot hide an
  attempt to edit them.
- Keep the check **outside the repository**: the executor cannot read or edit it, and
  there are no stored answers to copy. Verified by self-test: an exact stand-in passes,
  one corrupted string is caught with the location.
- The free-model list churns: two acceptable models from the earlier trial were gone a
  few days later. Never rely on a model name seen once.

### Same task, second model (DeepSeek V4.1 Flash, free)

Rerun from a clean state with the same task, `--scope`, and the linker environment set
through variables outside the repository (nothing to improvise around):

| | beam-free | deepseek-v4.1-flash-free |
|---|---|---|
| wall time | 830 s | 367 s |
| agent steps | 154 | 39 |
| failed tool calls | 3 | 1 |
| fresh input / output / reasoning tokens | 320k / 28k / 21k | 87k / 15k / 26k |
| files committed | 27 (hacks, junk) | 4, all legitimate |
| own tests | 15 | 21 |
| check | 156/156 | 156/156 |

One run per model, one task: indicative, not a benchmark. What held up across both runs is
the method: an out-of-repo check against the live reference, a review of the file list,
and an environment prepared by the orchestrator. Most of beam-free's mess came from
improvising around a missing Windows SDK; once the linker was configured through
`CARGO_TARGET_*_LINKER` / `CARGO_ENCODED_RUSTFLAGS` there was nothing left to improvise.
The kit's history is per project, so these runs live in the experiment clone, not here.

### todo-sync experiment (2026-10-29)

A Rust + Kotlin/JVM to-do core with LAN sync, in `.experiments/todo-sync` (its own git
repository, ignored here). The orchestrator wrote the protocol, the visible vectors and 33
hidden ones (outside the repo, self-tested against wrong merges) before delegating.
`deepseek-v4.1-flash-free` did each core in one attempt (Rust 256 s, Kotlin 155 s), both
passed the hidden set, files stayed in scope. What it taught:

- **On Windows the check runs through `cmd.exe` from Python, and a bare `gradlew.bat` in
  the current folder is not found.** Write `.\gradlew.bat`. The Kotlin run was reported
  `failed` for this reason alone; the executor itself had used `.\gradlew.bat`.
- The environment is the orchestrator's job, as before: the Rust GNU toolchain (no Visual
  Studio needed) and a Gradle skeleton prepared up front left nothing to improvise.

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

- Real-world run of the retry path: a provider error (`provider.quota`, HTTP 402) was seen
  once in JSON mode; its shape in text mode is unknown, so today any non-zero exit, timeout
  or empty answer counts as an infrastructure failure and moves to the next model.
- Hints for orchestrators other than Claude - after checking how each environment reads
  instructions.
- The privacy table has no row for most `-free` variants (e.g. `deepseek-v4.1-flash-free`),
  so they are denied under every preset until allowed by hand. Decide whether a `-free`
  model may inherit the row of its paid sibling (the table's own footnotes suggest the
  terms can differ, so the current default is conservative on purpose).

## Handoff (state on 2026-10-24)

Written so a fresh session can continue without the conversation that produced this.

**What exists and works:** `init`, `models`, `pick`, `allow`, `deny`, `discover`,
`delegate` (with `--scope` and `--holdout`). 53 tests. Public repo, MIT, English only.
Verified against a live OpenCode v2.0.32 and on one real task (see above).

**Decisions already taken by the owner - do not reopen without asking:**
- The kit is orchestrator-agnostic: any agent that can run a shell command can drive it.
  OpenCode is the executor; free models only.
- The owner trusts DeepSeek V4.1 Flash for coding more than beam-free, and the single
  comparison agrees (see the table). Put it first through `prefer`/`--model`, after
  allowing it manually.
- The Rust port of the owner's main project (ZapretXmel) is **not** being pursued now.
  `batfile.py` was ported only as an experiment to measure the method. The owner asked to
  keep this repository focused on the kit.
- Privacy policy is the owner's call per project; never loosen it on your own.

**The experiment is archived, not in the repository:**
`.experiments/rust-batfile-experiment.zip` (gitignored, 25 KB): both Rust ports
(`deepseek/`, `beam-clean/`), the out-of-repo check `compare.py`, the task texts, the
linker environment `rustenv.sh` and both verdicts under `method/`, with a README inside.
The working folders `D:/Code/zx-offload-check` and `D:/Code/zx-rust-experiment` it came
from are not needed any more. Nothing from them was ever pushed. The lessons are recorded
in this file.

**Held-out check (`--holdout CMD`, done):** CLI flag only, never in config or the task file,
because the executor can read the repository. Runs only after the visible check is green;
a failure makes the verdict `failed`. Tried on 2026-10-29 against `deepseek-v4.1-flash-free`
on a throwaway repo (19 s): visible and held-out checks both passed, and the held-out test
path appeared nowhere in the executor's tree. Gotcha: pass the holdout path in the form the
check shell understands (a Git Bash `/tmp/...` path is not visible to Windows Python).

**Resume (`--resume BRANCH`, done):** `--task` holds the numbered discrepancies; the work goes on a
new `offload/...` branch cut from the earlier one, which is never touched. Only `offload/` branches
and writing roles are accepted. Tried on 2026-10-29 with `deepseek-v4.1-flash-free`: a held-out failure, then a resume with one
discrepancy produced a one-line diff on a new branch (30 s), the earlier branch stayed intact. The Windows
`init` noise (null device reported as a terminal) is fixed by asking the console API.

**Suggested next steps, none started:** hints for orchestrators other than Claude; per-user rather
than per-project model history (today a model's record starts from zero in every project).

**Working here:** run `python -m pytest tests -q` first. Edit files with the editor tool
rather than shell heredocs: `\n` inside a heredoc silently becomes a real newline and
broke three edits during the first session.
