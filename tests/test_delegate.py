"""`delegate` end to end, with a fake executor on a real temporary git repository.

The dangerous parts are checked first: that a failed attempt leaves no trace,
that the person's own branch and uncommitted work are never touched, and that an
executor rewriting its own limits is caught.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from offload import config, delegate, discover, gitops, history, init, paths, policy, report
from offload.opencode import AgentResult

GOOD_REPORT = (
    "DONE:       new.txt - created\n"
    "VERIFIED:   git ls-files -> new.txt\n"
    "NOT DONE:   none\nDECISIONS:  none\nBLOCKERS:   none\n"
)
VERIFY_NEW = "git ls-files --error-unmatch new.txt"


def make_repo(tmp_path: Path, verify: str = VERIFY_NEW) -> Path:
    gitops.git(tmp_path, "init", "-q", "-b", "main")
    gitops.git(tmp_path, "config", "user.name", "t")
    gitops.git(tmp_path, "config", "user.email", "t@t")
    gitops.git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    init.init(tmp_path, privacy="open", verify=verify, interactive=False)
    gitops.git(tmp_path, "add", "-A")
    gitops.git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def snapshot(*models: str, denied: tuple[str, ...] = ()) -> discover.Snapshot:
    entries = [discover.Entry(m, None, True, "ok") for m in models]
    entries += [discover.Entry(m, None, False, "denied in test") for m in denied]
    return discover.Snapshot(fetched_at=0, entries=entries)


def result(out: str = GOOD_REPORT, code: int = 0, timed_out: bool = False) -> AgentResult:
    return AgentResult(code, out, "", 1.0, timed_out)


def writer(files: dict[str, str], out: str = GOOD_REPORT):
    """A fake executor that writes files into the project and reports."""

    def run(root, agent, model, message, task_file, timeout):
        for name, text in files.items():
            target = Path(root) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return result(out)

    return run


def branches(root: Path) -> list[str]:
    return gitops.git(root, "branch", "--format=%(refname:short)").split()


def test_passed_flow_keeps_work_on_a_branch_and_restores_the_original(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root, "create new.txt", snapshot=snapshot("p/m1"), executor=writer({"new.txt": "x\n"})
    )
    assert verdict.status == "passed" and verdict.exit_code == 0
    assert verdict.model == "p/m1" and verdict.files == ["new.txt"]
    assert verdict.verify["exit_code"] == 0
    assert verdict.branch in branches(root)
    assert gitops.current_ref(root) == "main"
    assert not (root / "new.txt").exists()  # the person's tree is untouched
    assert history.stats(root)["p/m1"].passed == 1


def test_failed_check_is_reported_and_the_branch_kept_for_inspection(tmp_path) -> None:
    root = make_repo(tmp_path, verify="git ls-files --error-unmatch missing.txt")
    verdict = delegate.delegate(
        root, "do it", snapshot=snapshot("p/m1"), executor=writer({"new.txt": "x\n"})
    )
    assert verdict.status == "failed" and verdict.exit_code == 3
    assert verdict.branch in branches(root)
    assert history.stats(root)["p/m1"].passed == 0


def test_infrastructure_failure_falls_through_to_the_next_model(tmp_path) -> None:
    root = make_repo(tmp_path)
    calls = []

    def flaky(root_, agent, model, message, task_file, timeout):
        calls.append(model)
        if model == "p/m1":
            # Leaves junk behind and then fails: the next attempt must not see it.
            (Path(root_) / "junk.txt").write_text("junk", encoding="utf-8")
            return result("", code=1)
        (Path(root_) / "new.txt").write_text("x\n", encoding="utf-8")
        return result()

    verdict = delegate.delegate(
        root, "create new.txt", snapshot=snapshot("p/m1", "p/m2"), executor=flaky
    )
    assert calls == ["p/m1", "p/m2"]
    assert verdict.status == "passed" and verdict.model == "p/m2"
    assert verdict.files == ["new.txt"]  # junk.txt from the failed attempt is gone
    assert [a.outcome for a in verdict.attempts] == ["error", "ok"]
    assert history.stats(root)["p/m1"].passed == 0


def test_all_attempts_failing_deletes_the_branch_and_restores_origin(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root, "x", snapshot=snapshot("p/m1", "p/m2"),
        executor=lambda *a: result("", timed_out=True, code=1),
    )
    assert verdict.status == "executor_error" and verdict.exit_code == 4
    assert [b for b in branches(root) if b.startswith("offload/")] == []
    assert gitops.current_ref(root) == "main"


def test_executor_editing_its_own_limits_is_caught_and_discarded(tmp_path) -> None:
    root = make_repo(tmp_path)
    cage = ".opencode/agents/offload-build.md"
    verdict = delegate.delegate(
        root, "x", snapshot=snapshot("p/m1"),
        executor=writer({cage: "permissions: []\n", "new.txt": "x\n"}),
    )
    assert verdict.status == "tampered" and verdict.exit_code == 5
    assert [b for b in branches(root) if b.startswith("offload/")] == []
    original = (root / cage).read_text(encoding="utf-8")
    assert "external_directory" in original  # the real file was never touched


def test_no_changes_is_its_own_status(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root, "x", snapshot=snapshot("p/m1"), executor=lambda *a: result()
    )
    assert verdict.status == "no_changes"
    assert [b for b in branches(root) if b.startswith("offload/")] == []


def test_dirty_tree_is_refused_before_anything_runs(tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / "mine.txt").write_text("my work", encoding="utf-8")
    ran = []
    with pytest.raises(delegate.DelegateError, match="uncommitted"):
        delegate.delegate(
            root, "x", snapshot=snapshot("p/m1"), executor=lambda *a: ran.append(1) or result()
        )
    assert ran == []


def test_missing_check_command_is_refused(tmp_path) -> None:
    root = make_repo(tmp_path, verify="")
    cfg = config.load(root)
    cfg.verify = ""
    config.save(root, cfg)
    with pytest.raises(delegate.DelegateError, match="no check command"):
        delegate.delegate(root, "x", snapshot=snapshot("p/m1"), executor=lambda *a: result())


def test_forced_model_must_be_acceptable(tmp_path) -> None:
    root = make_repo(tmp_path)
    with pytest.raises(delegate.DelegateError) as error:
        delegate.delegate(
            root, "x", model="p/bad", snapshot=snapshot("p/m1", denied=("p/bad",)),
            executor=lambda *a: result(),
        )
    assert error.value.code == 2 and "denied in test" in str(error.value)


def test_no_acceptable_model_exits_with_code_two(tmp_path) -> None:
    root = make_repo(tmp_path)
    with pytest.raises(delegate.DelegateError) as error:
        delegate.delegate(root, "x", snapshot=snapshot(denied=("p/bad",)),
                          executor=lambda *a: result())
    assert error.value.code == 2


def test_read_only_role_never_resets_the_persons_branch(tmp_path) -> None:
    """A hard reset on the person's own branch would destroy uncommitted work."""
    root = make_repo(tmp_path)
    (root / "base.txt").write_text("my uncommitted edit\n", encoding="utf-8")

    # A read-only role that fails and one that (wrongly) writes: neither may reset.
    delegate.delegate(
        root, "explain", role="explore", snapshot=snapshot("p/m1", "p/m2"),
        executor=lambda *a: result("", code=1),
    )
    verdict = delegate.delegate(
        root, "explain", role="explore", snapshot=snapshot("p/m1"),
        executor=writer({"stray.txt": "x"}, out="DONE: x\nVERIFIED: none\n"),
    )
    assert (root / "base.txt").read_text(encoding="utf-8") == "my uncommitted edit\n"
    assert (root / "stray.txt").exists()  # left for the person, not deleted
    assert verdict.status == "failed" and any("read-only" in n for n in verdict.notes)


