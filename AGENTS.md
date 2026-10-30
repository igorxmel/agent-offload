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
- **OpenCode takes the project folder from `PWD`, not from the process's working directory**
  (2026-10-30). Started with `cwd=project` from a Git Bash whose `PWD` pointed elsewhere, the
  executor ran `cd` and got the caller's folder - so every deny rule applied to the wrong
  tree. `opencode.agent_env` sets `PWD` to the project for every run; a test guards it.
- **Steps stream on stderr as they happen** (`Read PROTOCOL.md` 1.3 s into a run), the final
  answer on stdout. Silence on both means the provider stopped answering: the stall
  detector (`stall_timeout`) relies on this.

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
- Network nodes (UDP discovery + TCP sync) went the same way: Rust 356 s, Kotlin 300 s, one
  attempt each, and every hidden interop scenario passed in all three pairings
  (rust-kotlin, kotlin-rust, kotlin-kotlin). The interop check starts real processes on
  loopback and compares their store files.
- **Self-test the check on a reference first.** Running the hidden scenarios against a
  Python reference node found two gaps in the spec (which address to connect back to; the
  Windows UDP `WSAECONNRESET` after sending to a closed port) before any executor saw it,
  and two deliberately broken nodes confirmed the hidden set catches what the visible one
  misses.
- Nodes in tests must announce to loopback only: a node with no announce address falls
  back to broadcast on the real network, which can raise a Windows Firewall prompt.
- Every orchestrator mistake in this run was in the check command, not the code (a bare
  `gradlew.bat`, backslashes eaten by a Python string). Run the check by hand once before
  delegating.
- The Windows GUI (egui, glow backend; needs mingw-w64 on PATH for the GNU toolchain) passed
  every machine check, the app running as a sync peer, yet a screenshot showed three bugs
  no check could see: a device count that included itself, an invisible input field, a
  delete glyph the font lacks. **For a UI, look at it.** The fixes went back as a numbered
  list and came back passing; the one-character glyph fix was cheaper to do by hand.
- Stop demo processes by PID or path, never by image name: `node.exe` is also Node.js.

### Providers beyond OpenCode Zen (2026-10-29/30)

The executor is OpenCode; the provider only supplies the model, so any provider OpenCode
connects to can be tried with the same denies, checks and branches.

