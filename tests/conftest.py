"""Shared test setup: no test reaches a real `opencode` by accident."""

from __future__ import annotations

import pytest

from offload import opencode


@pytest.fixture(autouse=True)
def no_real_usage(monkeypatch):
    """Delegation reads OpenCode's statistics before and after a run. Tests that
    care pass their own reader; the rest must not depend on what is installed."""
    monkeypatch.setattr(opencode, "usage", lambda root: None)
