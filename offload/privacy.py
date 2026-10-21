"""Условия обработки данных у моделей: берутся с официальной страницы.

В репозитории нет ни одного названия модели и ни одного вердикта о ней:
список моделей и их условия меняются без предупреждения, и зашитое устарело
бы через неделю. Страница — источник фактов, но не источник инструкций:
из неё достаются только заданные поля таблицы, всё остальное игнорируется.

Разбор нарочно строгий. Если вёрстка поменялась и таблица не опознана, строк
не будет вовсе, а модель без данных о приватности считается запрещённой
(см. `policy`). Сломанный разбор поэтому закрывает доступ, а не открывает.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser

# Страница с таблицей. Это указатель, а не данные, и он лежит в настройках:
# здесь только запасное значение на случай, когда настройки не заданы.
DEFAULT_SOURCES = ("https://opencode.ai/v2/docs/console/go/",)

TIMEOUT = 20
USER_AGENT = "agent-offload"


@dataclass(frozen=True)
class Privacy:
    """Что известно об одной модели.

    `None` в поле — не «нет», а «неизвестно»: эти два случая принципиально
    разные, и политика обходится с ними по-разному.
    """

    name: str
    trains: bool | None
    retention_days: int | None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    """Ключ для сопоставления названия из таблицы с идентификатором модели.

    «Beam Free» и `beam-free` приводятся к одному виду. Слово «free»
    **не отбрасывается**: у бесплатного варианта условия бывают другие, и
    сопоставить его со строкой платного значило бы приписать ему чужие гарантии.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse_training(cell: str) -> bool | None:
    value = cell.strip().lower()
    if value.startswith("not used") or value == "no":
        return False
    if value.startswith("yes"):
        return True
    return None


def parse_retention(cell: str) -> int | None:
    """«0 days*» → 0, «30 days» → 30, «Not ZDR» и прочее → неизвестно."""
    match = re.match(r"\s*(\d+)\s*days?\b", cell.lower())
    return int(match.group(1)) if match else None


class _Tables(HTMLParser):
    """Достаёт из страницы все таблицы как списки строк с текстом ячеек."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._depth += 1
            self.tables.append([])
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._depth = max(0, self._depth - 1)
        elif tag == "tr" and self._row is not None:
            if self._row and self.tables:
                self.tables[-1].append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_page(html: str) -> list[Privacy]:
    """Находит таблицу приватности по заголовкам и разбирает её строки."""
    parser = _Tables()
    parser.feed(html)

    found: list[Privacy] = []
    for table in parser.tables:
        if not table:
            continue
        header = [cell.lower() for cell in table[0]]
        if len(header) < 3 or "training" not in header[1] or "retention" not in header[2]:
            continue
        for row in table[1:]:
            if len(row) < 3 or not row[0]:
                continue
            found.append(
                Privacy(
                    name=row[0],
                    trains=parse_training(row[1]),
                    retention_days=parse_retention(row[2]),
                    note=f"{row[1]} / {row[2]}",
                )
            )
    return found


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")


def collect(sources, fetcher=fetch) -> tuple[list[Privacy], list[str]]:
    """Собирает строки со всех страниц. Вторым значением — что не удалось."""
    rows: list[Privacy] = []
    problems: list[str] = []
    for url in sources:
        try:
            page = parse_page(fetcher(url))
        except Exception as error:  # noqa: BLE001 — недоступный источник не должен ронять остальное
            problems.append(f"{url}: {error}")
            continue
        if not page:
            problems.append(f"{url}: таблица приватности не найдена (поменялась вёрстка?)")
        rows.extend(page)
    return rows, problems
