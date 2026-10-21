"""`offload init`: разворачивает набор в любом проекте одной командой.

Свойства, ради которых он написан так:

- **Повторяемый.** Запуск поверх существующей установки обновляет то, что
  принадлежит набору, и не трогает то, что принадлежит человеку (политику,
  настройки, его собственный `AGENTS.md` вне нашего блока).
- **Работает без человека.** Оркестраторы запускают команды без клавиатуры,
  поэтому вопросов должно быть можно избежать флагами, а при их отсутствии
  выбирается самая строгая политика приватности, а не самая мягкая.
- **Ничего не ломает.** Чужие файлы не перезаписываются: если что-то нельзя
  сделать безопасно, об этом говорится, а не делается молча.
"""

from __future__ import annotations

import sys
from pathlib import Path

from offload import agents, config, opencode, paths, policy, texts


def detect_verify(root: Path) -> str:
    """Угадывает команду проверки по признакам проекта; пусто — не угадал."""
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        return "python -m pytest -q"
    if (root / "package.json").exists():
        return "npm test"
    if (root / "Cargo.toml").exists():
        return "cargo test"
    if (root / "go.mod").exists():
        return "go test ./..."
    return ""


def ask_preset(stream_in=None, stream_out=None) -> str:
    """Спрашивает, что за код. Возвращает имя набора политики."""
    stream_in = stream_in or sys.stdin
    stream_out = stream_out or sys.stdout

    names = list(policy.PRESETS)
    print("\nЧто за код в этом проекте? От этого зависит, каким моделям его можно "
          "отправлять.\nБесплатные модели работают на чужих серверах.\n", file=stream_out)
    for index, name in enumerate(names, 1):
        print(f"  {index}. {name:<8} {policy.PRESETS[name]['about']}", file=stream_out)
    print(file=stream_out)

    while True:
        stream_out.write(f"Номер [1 = {names[0]}]: ")
        stream_out.flush()
        raw = stream_in.readline()
        if raw == "":
            # Конец ввода, а не пустая строка: вопрос задавать некому.
            raise EOFError("ввод закрыт")
        answer = raw.strip()
        if not answer:
            return names[0]
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        if answer in policy.PRESETS:
            return answer
        print("Нужен номер из списка.", file=stream_out)


def _managed_block(section: str, verify: str) -> str:
    return section.replace("{verify}", verify or "не задана: укажите в .offload/config.json")


def write_agents_md(root: Path, verify: str) -> str:
    """Вставляет или обновляет наш блок в AGENTS.md. Остальное не трогает."""
    path = root / "AGENTS.md"
    block = _managed_block(texts.AGENTS_SECTION, verify)

    if not path.exists():
        path.write_text(f"# Правила проекта\n\n{block}", encoding="utf-8")
        return "создан AGENTS.md"

    text = path.read_text(encoding="utf-8")
    begin, end = text.find(texts.MARK_BEGIN), text.find(texts.MARK_END)
    if begin != -1 and end > begin:
        end += len(texts.MARK_END)
        new = text[:begin] + block.rstrip("\n") + text[end:]
        if new == text:
            return "AGENTS.md актуален"
        path.write_text(new, encoding="utf-8")
        return "обновлён блок в AGENTS.md"

    separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + separator + block, encoding="utf-8")
    return "добавлен блок в AGENTS.md"


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def ensure_gitignore(root: Path) -> str:
    line = f"{paths.DIR_NAME}/state/"
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if line in text.splitlines():
        return ""
    path.write_text(text + ("" if text.endswith("\n") or not text else "\n") + line + "\n",
                    encoding="utf-8")
    return f"в .gitignore добавлено {line}"


def init(root: Path, privacy: str | None = None, verify: str | None = None,
         interactive: bool | None = None) -> list[str]:
    """Разворачивает набор. Возвращает строки отчёта для человека."""
    report: list[str] = []
    if interactive is None:
        interactive = sys.stdin.isatty()

    # Приватность: флаг важнее вопроса, а без обоих — самое строгое.
    first_time = not paths.policy_file(root).exists()
    if first_time:
        if privacy is None:
            try:
                if not interactive:
                    raise EOFError
                privacy = ask_preset()
            except EOFError:
                privacy = policy.DEFAULT_PRESET
                report.append(
                    f"приватность: выбрана строгая ({privacy}), потому что вопрос некому задать. "
                    "Изменить: offload init --privacy open|private|strict (на пустом месте) "
                    f"или править {paths.DIR_NAME}/policy.json"
                )
        if privacy not in policy.PRESETS:
            raise SystemExit(f"неизвестная политика «{privacy}»; есть: {', '.join(policy.PRESETS)}")
        policy.save(root, policy.Policy.from_preset(privacy))
        report.append(f"политика приватности: {privacy} — {policy.PRESETS[privacy]['about']}")
    else:
        report.append("политика приватности уже задана — не меняю")

    cfg = config.load(root)
    if verify is not None:
        cfg.verify = verify
    elif not cfg.verify:
        cfg.verify = detect_verify(root)
    if first_time or verify is not None or not paths.config_file(root).exists():
        config.save(root, cfg)
    report.append(
        f"проверка результата: {cfg.verify}" if cfg.verify
        else "проверка результата: НЕ ОПРЕДЕЛЕНА — без неё делегировать нельзя, "
             f"укажите verify в {paths.DIR_NAME}/config.json"
    )

    if write_if_changed(paths.offload_dir(root) / "protocol.md", texts.PROTOCOL):
        report.append("записан .offload/protocol.md")
    report.append(write_agents_md(root, cfg.verify))

    changed = [name for name, body in agents.files().items()
               if write_if_changed(paths.agents_dir(root) / name, body)]
    report.append(f"агенты OpenCode: обновлено {len(changed)} из {len(agents.files())}")

    if note := ensure_gitignore(root):
        report.append(note)

    claude = root / "CLAUDE.md"
    if not claude.exists():
        claude.write_text("# Правила проекта — в [AGENTS.md](AGENTS.md)\n", encoding="utf-8")
        report.append("создан CLAUDE.md-указатель (Claude Code читает его, а не AGENTS.md)")
    elif "AGENTS.md" not in claude.read_text(encoding="utf-8"):
        report.append("CLAUDE.md не ссылается на AGENTS.md — добавьте ссылку, иначе Claude Code "
                      "не увидит правил делегирования")

    try:
        report.append(f"opencode найден: {opencode.version()}")
    except opencode.OpenCodeError as error:
        report.append(f"ВНИМАНИЕ: {error}")
    return report
