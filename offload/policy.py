"""Политика приватности: что считать допустимым для кода этого проекта.

Политика описывает **правила отбора**, а не названия моделей. Человек говорит
«обучение на моих запросах запрещено, хранение не дольше недели», а какие
модели под это подходят, решает свежая таблица с официальной страницы.

Главный принцип: **неизвестное запрещено.** Модель, о которой нет данных, не
допускается, пока человек не разрешит её сам. Иначе сломавшийся разбор
страницы молча открыл бы доступ ко всему, включая модели, которые учатся на
запросах.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from offload import jsonio, paths
from offload.privacy import Privacy, normalize

# Готовые настройки на вопрос «что это за код». Вопрос задаёт `init`.
PRESETS: dict[str, dict] = {
    "strict": {
        "allow_training": False,
        "max_retention_days": 0,
        "require_known": True,
        "about": "закрытый или чувствительный код: без обучения и без хранения запросов",
    },
    "private": {
        "allow_training": False,
        "max_retention_days": 30,
        "require_known": True,
        "about": "обычный код: без обучения, хранение до 30 дней допустимо",
    },
    "open": {
        "allow_training": True,
        "max_retention_days": None,
        "require_known": False,
        "about": "открытый код: можно всё, в том числе модели, которые учатся на запросах",
    },
}

DEFAULT_PRESET = "strict"


@dataclass
class Policy:
    allow_training: bool = False
    max_retention_days: int | None = 0
    require_known: bool = True
    # Ручные исключения. Хранятся как есть, сравниваются по нормализованному виду.
    allowed: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)

    @classmethod
    def from_preset(cls, name: str) -> Policy:
        preset = PRESETS[name]
        return cls(
            allow_training=preset["allow_training"],
            max_retention_days=preset["max_retention_days"],
            require_known=preset["require_known"],
        )

    def to_dict(self) -> dict:
        return {
            "allow_training": self.allow_training,
            "max_retention_days": self.max_retention_days,
            "require_known": self.require_known,
            "allowed": self.allowed,
            "denied": self.denied,
        }


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str


def load(root) -> Policy:
    data = jsonio.read(paths.policy_file(root), None)
    if data is None:
        # Файла нет — действует самая строгая политика, а не самая мягкая.
        return Policy.from_preset(DEFAULT_PRESET)
    base = Policy.from_preset(DEFAULT_PRESET)
    return Policy(
        allow_training=bool(data.get("allow_training", base.allow_training)),
        max_retention_days=data.get("max_retention_days", base.max_retention_days),
        require_known=bool(data.get("require_known", base.require_known)),
        allowed=list(data.get("allowed", [])),
        denied=list(data.get("denied", [])),
    )


def save(root, policy: Policy) -> None:
    jsonio.write(paths.policy_file(root), policy.to_dict())


def short_id(model_id: str) -> str:
    """`opencode/beam-free` → `beam-free`: провайдер в таблице не указан."""
    return model_id.rsplit("/", 1)[-1]


def _listed(model_id: str, names: list[str]) -> bool:
    keys = {normalize(name) for name in names} | {normalize(short_id(n)) for n in names}
    return normalize(short_id(model_id)) in keys or normalize(model_id) in keys


def evaluate(model_id: str, privacy: Privacy | None, policy: Policy) -> Verdict:
    """Допустима ли модель. Порядок проверок — порядок важности."""
    if _listed(model_id, policy.denied):
        return Verdict(False, "запрещена вручную")
    if _listed(model_id, policy.allowed):
        return Verdict(True, "разрешена вручную")

    if privacy is None:
        if policy.require_known:
            return Verdict(False, "нет данных о приватности (разрешить: offload allow <модель>)")
        return Verdict(True, "данных о приватности нет, но политика это допускает")

    if privacy.trains is True and not policy.allow_training:
        return Verdict(False, "запросы идут в обучение")
    if privacy.trains is None and policy.require_known:
        return Verdict(False, "неизвестно, идут ли запросы в обучение")

    limit = policy.max_retention_days
    if limit is not None:
        if privacy.retention_days is None:
            if policy.require_known:
                return Verdict(False, "срок хранения запросов неизвестен")
        elif privacy.retention_days > limit:
            return Verdict(False, f"хранение {privacy.retention_days} дн. при пределе {limit}")

    return Verdict(True, "подходит под политику")
