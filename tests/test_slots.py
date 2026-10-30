"""Delegations in separate working copies: the person's tree is never touched, and
two delegations can run at the same time without sharing files."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from offload import config, delegate, gitops, slots
from tests.test_delegate import GOOD_REPORT, branches, make_repo, result, snapshot


def test_executor_works_in_a_slot_and_the_persons_tree_is_never_checked_out(tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / "mine.txt").write_text("untracked work of the person\n", encoding="utf-8")
    gitops.git(root, "add", "mine.txt")
    gitops.git(root, "commit", "-qm", "mine")
    seen = {}

    def executor(work, agent, model, message, task_file, timeout, *_):
        seen["work"] = Path(work)
        seen["root_branch_during_run"] = gitops.current_ref(root)
        (Path(work) / "new.txt").write_text("x\n", encoding="utf-8")
        return result()

    verdict = delegate.delegate(root, "create new.txt", snapshot=snapshot("p/m1"), executor=executor)
    assert verdict.status == "passed"
    assert seen["work"].resolve() != root.resolve()
    assert seen["root_branch_during_run"] == "main"  # never switched, not even briefly
    assert not (root / "new.txt").exists()
    assert gitops.git(root, "status", "--porcelain").strip() == ""
    assert "new.txt" in gitops.git(root, "ls-tree", "-r", "--name-only", verdict.branch)


def test_two_delegations_run_at_once_in_different_slots(tmp_path) -> None:
    root = make_repo(tmp_path, verify="git ls-files --error-unmatch a.txt || "
                                      "git ls-files --error-unmatch b.txt")
    inside = []
    barrier = threading.Barrier(2, timeout=20)

    def executor_for(name):
        def run(work, agent, model, message, task_file, timeout, *_):
            inside.append(Path(work).resolve())
            barrier.wait()  # both are running at the same moment
            (Path(work) / f"{name}.txt").write_text(name + "\n", encoding="utf-8")
            return result(GOOD_REPORT)
        return run

    verdicts = {}

    def go(name):
        verdicts[name] = delegate.delegate(root, f"create {name}.txt", snapshot=snapshot("p/m1"),
                                           executor=executor_for(name))

    threads = [threading.Thread(target=go, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert len(set(inside)) == 2
    assert {v.status for v in verdicts.values()} == {"passed"}
    a, b = verdicts["a"].branch, verdicts["b"].branch
    assert a != b and {a, b} <= set(branches(root))
    tree_a = gitops.git(root, "ls-tree", "-r", "--name-only", a)
    assert "a.txt" in tree_a and "b.txt" not in tree_a  # nothing leaked between them


def test_slot_is_reused_with_ignored_build_output_kept_warm(tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / ".gitignore").write_text(
        (root / ".gitignore").read_text(encoding="utf-8") + "target/\n", encoding="utf-8")
    gitops.git(root, "commit", "-qam", "ignore target")
    works = []

    def executor(work, agent, model, message, task_file, timeout, *_):
        work = Path(work)
        works.append(work.resolve())
        (work / "target").mkdir(exist_ok=True)
        marker = work / "target" / "built.bin"
        first = not marker.exists()
        marker.write_text("cache", encoding="utf-8")
        (work / "leftover.txt").write_text("untracked junk\n", encoding="utf-8") if first else None
        (work / "new.txt").write_text("x\n", encoding="utf-8")
        return result()

    first = delegate.delegate(root, "one", snapshot=snapshot("p/m1"), executor=executor)
    # A run that died mid-way leaves untracked junk in the slot; the next run must not
    # pick it up.
    (works[0] / "crash-junk.txt").write_text("half-written\n", encoding="utf-8")
    second = delegate.delegate(root, "two", snapshot=snapshot("p/m1"), executor=executor)
    assert "crash-junk.txt" not in second.files
    assert works[0] == works[1]
    assert (works[1] / "target" / "built.bin").exists()  # ignored output survived
    tree = lambda v: gitops.git(root, "ls-tree", "-r", "--name-only", v.branch)
    assert "leftover.txt" in tree(first)
    assert "leftover.txt" not in tree(second)  # the slot was reset to the base in between


def test_failure_releases_the_slot_and_discards_the_branch(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(root, "x", snapshot=snapshot("p/m1"),
                                executor=lambda *a: result(code=1))
    assert verdict.status == "executor_error" and verdict.branch == ""
    assert branches(root) == ["main"]
    locks = list((root / ".offload" / "state" / "worktrees").glob("*.lock"))
    assert locks == []


def test_stale_lock_is_taken_over_and_a_live_one_is_not(tmp_path) -> None:
    root = make_repo(tmp_path)
    folder = root / ".offload" / "state" / "worktrees"
    folder.mkdir(parents=True)
    lock = folder / "slot-1.lock"
    lock.write_text("1 0\n", encoding="utf-8")
    base = gitops.head(root)
    slot = slots.acquire(root, base, "offload/t1", stale_after=3600)
    assert slot.number == 2  # slot 1 looks busy
    slots.release(root, slot, "offload/t1", keep_branch=False)
    old = time.time() - 7200
    os.utime(lock, (old, old))
    slot = slots.acquire(root, base, "offload/t2", stale_after=3600)
    assert slot.number == 1  # the dead run's lock was taken over
    slots.release(root, slot, "offload/t2", keep_branch=False)


def test_ignored_local_files_are_copied_into_the_slot(tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / ".gitignore").write_text(
        (root / ".gitignore").read_text(encoding="utf-8") + "local.properties\n", encoding="utf-8")
    gitops.git(root, "commit", "-qam", "ignore local")
    (root / "local.properties").write_text("sdk.dir=C:/sdk\n", encoding="utf-8")
    cfg = config.load(root)
    cfg.worktree_copy = ["local.properties"]
    config.save(root, cfg)
    gitops.git(root, "commit", "-qam", "copy list")
    seen = {}

    def executor(work, agent, model, message, task_file, timeout, *_):
        seen["copy"] = (Path(work) / "local.properties").read_text(encoding="utf-8")
        (Path(work) / "new.txt").write_text("x\n", encoding="utf-8")
        return result()

    verdict = delegate.delegate(root, "x", snapshot=snapshot("p/m1"), executor=executor)
    assert seen["copy"] == "sdk.dir=C:/sdk\n"
    assert "local.properties" not in verdict.files  # ignored, so never committed


def test_review_on_a_branch_sees_that_branch_and_changes_nothing(tmp_path) -> None:
    root = make_repo(tmp_path)
    built = delegate.delegate(root, "create new.txt", snapshot=snapshot("p/m1"),
                              executor=lambda w, *a: (Path(w, "new.txt").write_text("x\n"),
                                                      result())[1])
    tip = gitops.branch_tip(root, built.branch)
    seen = {}

    def reviewer(work, agent, model, message, task_file, timeout, *_):
        seen["agent"] = agent
        seen["has_file"] = (Path(work) / "new.txt").exists()
        seen["task"] = (Path(work) / task_file).read_text(encoding="utf-8")
        return result("DONE: reviewed\nVERIFIED: read\nNOT DONE: none\nDECISIONS: none\n"
                      "BLOCKERS: none\n")

    verdict = delegate.delegate(root, "Review it.", role="review", on=built.branch,
                                snapshot=snapshot("p/m1"), executor=reviewer)
    assert verdict.status == "passed" and verdict.branch == ""
    assert verdict.report_ok and verdict.report["ANSWER"].startswith("DONE: reviewed")
    assert not any("report format" in n for n in verdict.notes)
    assert seen["agent"] == "offload-review" and seen["has_file"]
    assert "git diff" in seen["task"] and "..HEAD" in seen["task"]
    assert gitops.branch_tip(root, built.branch) == tip  # the reviewed branch is untouched
    assert gitops.current_ref(root) == "main" and not (root / "new.txt").exists()


def test_on_is_refused_for_writing_roles_and_unknown_branches(tmp_path) -> None:
    root = make_repo(tmp_path)
    with pytest.raises(delegate.DelegateError, match="read-only"):
        delegate.delegate(root, "x", role="build", on="main", snapshot=snapshot("p/m1"),
                          executor=lambda *a: result())
    with pytest.raises(delegate.DelegateError, match="no such branch"):
        delegate.delegate(root, "x", role="review", on="offload/none", snapshot=snapshot("p/m1"),
                          executor=lambda *a: result())


def test_all_slots_busy_is_a_clear_error(tmp_path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    monkeypatch.setattr(slots, "MAX_SLOTS", 1)
    folder = root / ".offload" / "state" / "worktrees"
    folder.mkdir(parents=True)
    (folder / "slot-1.lock").write_text("1 0\n", encoding="utf-8")
    with pytest.raises(delegate.DelegateError, match="busy"):
        delegate.delegate(root, "x", snapshot=snapshot("p/m1"), executor=lambda *a: result())
    assert branches(root) == ["main"]