def test_executor_state_files_do_not_ride_into_the_commit(tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / ".gitignore").write_text("", encoding="utf-8")  # no ignore for .offload/state
    gitops.git(root, "add", "-A")
    gitops.git(root, "commit", "-q", "-m", "drop ignore")
    verdict = delegate.delegate(
        root, "create new.txt", snapshot=snapshot("p/m1"), executor=writer({"new.txt": "x\n"})
    )
    tracked = gitops.git(root, "ls-tree", "-r", "--name-only", verdict.branch).split()
    assert not any(p.startswith(".offload/state/") for p in tracked)


def test_unformatted_report_is_flagged_not_trusted(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root, "x", snapshot=snapshot("p/m1"),
        executor=writer({"new.txt": "x\n"}, out="All done, everything works great!"),
    )
    assert verdict.report_ok is False and "RAW" in verdict.report
    assert any("report format" in n for n in verdict.notes)


# --- report parsing -------------------------------------------------------


def test_report_parser_joins_repeated_headers_and_strips_markdown() -> None:
    text = (
        "\x1b[1mDONE:\x1b[0m a.py - added\nDONE: b.py - changed\n"
        "**VERIFIED:** pytest -> 2 passed\n- NOT DONE: nothing\nBLOCKERS: none"
    )
    parsed = report.parse(text)
    assert parsed["DONE"] == "a.py - added\nb.py - changed"
    assert "2 passed" in parsed["VERIFIED"] and parsed["BLOCKERS"] == "none"
    assert report.is_well_formed(parsed)


