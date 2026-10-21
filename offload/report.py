"""Parsing the executor's report.

The format is fixed by `.offload/protocol.md`: DONE / VERIFIED / NOT DONE /
DECISIONS / BLOCKERS. Models wrap it in markdown, repeat a header per line, or
add a sentence before it, so parsing is tolerant. What it must never do is
invent content: a missing section stays missing.
"""

from __future__ import annotations

import re

SECTIONS = ("DONE", "VERIFIED", "NOT DONE", "DECISIONS", "BLOCKERS")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_HEADER = re.compile(
    # The colon is optional when the header stands alone on its line: models write
    # both "DONE: x" and a bare "DONE" followed by the body on the next line.
    r"^[ \t>*_`#-]*(" + "|".join(SECTIONS) + r")[*_`]*[ \t]*(?::[*_`]*[ \t]*|$)",
    re.MULTILINE,
)


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def parse(text: str) -> dict[str, str]:
    """Section name -> text. Repeated headers are joined, one per line."""
    text = strip_ansi(text)
    matches = list(_HEADER.finditer(text))
    found: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        found.setdefault(match.group(1), []).append(body)
    return {name: "\n".join(parts).strip() for name, parts in found.items()}


def is_well_formed(sections: dict[str, str]) -> bool:
    """A report that skips DONE or VERIFIED cannot be acted on."""
    return "DONE" in sections and "VERIFIED" in sections


def clip(text: str, limit: int = 600) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " ..."
