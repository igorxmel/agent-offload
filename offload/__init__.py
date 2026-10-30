"""agent-offload: hand bulk work to OpenCode's free models.

The orchestrator (Claude, Codex, Antigravity - anything that can run a shell
command) sets the goal; the executor writes the code. What comes back to the
orchestrator is a short verdict from a machine check, not two hundred lines.
"""

__version__ = "0.2.0"
