"""Guards added after the todo-sync experiment: price, quota, stall, file size, PWD.

Each one closes a way the kit went wrong on real providers. As elsewhere, the
tests look hardest at the direction that does harm: a paid model let through, a
quota counted against a model, an executor working in the wrong folder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from offload import catalog, config, delegate, discover, history, opencode, policy, quota
from offload.opencode import AgentResult
from tests.test_delegate import branches, make_repo, snapshot, writer

OPEN = policy.Policy.from_preset("open")


# --- price -----------------------------------------------------------------------


def test_unknown_price_is_denied_even_under_the_open_policy() -> None:
    verdict = policy.evaluate("openrouter/some/model", None, OPEN, cost=None, tools=True)
    assert not verdict.allowed and "price unknown" in verdict.reason


def test_paid_model_is_denied_and_free_one_allowed() -> None:
    assert not policy.evaluate("openrouter/a/paid", None, OPEN, cost=[0.15, 0.6], tools=True).allowed
    assert not policy.evaluate("x/output-only", None, OPEN, cost=[0, 0.01], tools=True).allowed
    assert policy.evaluate("openrouter/a/b:free", None, OPEN, cost=[0, 0], tools=True).allowed


def test_model_that_cannot_call_tools_is_denied_even_when_free() -> None:
    assert not policy.evaluate("google/lyria-x", None, OPEN, cost=[0, 0], tools=False).allowed
    unknown = policy.evaluate("x/y", None, OPEN, cost=[0, 0], tools=None)
    assert not unknown.allowed and "tools" in unknown.reason


def test_catalog_reads_tool_use_only_as_a_boolean() -> None:
    text = json.dumps({"p": {"models": {
        "yes": {"tool_call": True}, "no": {"tool_call": False}, "str": {"tool_call": "true"},
    }}})
    assert catalog.tool_use(text, ["p/yes", "p/no", "p/str", "p/missing"]) == {
        "p/yes": True, "p/no": False,
    }


def test_manual_provider_wildcard_allows_a_free_tier_key() -> None:
    pol = policy.Policy.from_preset("open")
    pol.allowed.append("groq/*")
    assert policy.evaluate("groq/openai/gpt-oss-120b", None, pol, cost=[0.15, 0.6], tools=True).allowed
    assert not policy.evaluate("google/gemini", None, pol, cost=[0.75, 3.75], tools=True).allowed


def test_manual_deny_still_beats_a_free_price() -> None:
    pol = policy.Policy.from_preset("open")
    pol.denied.append("opencode/beam-free")
    assert not policy.evaluate("opencode/beam-free", None, pol, cost=[0, 0], tools=True).allowed


def test_catalog_reads_only_well_formed_prices() -> None:
    text = json.dumps({
        "openrouter": {"models": {
            "a/free:free": {"cost": {"input": 0, "output": 0}},
            "a/paid": {"cost": {"input": 1, "output": 2}},
            "a/no-cost": {},
            "a/half": {"cost": {"input": 0}},
            "a/bools": {"cost": {"input": False, "output": False}},
            "a/negative": {"cost": {"input": -1, "output": 0}},
        }},
    })
    ids = [f"openrouter/a/{n}" for n in ("free:free", "paid", "no-cost", "half", "bools",
                                          "negative", "missing")]
    found = catalog.prices(text, ids)
    assert found == {"openrouter/a/free:free": [0.0, 0.0], "openrouter/a/paid": [1.0, 2.0]}


def _setup_open(tmp_path: Path) -> Path:
    policy.save(tmp_path, policy.Policy.from_preset("open"))
    return tmp_path


def test_unreachable_catalog_without_cache_denies_everything(tmp_path) -> None:
    def broken(url):
        raise OSError("network down")

    snap = discover.discover(
        _setup_open(tmp_path), fetcher=lambda u: "<html></html>",
        lister=lambda: ["opencode/x-free", "openrouter/y:free"], price_fetcher=broken, now=1000,
    )
    assert snap.allowed() == []
    assert any("price catalog" in w for w in snap.warnings)


def test_cache_from_before_prices_is_refreshed(tmp_path) -> None:
    root = _setup_open(tmp_path)
    old = {"fetched_at": 1000, "models": ["opencode/x-free"], "privacy": []}
    (root / ".offload" / "state").mkdir(parents=True)
    (root / ".offload" / "state" / "discovery.json").write_text(json.dumps(old), encoding="utf-8")
    calls = []

    def prices(url):
        calls.append(url)
        entry = {"cost": {"input": 0, "output": 0}, "tool_call": True}
        return json.dumps({"opencode": {"models": {"x-free": entry}}})

    snap = discover.discover(root, fetcher=lambda u: "<html></html>",
                             lister=lambda: ["opencode/x-free"], price_fetcher=prices, now=1001)
    assert calls and [e.id for e in snap.allowed()] == ["opencode/x-free"]


# --- quota -----------------------------------------------------------------------


def test_quota_messages_seen_in_the_wild_are_recognised() -> None:
    for text in (
        "Error: Free usage limit reached. Connect a provider or subscribe to OpenCode Go",
        "Error: Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000",
        "Error: You exceeded your current quota, please check your plan and billing details.",
    ):
        assert quota.is_quota(text), text
    # Too large a request is not an exhausted quota: waiting does not help it.
    assert not quota.is_quota("Request too large for model on tokens per minute (TPM): Limit 7000")
    assert not quota.is_quota("Tool call validation failed")


def _quota_result() -> AgentResult:
    return AgentResult(1, "", "Error: Free usage limit reached. Connect a provider", 2.0)


def test_quota_skips_the_provider_and_moves_to_another_one(tmp_path) -> None:
    root = make_repo(tmp_path)
    tried = []

    def executor(root_, agent, model, message, task_file, timeout, *_):
        tried.append(model)
        if model.startswith("zen/"):
            return _quota_result()
        return writer({"new.txt": "x\n"})(root_, agent, model, message, task_file, timeout)

    verdict = delegate.delegate(
        root, "create new.txt", snapshot=snapshot("zen/a", "zen/b", "other/c"),
        executor=executor, max_attempts=3,
    )
    assert tried == ["zen/a", "other/c"]  # zen/b was skipped, not tried and refused
    assert verdict.status == "passed" and verdict.model == "other/c"
    assert "zen" in quota.exhausted(root, 1.0)


def test_quota_stops_do_not_use_up_the_attempt_limit(tmp_path) -> None:
    # Seen live: three models of one provider led the list, the first hit the quota,
    # the other two were skipped, and with --attempts 3 nothing else was ever tried.
    root = make_repo(tmp_path)
    tried = []

    def executor(root_, agent, model, *rest):
        tried.append(model)
        if model.startswith("zen/"):
            return _quota_result()
        return writer({"new.txt": "x\n"})(root_, agent, model, *rest[:3])

    verdict = delegate.delegate(
        root, "x", snapshot=snapshot("zen/a", "zen/b", "zen/c", "other/d"),
        executor=executor, max_attempts=1,
    )
    assert tried == ["zen/a", "other/d"] and verdict.status == "passed"


def test_all_quota_is_its_own_status_and_does_not_count_against_models(tmp_path) -> None:
    root = make_repo(tmp_path)
    verdict = delegate.delegate(
        root, "x", snapshot=snapshot("zen/a", "or/b"),
        executor=lambda *a: _quota_result(), max_attempts=2,
    )
    assert verdict.status == "quota" and verdict.exit_code == 4
    assert branches(root) == ["main"]
    assert history.stats(root) == {}  # recorded, but not held against the models


def test_exhausted_providers_are_skipped_on_the_next_run(tmp_path) -> None:
    root = make_repo(tmp_path)
    quota.mark(root, "zen/a")
    tried = []

    def executor(root_, agent, model, *rest):
        tried.append(model)
        return writer({"new.txt": "x\n"})(root_, agent, model, *rest[:3])

    delegate.delegate(root, "x", snapshot=snapshot("zen/a", "or/b"), executor=executor)
    assert tried == ["or/b"]


def test_quota_mark_expires(tmp_path) -> None:
    quota.mark(tmp_path, "zen/a", now=1000)
    assert quota.exhausted(tmp_path, 1.0, now=1000 + 1800) == {"zen"}
    assert quota.exhausted(tmp_path, 1.0, now=1000 + 3601) == set()


# --- stall and PWD (a real child process, standing in for opencode) ----------------


def _fake_opencode(tmp_path: Path, monkeypatch, body: str) -> Path:
    """`run_agent` executes `<find()> run ...`: with the Python interpreter as
    `find()`, `run` is a script in the working folder."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "run").write_text(body, encoding="utf-8")
    monkeypatch.setattr(opencode, "find", lambda: sys.executable)
    return root