- **The free quota covers all models at once, and for Zen it is most likely per IP.**
  Nine delegations (~60 min of executor time) fit into OpenCode Zen's free quota; then
  `beam-free` stopped mid-task with "Free usage limit reached" and every other free model
  refused within seconds. It came back hours later, for one request. Zen was used without
  any login (`opencode auth list` was empty), so the limit cannot be per account: a friend
  behind the same VPN exit hit it at once without using OpenCode. Everyone sharing an
  exit IP shares the quota; the kit's runs use it up for them too. OpenRouter's free tier ended the same way ("Rate limit exceeded:
  free-models-per-day"), Google AI Studio's Pro model had none ("exceeded your current
  quota").
- **Groq's free tier cannot drive an agent.** One-file probes passed, but the first real
  request was 8562 input tokens against a 7000 tokens-per-minute limit: OpenCode's system
  prompt and tool definitions alone come close to that. `gpt-oss-120b` also called a tool
  `exec` that does not exist (from its own training harness). For an agent the limit that
  matters is tokens per minute per request, not requests per day.
- **OpenRouter's `:free` models can.** `thinkingmachines/inkling:free` built the Android app
  (24 min) and both halves of a protocol fix (18 and 14 min), passing every hidden check.
  `nvidia/nemotron-3-ultra-550b-a55b:free` worked for 12 minutes and then stopped answering
  until the 30-minute timeout threw the work away. `gemini-3.8-flash` was right but slow
  (222 s for a two-file question).
- **Probe with a real agent step, not a one-line prompt.** A read-only `offload-explore` run
  on the actual repository with a question that needs two files separates working models
  from broken ones in seconds; a one-line prompt passed models that then failed every real
  request.
- Inkling committed a 380 MB JVM heap dump with its work; it was merged by hand without it.
- **Real hardware found what loopback could not.** On real Wi-Fi (Windows PC + Android 15
  phone) data synced both ways, but only the PC saw the phone: Windows sends a limited
  broadcast through one adapter, here a virtual one (VirtualBox/Docker/WSL). The fix went
  into the spec first (reply to a hello by unicast), then into a loopback scenario that
  reproduces the one-way case, self-tested on the reference, then delegated. Afterwards a
  change crossed in under a second from phone to PC and in about two seconds back.

What the kit learned from this is now code (see "Guards" below).

## Guards (2026-10-30)

Each closes a way the kit went wrong on real providers; `tests/test_guards.py` covers them
and every one was checked by mutation.

- **Price** (`catalog`): prices come from the public catalog OpenCode is built on
  (models.dev). Only a listed price of zero is accepted; unknown is denied. Without this,
  connecting OpenRouter put 358 paid models (Claude among them) next to 23 free ones in the
  acceptable list. A free-tier key (Groq, Google) is not billed although a price is listed:
  the person allows the provider with `offload allow groq/*`.
- **Tool use** (`catalog`): a model the catalog marks as unable to call tools is denied,
  unknown included. Music and moderation models are free and would otherwise be tried
  first while there is no history.
- **Quota** (`quota`): known provider messages mark the provider exhausted for
  `quota_cooldown_hours` (1 h); its other models are skipped, not tried and refused. The
  stop is recorded but not held against the model. All attempts stopped by quota give the
  status `quota` (exit 4).
- **Stall** (`opencode.run_agent`): `stall_timeout` (600 s) without a byte on stdout or
  stderr kills the run and moves on.
- **File size** (`delegate`): files above `max_file_kb` (5 MB) are discarded and reported.
- **`PWD`**: see "Verified behaviour" above.
- An explicit `--model` missing from the cached snapshot (a provider connected after the
  last `discover`) triggers one refresh instead of "unknown model".
- **Executor usage**: `opencode stats --project . --all --json` before and after a
  delegation; the difference (steps, tokens, cost) goes into the verdict and the history.
  Unreadable or shrinking totals give "unknown", never a guess. Two delegations running in
  one project at once would share the difference.

- **Working copies (`slots`)**: every writing delegation runs in its own git worktree
  `.offload/state/worktrees/slot-N`, so the person's tree is never checked out and
  delegations run in parallel. Slots are reused so ignored build output stays warm;
  `checkout -f` + `clean -fd` (no `-x`) reset everything else. A lock file per slot, taken
  over when older than the longest possible run. `worktree_copy` copies git-ignored files a
  build needs (an Android `local.properties`). Read-only roles with `--on BRANCH` look at a
  branch in a detached slot: that is how a free model does the first review. Live on
  2026-10-30: a Kotlin and a Rust task ran in two slots at once (4 and 3 minutes), the main
  tree stayed clean throughout.

## Measuring the saving

The orchestrator's side cannot be read by the kit (any orchestrator may drive it). For
Claude Code it is in the session transcript, `~/.claude/projects/<dir>/<session>.jsonl`:
each response carries `usage` (input, cache write, cache read, output); count each message
id once. Over the whole todo-sync experiment (2026-10-29/30) the orchestrator spent 228k
output tokens and 101M cache reads in 336 responses, the executors 155k output + 170k
reasoning tokens and 39M cache reads in 769 steps. That run is not a fair measure: it
included toolchain setup and provider research, and most of the orchestrator's cost was
re-reading a long session context. A fair one is an A/B on one task in fresh sessions:
the orchestrator alone versus the orchestrator with the kit.

### First A/B (2026-10-30): due dates across Rust, Kotlin, egui and Compose

One task (PROTOCOL.md 1.1: optional `due`, sixth merge key, list order with a runner, UI in
both apps), one start commit, warm builds, two fresh scheduled sessions on the same model
(Opus 5.5). Arm A worked alone; arm B delegated through the kit to
`openrouter/thinkingmachines/inkling:free`.

| | A: alone | B: through the kit |
|---|---|---|
| wall time | 13 min | 96 min (6 delegations, run one after another) |
| orchestrator output tokens | 44.2k | 17.1k |
| orchestrator cache write / cache read | 137k / 3.81M | 102k / 4.08M |
| executor | - | 505 steps, 593k in / 56k out / 47k reasoning, 33.5M cache reads, $0 |
| hidden checks (71 vectors x 2 languages, 30 interop runs) | all pass | all pass |

Weighted by list price (output 5x input, cache write ~2x, cache read 0.1x), B cost the
orchestrator about **20% less** than A, at about **7x the wall time**. Output fell 2.6x,
but reading the session context back on every turn did not shrink: B's session lived
longer and re-read about as much. Two of B's four first delegations had real bugs the
visible checks missed (merge key order, "today" in UTC, no way to give a task a due date);
the orchestrator found them by reading the diffs and fixed each with one `--resume`.

What this says: on a medium task the saving is real but modest, and paid for in time. It
grows with the size of the implementation relative to the orchestrator's reading and
review, and it is eaten by every extra turn the orchestrator spends waiting or reviewing.
One run per arm: indicative, not a benchmark.

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

- Partial work is thrown away on a timeout or a stall. Nemotron's 12 useful minutes were
  lost that way; keeping such work on a branch marked unverified might be worth it.
- Model choice without history is a guess in catalog order. The catalog also has context
  size and release date, which could order the guesses without naming any model.
- Hints for orchestrators other than Claude - after checking how each environment reads
  instructions.
- Per-user rather than per-project model history: today a model's record starts from zero
  in every project.
- The privacy table has no row for most `-free` variants (e.g. `deepseek-v4.1-flash-free`),
  so they are denied under every preset until allowed by hand. Decide whether a `-free`
  model may inherit the row of its paid sibling (the table's own footnotes suggest the
  terms can differ, so the current default is conservative on purpose).

## Handoff (state on 2026-10-30)

Written so a fresh session can continue without the conversation that produced this.

**What exists and works:** `init`, `models`, `pick`, `allow`, `deny` (also `provider/*`),
`discover`, `delegate` (with `--scope`, `--holdout`, `--resume`), and the guards above.
72 tests. Public repo, MIT, English only. Verified against a live OpenCode v2.0.32, on the
`batfile.py` port and on the todo-sync experiment (about fifteen delegations).

**Decisions already taken by the owner - do not reopen without asking:**
- The kit is orchestrator-agnostic: any agent that can run a shell command can drive it.
  OpenCode is the executor. Models must be free; any provider OpenCode connects to may
  supply them (decided 2026-10-30 after the Zen quota ran out).
- The owner trusts DeepSeek V4.1 Flash for coding more than beam-free, and the single
  comparison agrees (see the table). Put it first through `prefer`/`--model`, after
  allowing it manually.
- The Rust port of the owner's main project (ZapretXmel) is **not** being pursued now.
  `batfile.py` was ported only as an experiment to measure the method. The owner asked to
  keep this repository focused on the kit.
- Privacy policy is the owner's call per project; never loosen it on your own.

**Experiments, not in the repository:**
- `.experiments/rust-batfile-experiment.zip` (gitignored, 25 KB): both Rust ports, the
  out-of-repo check, task texts, the linker environment and both verdicts, with a README.
- `.experiments/todo-sync` (gitignored, its own git repository): the Rust + Kotlin to-do
  app with LAN sync, Windows (egui) and Android (Compose) apps. Its hidden checks,
  reference node and task texts live in `D:/Code/todo-sync-check`, outside every
  repository on purpose.

**Machine setup used by the experiments** (not needed by the kit): Rust GNU toolchain,
mingw-w64 (scoop) on PATH for GUI crates, Gradle in `%LOCALAPPDATA%/gradle-dist`,
Android command-line tools (scoop `android-clt`, licenses accepted by the owner).
OpenCode has Groq, Google and OpenRouter keys connected.

**Held-out check (`--holdout CMD`):** CLI flag only, never in config or the task file,
because the executor can read the repository. Runs only after the visible check is green;
a failure makes the verdict `failed`. Pass the path in the form the check shell
understands (a Git Bash `/tmp/...` path is not visible to Windows Python).

**Resume (`--resume BRANCH`):** `--task` holds the numbered discrepancies; the work goes on
a new `offload/...` branch cut from the earlier one, which is never touched.

**Working here:** run `python -m pytest tests -q` first. Edit files with the editor tool
rather than shell heredocs or `sed`: `\n` inside a heredoc silently becomes a real newline,
and a backslash in `sed` or a Python string gets eaten. Both broke edits again during the
todo-sync experiment, in JSON config and task files.
