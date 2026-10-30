"""Work an executor did before it was killed is kept, unverified, instead of lost.

Seen live: a provider stopped answering after 12 useful minutes and the timeout
threw all of it away.
"""

from __future__ import annotations

from pathlib import Path

from offload import delegate, gitops
from offload.opencode import AgentResult
from tests.test_delegate import branches, make_repo, result, snapshot


def killed(outcome: str, files: dict[str, str]):
    def run(work, agent, model, message, task_file, timeout, *_):
        for name, text in files.items():
            target = Path(work) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return AgentResult(1, "step 1\nstep 2\n", "", 900.0, timed_out=outcome == "timeout",
                           stalled=outcome == "stall")
    return run


def test_stalled_work_is_kept_on_a_partial_branch_and_can_be_resumed(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(root, "create new.txt", snapshot=snapshot("p/m1"),
                                executor=killed("stall", {"half.txt": "half\n"}))
    assert verdict.status == "executor_error" and verdict.branch == ""
    assert len(verdict.partial) == 1
    side = verdict.partial[0]
    assert side in branches(root)
    assert "half.txt" in gitops.git(root, "ls-tree", "-r", "--name-only", side)
    assert any("--resume" in n for n in verdict.notes)
    assert gitops.current_ref(root) == "main" and not (root / "half.txt").exists()

    def finish(work, agent, model, message, task_file, timeout, *_):
        assert (Path(work) / "half.txt").exists()  # resumed on top of the kept work
        (Path(work) / "new.txt").write_text("x\n", encoding="utf-8")
        return result()

    done = delegate.delegate(root, "1. finish it", snapshot=snapshot("p/m1"),
                             resume=side, executor=finish)
    assert done.status == "passed"


def test_timeout_keeps_work_too_but_a_plain_error_does_not(tmp_path) -> None:
    root = make_repo(tmp_path)
    timed = delegate.delegate(root, "x", snapshot=snapshot("p/m1"),
                              executor=killed("timeout", {"a.txt": "a\n"}))
    assert len(timed.partial) == 1

    def errored(work, *a):
        (Path(work) / "b.txt").write_text("b\n", encoding="utf-8")
        return AgentResult(1, "", "Error: something", 1.0)

    plain = delegate.delegate(root, "y", snapshot=snapshot("p/m1"), executor=errored)
    assert plain.partial == []


def test_work_done_before_a_quota_stop_is_kept(tmp_path) -> None:
    # Seen live: a model worked ~10 minutes, then "Daily limit reached" threw it away.
    root = make_repo(tmp_path)

    def worked_then_quota(work, *a):
        (Path(work) / "half.txt").write_text("half\n", encoding="utf-8")
        return AgentResult(1, "", "Error: Daily limit reached for x/y:free (limit_rpd)", 640.0)

    verdict = delegate.delegate(root, "x", snapshot=snapshot("x/y:free"),
                                executor=worked_then_quota)
    assert verdict.status == "quota" and len(verdict.partial) == 1
    assert "half.txt" in gitops.git(root, "ls-tree", "-r", "--name-only", verdict.partial[0])


def test_partial_work_obeys_scope_size_and_tamper_rules(tmp_path) -> None:
    root = make_repo(tmp_path)
    scoped = delegate.delegate(root, "x", snapshot=snapshot("p/m1"), scope=["src"],
                               executor=killed("stall", {"src/ok.txt": "ok\n",
                                                         "elsewhere.txt": "no\n"}))
    tree = gitops.git(root, "ls-tree", "-r", "--name-only", scoped.partial[0])
    assert "src/ok.txt" in tree and "elsewhere.txt" not in tree

    only_stray = delegate.delegate(root, "y", snapshot=snapshot("p/m1"), scope=["src"],
                                   executor=killed("stall", {"elsewhere.txt": "no\n"}))
    assert only_stray.partial == []

    cage = ".opencode/agents/offload-build.md"
    tampered = delegate.delegate(root, "z", snapshot=snapshot("p/m1"),
                                 executor=killed("stall", {cage: "x\n", "a.txt": "a\n"}))
    assert tampered.partial == []


def test_each_killed_attempt_gets_its_own_partial_branch(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(root, "x", snapshot=snapshot("p/m1", "p/m2"), max_attempts=2,
                                executor=killed("stall", {"a.txt": "a\n"}))
    assert len(verdict.partial) == 2 and verdict.partial[0] != verdict.partial[1]
    assert all(b in branches(root) for b in verdict.partial)