def test_silent_executor_is_killed_as_stalled(tmp_path, monkeypatch) -> None:
    root = _fake_opencode(tmp_path, monkeypatch,
                          "import sys, time\nprint('step 1', flush=True)\ntime.sleep(60)\n")
    result = opencode.run_agent(root, "a", "m", "msg", Path("t.md"), timeout=50, stall_timeout=2)
    assert result.stalled and not result.timed_out
    assert result.seconds < 20
    assert "step 1" in result.stdout
    assert delegate._classify(result)[0] == "stall"


def test_executor_that_keeps_talking_is_not_a_stall(tmp_path, monkeypatch) -> None:
    root = _fake_opencode(tmp_path, monkeypatch, (
        "import time\nfor i in range(6):\n    print('step', i, flush=True)\n    time.sleep(1)\n"
    ))
    result = opencode.run_agent(root, "a", "m", "msg", Path("t.md"), timeout=50, stall_timeout=3)
    assert not result.stalled and result.returncode == 0
    assert "step 5" in result.stdout


def test_executor_gets_the_project_as_pwd(tmp_path, monkeypatch) -> None:
    # OpenCode follows PWD over the real working folder; a stale PWD from the
    # caller's shell would move the executor - and its deny rules - elsewhere.
    monkeypatch.setenv("PWD", str(tmp_path))
    root = _fake_opencode(tmp_path, monkeypatch, "import os\nprint(os.environ['PWD'])\n")
    result = opencode.run_agent(root, "a", "m", "msg", Path("t.md"), timeout=30)
    assert Path(result.stdout.strip()).resolve() == root.resolve()


