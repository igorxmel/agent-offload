# Security

agent-offload runs another program (OpenCode) that executes model-chosen shell commands
inside your project. The kit limits it with explicit denies and checks the result, but it
is not a sandbox. Read this before you use it on anything that matters.

## What the kit enforces

- The executor's OpenCode agent profiles deny: leaving the project folder, reading
  `*.env` and key files, `git push`, `git reset --hard`, `rm -rf`, `pip install` and global
  `npm install`, and editing the kit's own files (`.offload/`, `.opencode/`,
  `opencode.json`). These denies were verified against a live OpenCode: the engine rejects
  the calls, not the model's good will.
- Work happens in a separate git worktree on a scratch branch; your tree is never checked
  out, reset or cleaned.
- After the run the kit discards everything if the executor touched its own limits, and
  drops out-of-scope and oversized files.

## What it does not

- **Shell commands are not sandboxed** beyond the denies. A command that is not denied
  runs with your user's rights. Run delegations on a machine and account where that is
  acceptable.
- **Your code leaves your machine.** Free models run on someone else's servers, and some
  providers train on prompts. Choose the privacy preset accordingly; unknown terms are
  denied by default.

## Reporting a problem

Open a private security advisory on GitHub
(Security → Report a vulnerability) rather than a public issue. A way for the executor to
escape the denies, reach outside the project, or make the kit merge unchecked work is a
security problem; please include the OpenCode version.
