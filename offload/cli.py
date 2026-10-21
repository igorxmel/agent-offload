"""Командная строка. Оркестратор вызывает именно её.

Каждая команда умеет `--json`: оркестратор — машина, и разбирать таблицу для
людей ему незачем. Коды выхода: 0 — успех, 1 — ошибка использования или среды,
2 — нет допустимых моделей (отдельный код, чтобы его можно было обработать).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from offload import __version__, discover, jsonio, opencode, policy, select
from offload import init as init_mod

EXIT_NO_MODELS = 2


def _root(args) -> Path:
    return Path(args.root).resolve()


def _out(args, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else text)


def _warn(snapshot) -> None:
    for line in snapshot.warnings:
        print(f"! {line}", file=sys.stderr)


def cmd_init(args) -> int:
    for line in init_mod.init(_root(args), privacy=args.privacy, verify=args.verify):
        print(f"- {line}")
    return 0


def cmd_models(args) -> int:
    snap = discover.discover(_root(args), refresh=args.refresh)
    _warn(snap)
    entries = snap.allowed() if args.allowed else snap.entries
    data = [
        {"id": e.id, "allowed": e.allowed, "reason": e.reason,
         "privacy": e.privacy.to_dict() if e.privacy else None}
        for e in entries
    ]
    lines = [f"{'да ' if e.allowed else 'нет'}  {e.id:<44} {e.reason}" for e in entries]
    _out(args, data, "\n".join(lines) or "моделей нет")
    return 0 if snap.allowed() else EXIT_NO_MODELS


def cmd_pick(args) -> int:
    root = _root(args)
    snap = discover.discover(root, refresh=args.refresh)
    _warn(snap)
    choice = select.pick(root, snap, args.role)
    if choice is None:
        print("нет ни одной допустимой модели. Смотрите: offload models", file=sys.stderr)
        return EXIT_NO_MODELS
    _out(args, {"model": choice.model, "basis": choice.basis},
         choice.model if not args.verbose else f"{choice.model}  ({choice.basis})")
    return 0


def cmd_discover(args) -> int:
    snap = discover.discover(_root(args), refresh=True)
    _warn(snap)
    _out(args, {"models": len(snap.entries), "allowed": len(snap.allowed())},
         f"моделей: {len(snap.entries)}, допустимых: {len(snap.allowed())}")
    return 0


def _edit_list(args, field: str, other: str) -> int:
    root = _root(args)
    pol = policy.load(root)
    getattr(pol, other)[:] = [m for m in getattr(pol, other) if m != args.model]
    if args.model not in getattr(pol, field):
        getattr(pol, field).append(args.model)
    policy.save(root, pol)
    print(f"{args.model}: {'разрешена' if field == 'allowed' else 'запрещена'} вручную")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="offload", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", default=".", help="папка проекта (по умолчанию текущая)")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="развернуть набор в проекте")
    p.add_argument("--privacy", choices=list(policy.PRESETS),
                   help="политика приватности, чтобы не спрашивать")
    p.add_argument("--verify", help="команда проверки результата")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("models", help="модели и допустимы ли они по политике")
    p.add_argument("--allowed", action="store_true", help="только допустимые")
    p.add_argument("--refresh", action="store_true", help="не брать кэш")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("pick", help="выбрать модель среди допустимых")
    p.add_argument("--role", default="build", help="explore | plan | build | review")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="показать основание выбора")
    p.set_defaults(func=cmd_pick)

    p = sub.add_parser("discover", help="обновить список моделей и условия приватности")
    p.set_defaults(func=cmd_discover)

    for name, field, other, text in (
        ("allow", "allowed", "denied", "разрешить модель вручную"),
        ("deny", "denied", "allowed", "запретить модель вручную"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("model")
        p.set_defaults(func=lambda a, f=field, o=other: _edit_list(a, f, o))
    return parser


def main(argv: list[str] | None = None) -> int:
    # Вывод всегда в UTF-8: оркестратор читает его как текст, а системная
    # кодировка консоли Windows превращает кириллицу в нечитаемые знаки.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (opencode.OpenCodeError, jsonio.ConfigError) as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 1