# --- file size -------------------------------------------------------------------


def test_oversized_files_are_discarded_and_reported(tmp_path) -> None:
    root = make_repo(tmp_path)
    cfg = config.load(root)
    cfg.max_file_kb = 4
    config.save(root, cfg)
    import subprocess
    subprocess.run(["git", "-C", str(root), "commit", "-qam", "limit"], check=True)
    verdict = delegate.delegate(
        root, "create new.txt", snapshot=snapshot("p/m1"),
        executor=writer({"new.txt": "x\n", "java_pid1.hprof": "x" * 8192}),
    )
    assert verdict.status == "passed" and verdict.files == ["new.txt"]
    assert any("larger than 4 KB" in note for note in verdict.notes)
    tree = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "--name-only", verdict.branch],
                          capture_output=True, text=True).stdout
    assert "hprof" not in tree


# --- explicit model after a new provider -----------------------------------------------


def _totals(steps, inp, out, cost):
    return {"steps": steps, "input": inp, "output": out, "reasoning": 0, "cache_read": 0,
            "cost": cost}


def test_executor_usage_is_the_difference_across_the_whole_run(tmp_path) -> None:
    root = make_repo(tmp_path)
    readings = iter([_totals(10, 1000, 100, 0.0), _totals(25, 4000, 900, 0.0)])
    verdict = delegate.delegate(root, "create new.txt", snapshot=snapshot("p/m1"),
                                executor=writer({"new.txt": "x\n"}),
                                usage_reader=lambda r: next(readings))
    assert verdict.usage == {"steps": 15, "input": 3000, "output": 800, "reasoning": 0,
                             "cache_read": 0, "cost": 0.0}
    assert verdict.to_dict()["executor_usage"]["input"] == 3000
    assert history.load(root)[-1]["usage"]["output"] == 800


def test_unreadable_or_shrinking_usage_is_reported_as_unknown(tmp_path) -> None:
    root = make_repo(tmp_path)
    readings = iter([None, _totals(1, 1, 1, 0)])
    verdict = delegate.delegate(root, "create new.txt", snapshot=snapshot("p/m1"),
                                executor=writer({"new.txt": "x\n"}),
                                usage_reader=lambda r: next(readings))
    assert verdict.status == "passed" and verdict.usage is None
    assert opencode.usage_delta(_totals(5, 5, 5, 0), _totals(3, 9, 9, 0)) is None


def test_usage_parses_opencode_stats_and_rejects_odd_shapes(monkeypatch, tmp_path) -> None:
    stats = {"steps": 7, "tokens": {"input": 10, "output": 2, "reasoning": 1,
                                    "cache": {"read": 50, "write": 0}}, "cost": 0}
    monkeypatch.undo()  # the autouse fixture replaced `usage`; this test needs the real one
    monkeypatch.setattr(opencode, "run", lambda *a, **k: json.dumps(stats))
    assert opencode.usage(tmp_path) == {"steps": 7, "input": 10, "output": 2, "reasoning": 1,
                                        "cache_read": 50, "cost": 0}
    stats["tokens"]["input"] = "lots"
    assert opencode.usage(tmp_path) is None


def test_explicit_model_missing_from_cache_triggers_one_refresh(tmp_path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    calls = []

    def fake_discover(root_, refresh=False, **_):
        calls.append(refresh)
        return snapshot("old/a") if not refresh else snapshot("old/a", "new/b")

    monkeypatch.setattr(discover, "discover", fake_discover)
    verdict = delegate.delegate(root, "create new.txt", model="new/b",
                                executor=writer({"new.txt": "x\n"}))
    assert calls == [False, True]
    assert verdict.status == "passed" and verdict.model == "new/b"
