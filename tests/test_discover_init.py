"""`discover`, выбор модели и `init` — без сети и без настоящего opencode."""

from __future__ import annotations

from pathlib import Path

from offload import config, discover, history, init, paths, policy, select

PAGE = (Path(__file__).parent / "fixtures" / "privacy_table.html").read_text(encoding="utf-8")
MODELS = ["opencode/glm-5.3-flash", "opencode/muse-spark-1.3-contributor", "opencode/mystery"]


def fetcher(url: str) -> str:
    return PAGE


def lister() -> list[str]:
    return list(MODELS)


def setup(tmp_path, preset="private"):
    policy.save(tmp_path, policy.Policy.from_preset(preset))
    return tmp_path


def test_policy_is_applied_to_fresh_data(tmp_path) -> None:
    snap = discover.discover(setup(tmp_path), fetcher=fetcher, lister=lister, now=1000)
    verdict = {e.id: e.allowed for e in snap.entries}
    assert verdict["opencode/glm-5.3-flash"] is True
    assert verdict["opencode/muse-spark-1.3-contributor"] is False  # идёт в обучение
    assert verdict["opencode/mystery"] is False  # нет данных → запрещено


def test_cache_avoids_second_fetch_and_expires(tmp_path) -> None:
    root = setup(tmp_path)
    calls = []

    def counting(url):
        calls.append(url)
        return PAGE

    discover.discover(root, fetcher=counting, lister=lister, now=1000)
    discover.discover(root, fetcher=counting, lister=lister, now=1000 + 3600)
    assert len(calls) == 1
    discover.discover(root, fetcher=counting, lister=lister, now=1000 + 25 * 3600)
    assert len(calls) == 2


def test_broken_page_keeps_previous_data_instead_of_opening_access(tmp_path) -> None:
    root = setup(tmp_path)
    discover.discover(root, fetcher=fetcher, lister=lister, now=1000)
    snap = discover.discover(
        root, refresh=True, fetcher=lambda u: "<html>другая вёрстка</html>",
        lister=lister, now=2000,
    )
    assert snap.warnings
    assert {e.id: e.allowed for e in snap.entries}["opencode/glm-5.3-flash"] is True


def test_no_cache_and_broken_page_denies_everything(tmp_path) -> None:
    snap = discover.discover(
        setup(tmp_path), fetcher=lambda u: "<html></html>", lister=lister, now=1000
    )
    assert snap.allowed() == []


def test_pick_prefers_measured_results_over_list_order(tmp_path) -> None:
    root = setup(tmp_path, "open")
    snap = discover.discover(root, fetcher=fetcher, lister=lister, now=1000)
    assert select.pick(root, snap, "build").basis == "guess"

    history.record(root, "opencode/mystery", "build", passed=True)
    choice = select.pick(root, snap, "build")
    assert (choice.model, choice.basis) == ("opencode/mystery", "history")


def test_pick_returns_none_when_nothing_is_allowed(tmp_path) -> None:
    snap = discover.discover(
        setup(tmp_path, "strict"), fetcher=lambda u: "<html></html>", lister=lister, now=1000
    )
    assert select.pick(tmp_path, snap, "build") is None


def test_init_is_strict_without_a_human_and_idempotent(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    first = init.init(tmp_path, interactive=False)
    assert any("строгая" in line for line in first)
    assert policy.load(tmp_path).max_retention_days == 0
    assert config.load(tmp_path).verify == "python -m pytest -q"

    # Пользователь ослабил политику руками — повторный init её не трогает.
    policy.save(tmp_path, policy.Policy.from_preset("open"))
    agents_before = (paths.agents_dir(tmp_path) / "offload-build.md").read_text(encoding="utf-8")
    init.init(tmp_path, interactive=False)
    assert policy.load(tmp_path).allow_training is True
    assert (paths.agents_dir(tmp_path) / "offload-build.md").read_text(encoding="utf-8") == agents_before


def test_init_keeps_foreign_agents_md_and_updates_only_its_block(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Мои правила\n\nНе трогать.\n", encoding="utf-8")
    init.init(tmp_path, privacy="private", interactive=False)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Мои правила\n\nНе трогать.")
    assert text.count("offload:begin") == 1

    init.init(tmp_path, privacy="private", verify="make check", interactive=False)
    again = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert again.count("offload:begin") == 1 and "Не трогать." in again


def test_agent_profiles_deny_leaving_the_project_and_secrets(tmp_path) -> None:
    init.init(tmp_path, privacy="private", interactive=False)
    for role in ("explore", "plan", "build", "review"):
        body = (paths.agents_dir(tmp_path) / f"offload-{role}.md").read_text(encoding="utf-8")
        assert "action: external_directory" in body, role
        assert '"*.env"' in body and '"git push *"' in body, role
    assert 'action: edit' in (paths.agents_dir(tmp_path) / "offload-review.md").read_text(encoding="utf-8")


def test_closed_stdin_falls_back_to_strict_instead_of_hanging(tmp_path, monkeypatch) -> None:
    """Оркестратор запускает init без клавиатуры: вопрос задавать некому."""
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    report = init.init(tmp_path, interactive=True)
    assert any("некому задать" in line for line in report)
    assert policy.load(tmp_path).max_retention_days == 0
