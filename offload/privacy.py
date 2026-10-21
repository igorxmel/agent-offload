"""Model data-handling terms, taken from the official page.

The repository contains no model name and no verdict about one: the model list
and its terms change without notice, and anything hardcoded would go stale within
a week. The page is a source of facts, not of instructions: only the named table
fields are extracted, everything else is ignored.

Parsing is deliberately strict. If the layout changed and the table is not
recognised there are no rows at all, and a model with no privacy data counts as
denied (see `policy`). A broken parser therefore closes access instead of opening it.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser

# The page with the table. This is a pointer, not data, and it lives in the
# settings: this is only the fallback for when none are set.
DEFAULT_SOURCES = ("https://opencode.ai/v2/docs/console/go/",)

TIMEOUT = 20
USER_AGENT = "agent-offload"


@dataclass(frozen=True)
class Privacy:
    """What is known about one model.

    `None` in a field means "unknown", not "no": the two are fundamentally
    different, and the policy treats them differently.
    """

    name: str
    trains: bool | None
    retention_days: int | None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    """Key for matching a table name against a model identifier.

    "Beam Free" and `beam-free` reduce to the same form. The word "free" is
    **not stripped**: a free variant can have different terms, and matching it
    to the paid row would attribute guarantees it may not have.
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
    """"0 days*" -> 0, "30 days" -> 30, "Not ZDR" and anything else -> unknown."""
    match = re.match(r"\s*(\d+)\s*days?\b", cell.lower())
    return int(match.group(1)) if match else None


class _Tables(HTMLParser):
    """Extracts every table on the page as lists of rows of cell text."""

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
    """Finds the privacy table by its headers and parses its rows."""
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
    """Gathers rows from every page. The second value lists what failed."""
    rows: list[Privacy] = []
    problems: list[str] = []
    for url in sources:
        try:
            page = parse_page(fetcher(url))
        except Exception as error:  # noqa: BLE001 - one unreachable source must not sink the rest
            problems.append(f"{url}: {error}")
            continue
        if not page:
            problems.append(f"{url}: privacy table not found (layout changed?)")
        rows.extend(page)
    return rows, problems
