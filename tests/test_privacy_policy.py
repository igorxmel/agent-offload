"""Privacy page parsing and the policy.

The sample page is real, captured from the official site. What is checked is
where the kit could do harm: erring towards "allowed".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from offload import policy, privacy
from offload.privacy import Privacy

FIXTURE = Path(__file__).parent / "fixtures" / "privacy_table.html"


@pytest.fixture(scope="module")
def rows() -> dict[str, Privacy]:
    parsed = privacy.parse_page(FIXTURE.read_text(encoding="utf-8"))
    return {row.name: row for row in parsed}


def test_real_page_is_parsed_and_foreign_table_ignored(rows) -> None:
    assert len(rows) > 20
    assert "a" not in rows  # an unrelated table without the right headers


def test_training_and_retention_are_read_correctly(rows) -> None:
    assert rows["GLM-5.3-Flash"].trains is False
    assert rows["GLM-5.3-Flash"].retention_days == 0
    assert rows["Claude Haiku 5.5"].retention_days == 30
    assert rows["Gemini 4 Argon Contributor"].trains is True
    # "Not ZDR" is not zero days, it is the absence of a guarantee.
    assert rows["Gemini 4 Argon Contributor"].retention_days is None


def test_asterisk_does_not_break_retention() -> None:
    assert privacy.parse_retention("0 days*") == 0


def test_unrecognised_page_yields_nothing_not_everything() -> None:
    """Layout changed: no rows at all, not "everything allowed"."""
    assert privacy.parse_page("<html><table><tr><th>A</th><th>B</th></tr></table></html>") == []


def test_free_suffix_is_not_stripped_when_matching() -> None:
    """A free variant can have different terms than the paid one."""
    assert privacy.normalize("Beam Free") == privacy.normalize("beam-free")
    assert privacy.normalize("DeepSeek V4.1 Flash") != privacy.normalize("deepseek-v4.1-flash-free")


STRICT = policy.Policy.from_preset("strict")
PRIVATE = policy.Policy.from_preset("private")
OPEN = policy.Policy.from_preset("open")


def known(trains, days) -> Privacy:
    return Privacy("m", trains, days)


def test_unknown_model_is_denied_by_default() -> None:
    assert not policy.evaluate("opencode/new-model", None, STRICT).allowed
    assert not policy.evaluate("opencode/new-model", None, PRIVATE).allowed


def test_training_models_are_denied_unless_policy_allows() -> None:
    assert not policy.evaluate("x/m", known(True, None), PRIVATE).allowed
    assert policy.evaluate("x/m", known(True, None), OPEN).allowed


def test_retention_limit_is_enforced() -> None:
    assert policy.evaluate("x/m", known(False, 0), STRICT).allowed
    assert not policy.evaluate("x/m", known(False, 30), STRICT).allowed
    assert policy.evaluate("x/m", known(False, 30), PRIVATE).allowed
    assert not policy.evaluate("x/m", known(False, 31), PRIVATE).allowed


def test_unknown_retention_is_not_treated_as_zero() -> None:
    assert not policy.evaluate("x/m", known(False, None), STRICT).allowed


def test_manual_allow_and_deny_win() -> None:
    pol = policy.Policy.from_preset("strict")
    pol.allowed = ["nemotron-3-ultra-free"]
    assert policy.evaluate("opencode/nemotron-3-ultra-free", None, pol).allowed
    pol.denied = ["opencode/nemotron-3-ultra-free"]
    assert not policy.evaluate("opencode/nemotron-3-ultra-free", None, pol).allowed


def test_missing_policy_file_means_strictest(tmp_path) -> None:
    pol = policy.load(tmp_path)
    assert pol.allow_training is False and pol.max_retention_days == 0 and pol.require_known