def test_report_parser_does_not_invent_missing_sections() -> None:
    parsed = report.parse("Some text with no structure at all.")
    assert parsed == {} and not report.is_well_formed(parsed)


def test_policy_module_is_untouched_by_delegation(tmp_path) -> None:
    """The policy the person set must survive a delegation run unchanged."""
    root = make_repo(tmp_path)
    before = paths.policy_file(root).read_text(encoding="utf-8")
    delegate.delegate(root, "x", snapshot=snapshot("p/m1"), executor=lambda *a: result())
    assert paths.policy_file(root).read_text(encoding="utf-8") == before
    assert policy.load(root).allow_training is True


def test_git_binary_is_available() -> None:
    assert subprocess.run(["git", "--version"], capture_output=True, check=False).returncode == 0


def test_report_parser_accepts_a_bare_header_without_a_colon() -> None:
    """Seen from a real model: `DONE`, a blank line, then the body."""
    parsed = report.parse(
        "DONE\n\ncalc.py - added add()\n\nVERIFIED: `pytest` -> 2 passed\n\nDECISIONS: none"
    )
    assert parsed["DONE"] == "calc.py - added add()"
    assert report.is_well_formed(parsed)
    # A header word inside a sentence is not a header.
    assert report.parse("We are DONE with this and VERIFIED nothing.") == {}


# --- scope ---------------------------------------------------------------


def test_scope_discards_stray_files_but_keeps_the_work(tmp_path) -> None:
    """The first real run left a stray test.obj in the repo root; a green check said nothing."""
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root,
        "x",
        scope=["work"],
        snapshot=snapshot("p/m1"),
        executor=writer(
            {"work/new.txt": "x\n", "test.obj": "junk", "base.txt": "edited outside scope\n"}
        ),
        verify_cmd="git ls-files --error-unmatch work/new.txt",
    )
    assert verdict.status == "passed"
    assert verdict.files == ["work/new.txt"]
    assert any("out of scope" in n and "test.obj" in n for n in verdict.notes)

    tracked = gitops.git(root, "ls-tree", "-r", "--name-only", verdict.branch).split()
    assert "test.obj" not in tracked
    assert gitops.git(root, "show", f"{verdict.branch}:base.txt") == "base\n"  # restored


def test_scope_does_not_hide_an_attempt_to_edit_the_kits_own_files(tmp_path) -> None:
    """The kit's files are outside any scope; discarding them would mask the tampering."""
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root, "x", scope=["work"], snapshot=snapshot("p/m1"),
        executor=writer({".opencode/agents/offload-build.md": "permissions: []\n", "work/a": "1"}),
        verify_cmd="git ls-files --error-unmatch work/a",
    )
    assert verdict.status == "tampered"


def test_everything_out_of_scope_means_no_changes(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root, "x", scope=["work"], snapshot=snapshot("p/m1"),
        executor=writer({"elsewhere.txt": "x"}),
    )
    assert verdict.status == "no_changes"
    assert not (root / "elsewhere.txt").exists()


def test_scope_from_config_applies_and_empty_scope_means_no_limit(tmp_path) -> None:
    root = make_repo(tmp_path)
    cfg = config.load(root)
    cfg.scope = ["work"]
    config.save(root, cfg)
    gitops.git(root, "add", "-A")
    gitops.git(root, "commit", "-q", "-m", "scope")

    limited = delegate.delegate(
        root, "x", snapshot=snapshot("p/m1"), executor=writer({"work/a": "1", "b": "2"}),
        verify_cmd="git ls-files --error-unmatch work/a",
    )
    assert limited.files == ["work/a"]

    # An explicit empty list on the call is "use the config"; no scope at all is no limit.
    cfg.scope = []
    config.save(root, cfg)
    gitops.git(root, "add", "-A")
    gitops.git(root, "commit", "-q", "-m", "no scope")
    free = delegate.delegate(
        root, "y", snapshot=snapshot("p/m1"), executor=writer({"c": "3", "d": "4"}),
        verify_cmd="git ls-files --error-unmatch c",
    )
    assert sorted(free.files) == ["c", "d"]


def test_discard_never_reaches_outside_the_project(tmp_path) -> None:
    root = make_repo(tmp_path)
    outside = tmp_path.parent / "keep-me.txt"
    outside.write_text("precious", encoding="utf-8")
    gitops.discard_paths(root, ["../keep-me.txt"])
    assert outside.read_text(encoding="utf-8") == "precious"
