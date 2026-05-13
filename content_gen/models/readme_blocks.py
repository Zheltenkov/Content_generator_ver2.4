"""Typed README content blocks extracted from section bodies."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReadmeBlockKind(str, Enum):
    """Supported structured block kinds inside README sections."""

    MERMAID = "mermaid"
    TABLE = "table"
    FORMULA = "formula"


class ReadmeBlock(BaseModel):
    """Structured block extracted from Markdown without changing the source."""

    model_config = ConfigDict(extra="forbid")

    kind: ReadmeBlockKind
    source: str
    content: str = ""
    caption: str = ""
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    section_title: str = ""
    section_path: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_markdown(self) -> str:
        """Return the original Markdown source for the block."""
        return self.source

    def with_section(self, title: str, path: list[str]) -> "ReadmeBlock":
        """Attach section location metadata to the extracted block."""
        return self.model_copy(
            update={
                "section_title": title,
                "section_path": list(path),
            }
        )


_MERMAID_RE = re.compile(
    r"(?P<source>(?P<fence>`{3,}|~{3,})mermaid[^\n]*\n(?P<content>[\s\S]*?)\n(?P=fence))",
    flags=re.IGNORECASE,
)
_FORMULA_RE = re.compile(r"(?P<source>\$\$\s*\n?(?P<content>[\s\S]*?)\n?\$\$)")
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_CAPTION_RE = re.compile(
    r"^\s*(?:_(?P<italic>[^_\n]{3,160})_|\*(?P<star>[^*\n]{3,160})\*|(?P<label>(?:Рисунок|Диаграмма|Таблица|Formula|Figure|Table)\s*[:.]\s*[^\n]{3,160}))\s*$",
    flags=re.IGNORECASE,
)


def extract_readme_blocks(markdown: str) -> list[ReadmeBlock]:
    """Extract typed Mermaid, formula, and Markdown table blocks from Markdown."""
    text = (markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[ReadmeBlock] = []
    occupied: list[tuple[int, int]] = []

    for match in _MERMAID_RE.finditer(text):
        block = ReadmeBlock(
            kind=ReadmeBlockKind.MERMAID,
            source=match.group("source"),
            content=match.group("content").strip(),
            caption=_caption_near(text, match.start(), match.end()),
            start=match.start(),
            end=match.end(),
        )
        blocks.append(block)
        occupied.append((match.start(), match.end()))

    for match in _FORMULA_RE.finditer(text):
        if _overlaps(match.start(), match.end(), occupied):
            continue
        block = ReadmeBlock(
            kind=ReadmeBlockKind.FORMULA,
            source=match.group("source"),
            content=match.group("content").strip(),
            caption=_caption_near(text, match.start(), match.end()),
            start=match.start(),
            end=match.end(),
        )
        blocks.append(block)
        occupied.append((match.start(), match.end()))

    for start, end in _table_spans(text):
        if _overlaps(start, end, occupied):
            continue
        source = text[start:end].strip("\n")
        block = ReadmeBlock(
            kind=ReadmeBlockKind.TABLE,
            source=source,
            content=source,
            caption=_caption_near(text, start, end),
            start=start,
            end=end,
            metadata={"rows": max(0, len(source.splitlines()) - 2)},
        )
        blocks.append(block)
        occupied.append((start, end))

    return sorted(blocks, key=lambda item: item.start)


def block_counts(blocks: list[ReadmeBlock]) -> dict[str, int]:
    """Return stable block counts keyed by block kind value."""
    counts = {kind.value: 0 for kind in ReadmeBlockKind}
    for block in blocks:
        counts[block.kind.value] = counts.get(block.kind.value, 0) + 1
    return counts


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _table_spans(text: str) -> list[tuple[int, int]]:
    """Find Markdown table spans outside fenced code blocks."""
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)

    spans: list[tuple[int, int]] = []
    in_fence: str | None = None
    index = 0
    while index < len(lines):
        stripped_line = lines[index].rstrip("\n")
        fence_match = _FENCE_RE.match(stripped_line)
        if fence_match:
            fence_marker = fence_match.group(1)[:3]
            in_fence = None if in_fence == fence_marker else fence_marker if in_fence is None else in_fence
            index += 1
            continue

        if (
            in_fence is None
            and index + 1 < len(lines)
            and _TABLE_ROW_RE.match(stripped_line)
            and _TABLE_SEPARATOR_RE.match(lines[index + 1].rstrip("\n"))
        ):
            start = offsets[index]
            end_index = index + 2
            while end_index < len(lines) and _TABLE_ROW_RE.match(lines[end_index].rstrip("\n")):
                end_index += 1
            end = offsets[end_index] if end_index < len(offsets) else len(text)
            spans.append((start, end))
            index = end_index
            continue

        index += 1
    return spans


def _caption_near(text: str, start: int, end: int) -> str:
    """Return a short caption immediately before or after a block."""
    after = _first_non_empty_line(text[end:])
    if after and (match := _CAPTION_RE.match(after)):
        return _caption_match_text(match)

    before = _last_non_empty_line(text[:start])
    if before and (match := _CAPTION_RE.match(before)):
        return _caption_match_text(match)
    return ""


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _caption_match_text(match: re.Match[str]) -> str:
    return next((group.strip() for group in match.groups() if group), "")
