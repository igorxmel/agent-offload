# Changelog

## 0.2.0 - 2026-10-30

Everything here came out of running the kit on real work: a Rust + Kotlin to-do app with
LAN sync, a Windows app and an Android app, built by free models behind hidden checks.
[AGENTS.md](AGENTS.md) has the full story of each change.

### Added
- **Parallel delegations.** Every writing delegation runs in its own git worktree slot
  (`.offload/state/worktrees/slot-N`); the person's tree is never checked out. Slots are
  reused, so build output stays warm. `worktree_copy` brings in git-ignored files a build
  needs.
- **Free first review:** `--role review --on <branch>` looks at a branch in a detached
  slot and returns findings.
- `--holdout CMD`: a second check the executor never sees.
- `--resume BRANCH`: continue a failed delegation with a numbered list of discrepancies.
- **Price and tool-use filter** from the models.dev catalog: only models with a listed
  price of zero that can call tools; `offload allow <provider>/*` for free-tier keys.
- **Quota handling:** provider quota messages (OpenCode Zen, OpenRouter, Google) mark the
  provider exhausted for an hour; status `quota` when every attempt hit one.
- **Stall detector:** `stall_timeout` kills an executor that prints nothing for too long.
- **Unverified work is kept** on `<branch>-partial-N` after a timeout, stall or quota stop.
- `max_file_kb`: oversized files (heap dumps) are discarded.
- Executor usage (steps, tokens, cost) in every verdict and in the history.
- Untried models are ordered by catalog facts (context size, release date), not by list
  order.

### Fixed
- The executor ran in the caller's folder when the shell exported `PWD`; it is now always
  the project.
- `offload init` printed a privacy question with stdin closed on Windows.
- An explicit `--model` from a newly connected provider was refused until a manual
  `discover`.

## 0.1.0 - 2026-10-24

First working version: `init`, `models`, `pick`, `allow`, `deny`, `discover`, `delegate`
with `--scope`, privacy presets, explicit-deny agent profiles.
