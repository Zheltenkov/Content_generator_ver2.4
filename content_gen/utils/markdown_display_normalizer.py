"""
Deterministic repair for Markdown display blocks.

LLM editing passes can occasionally flatten Markdown tables and Mermaid fences
into a single physical line. That keeps the text readable as prose, but breaks
the UI renderer and exported README files. This module restores display block
boundaries without changing the educational content.
"""

from __future__ import annotations

import re
from collections.abc import Callable


_FENCED_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_MERMAID_FENCE_RE = re.compile(r"```mermaid\s+([\s\S]*?)```", re.IGNORECASE)
_MERMAID_OPEN_RE = re.compile(r"```mermaid\b[ \t]*", re.IGNORECASE)
_MERMAID_BOUNDARY_RE = re.compile(
    r"(?=\n\s*(?:"
    r"<p\b[^>]*text-align\s*:\s*center"
    r"|\*\*(?:Контекст|Пример|Вопросы|Практика|Ожидаемый|Критерии|Ситуация|Ограничение|Входные данные|Цель|Подход)\b"
    r"|#{1,6}\s+"
    r"))",
    re.IGNORECASE,
)
_MERMAID_INIT_RE = re.compile(r"%%\{init:[\s\S]*?\}%%", re.IGNORECASE)
_HTML_CENTER_CAPTION_RE = re.compile(
    r"\s*<p\b[^>]*text-align\s*:\s*center[^>]*>([\s\S]*?)</p>\s*(?:</div>\s*)*",
    re.IGNORECASE,
)
_GRAPH_DECL_RE = re.compile(
    r"\b((?:flowchart|graph)\s+(?:TB|TD|BT|RL|LR))\s+(?=\S)",
    re.IGNORECASE,
)
_SINGLE_DECL_RE = re.compile(
    r"\b(sequenceDiagram|stateDiagram-v2|stateDiagram|classDiagram|erDiagram|journey|gantt|pie)\s+(?=\S)",
    re.IGNORECASE,
)
_EDGE_SOURCE_RE = re.compile(
    r"((?:[\]\)\}]|\b[A-Za-z][A-Za-z0-9_]*))\s+"
    r"(?=[A-Za-z][A-Za-z0-9_]*\s*(?:-->|---|-\.->|-\.|==>|--|==))"
)
_MERMAID_NODE_TOKEN = (
    r"[A-Za-z][A-Za-z0-9_]*"
    r"(?:\s*(?:\[[^\]\n]*\]|\([^\)\n]*\)|\{[^\}\n]*\}))?"
)
_MERMAID_LABEL_EDGE_REPAIRS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"^({_MERMAID_NODE_TOKEN})\s*-\.\s*([^|<>\n]+?)\s*\.->\s*({_MERMAID_NODE_TOKEN})$"
        ),
        "-.->",
    ),
    (
        re.compile(
            rf"^({_MERMAID_NODE_TOKEN})\s*--\s*([^|<>\n]+?)\s*-->\s*({_MERMAID_NODE_TOKEN})$"
        ),
        "-->",
    ),
    (
        re.compile(
            rf"^({_MERMAID_NODE_TOKEN})\s*==\s*([^|<>\n]+?)\s*==>\s*({_MERMAID_NODE_TOKEN})$"
        ),
        "==>",
    ),
)
_STRAY_LEADING_SENTENCE_DOT_RE = re.compile(
    r"(^|\n)([ \t]*)\.\s+(?=(?:\*\*)?[A-ZА-ЯЁ])"
)
_FLATTENED_TABLE_RE = re.compile(r"\|\s+(?=\|)")
_TABLE_SEPARATOR_RE = re.compile(r"\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|")
_EXAMPLE_MARKER_RE = re.compile(r"(?<!\*)\bПример\s*:", re.IGNORECASE)
_PROTECTED_BLOCK_COMMENT_RE = re.compile(
    r"<!--\s*PROTECTED_BLOCK\b[\s\S]*?-->\s*",
    re.IGNORECASE,
)
_PROTECTED_INSTRUCTION_PATTERNS = [
    re.compile(
        r"\s*(?:и\s+)?комментарии\s+PROTECTED_BLOCK\s*\.?\s*"
        r"Это защищ[её]нные таблицы,\s*диаграммы,\s*формулы или код\.?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*КРИТИЧЕСКИ ВАЖНО:\s*-\s*Сохрани все маркеры\s*"
        r"\[\[\[BLOCK_\d+\]\]\]\s*без изменений\.?\s*"
        r"-\s*Сохрани комментарии\s+PROTECTED_BLOCK\s+без изменений\.?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*Сохрани все маркеры\s*\[\[\[BLOCK_\d+\]\]\]\s*без изменений\.?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*Сохрани комментарии\s+PROTECTED_BLOCK\s+без изменений\.?",
        re.IGNORECASE,
    ),
]


def _strip_html_tags(value: str) -> str:
    """Remove simple HTML tags from display captions."""
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _unique_preserve_order(values: list[str]) -> list[str]:
    """Return unique values while preserving first occurrence order."""
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = re.sub(r"\s+", "", value.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _normalize_mermaid_code(code: str) -> str:
    """Restore Mermaid code line boundaries and remove duplicate init blocks."""
    raw = (code or "").strip()
    if not raw:
        return ""

    init_directives = _unique_preserve_order(_MERMAID_INIT_RE.findall(raw))
    body = _MERMAID_INIT_RE.sub(" ", raw)
    body = re.sub(r"[ \t]+", " ", body).strip()

    # A flattened flowchart usually looks like: "flowchart TD A[...] --> B[...]".
    # Mermaid requires the diagram declaration and statements on separate lines.
    body = _GRAPH_DECL_RE.sub(r"\1\n    ", body, count=1)
    body = _SINGLE_DECL_RE.sub(r"\1\n    ", body, count=1)

    # Split consecutive statements: "... B[Label] B --> C[Label]".
    body = _EDGE_SOURCE_RE.sub(r"\1\n    ", body)

    lines: list[str] = []
    if init_directives:
        lines.append(init_directives[0].strip())

    for line in body.splitlines():
        cleaned = line.strip()
        if cleaned:
            cleaned = _normalize_mermaid_edge_label_line(cleaned)
            lines.append(cleaned if cleaned.startswith("%%{") else f"    {cleaned}" if lines and not cleaned.startswith(("flowchart", "graph", "sequenceDiagram", "stateDiagram", "classDiagram", "erDiagram", "journey", "gantt", "pie")) else cleaned)

    return "\n".join(lines).strip()


def _clean_mermaid_edge_label(label: str) -> str:
    """Prepare a human label for Mermaid pipe-label edge syntax."""
    cleaned = re.sub(r"\s+", " ", label or "").strip().strip(".:;—–- ")
    return cleaned.replace("|", "/")


def _normalize_mermaid_edge_label_line(line: str) -> str:
    """Convert fragile prose edge labels to Mermaid pipe-label syntax."""
    text = (line or "").strip()
    if not text or "|" in text:
        return text

    for pattern, arrow in _MERMAID_LABEL_EDGE_REPAIRS:
        match = pattern.match(text)
        if not match:
            continue
        source, raw_label, target = match.groups()
        label = _clean_mermaid_edge_label(raw_label)
        if not label:
            return text
        return f"{source.strip()} {arrow}|{label}| {target.strip()}"

    return text


def _repair_unclosed_mermaid_fences(markdown: str) -> str:
    """Close Mermaid fences flattened by HTML wrappers or LLM editors."""
    text = markdown or ""
    output: list[str] = []
    pos = 0

    while True:
        match = _MERMAID_OPEN_RE.search(text, pos)
        if not match:
            output.append(text[pos:])
            break

        output.append(text[pos:match.end()])
        output.append("\n")
        code_start = match.end()
        explicit_close = text.find("```", code_start)
        boundary_match = _MERMAID_BOUNDARY_RE.search(text, code_start)
        boundary = boundary_match.start() if boundary_match else -1

        if explicit_close >= 0 and (boundary < 0 or explicit_close < boundary):
            output.append(text[code_start:explicit_close + 3])
            pos = explicit_close + 3
            continue

        code_end = boundary if boundary >= 0 else len(text)
        output.append(text[code_start:code_end].strip())
        output.append("\n```\n")
        pos = code_end

    repaired = "".join(output)
    repaired = _HTML_CENTER_CAPTION_RE.sub(
        lambda m: f"\n\n*{_strip_html_tags(m.group(1))}*\n\n",
        repaired,
    )
    return repaired


def normalize_flattened_mermaid_fences(markdown: str) -> str:
    """Ensure Mermaid fences always contain multiline Mermaid code."""
    def replace(match: re.Match[str]) -> str:
        code = _normalize_mermaid_code(match.group(1))
        if not code:
            return match.group(0)
        return f"\n```mermaid\n{code}\n```\n"

    text = _repair_unclosed_mermaid_fences(markdown or "")
    text = _MERMAID_FENCE_RE.sub(replace, text)
    # A fence must start on its own line for Markdown renderers. This also
    # repairs HTML wrappers such as "<div>```mermaid".
    text = re.sub(r"([^\n])([ \t]*```mermaid)", r"\1\n\n```mermaid", text, flags=re.IGNORECASE)
    return text


def _looks_like_flattened_table(line: str) -> bool:
    """Check whether a physical line contains a flattened Markdown table."""
    if line.count("|") < 6:
        return False
    return bool(_FLATTENED_TABLE_RE.search(line) and _TABLE_SEPARATOR_RE.search(line))


def _repair_flattened_table_line(line: str) -> list[str]:
    """Split one flattened Markdown table line into Markdown table rows."""
    first_pipe = line.find("|")
    if first_pipe < 0:
        return [line]

    prefix = line[:first_pipe].rstrip()
    table_text = line[first_pipe:].strip()
    table_text = _FLATTENED_TABLE_RE.sub("|\n", table_text)

    repaired: list[str] = []
    if prefix:
        repaired.extend([prefix, ""])

    trailing: list[str] = []
    for raw_row in table_text.splitlines():
        row = raw_row.rstrip()
        if not row:
            continue
        if not row.lstrip().startswith("|"):
            trailing.append(row.strip())
            continue

        last_pipe = row.rfind("|")
        if last_pipe <= 0:
            repaired.append(row)
            continue

        core = row[: last_pipe + 1].rstrip()
        suffix = row[last_pipe + 1 :].strip()
        if core:
            repaired.append(core)
        if suffix:
            trailing.append(suffix)

    if trailing:
        repaired.append("")
        repaired.extend(trailing)

    return repaired or [line]


def _normalize_tables_chunk(markdown: str) -> str:
    """Normalize flattened Markdown tables in a non-code chunk."""
    output: list[str] = []
    for line in (markdown or "").splitlines():
        if _looks_like_flattened_table(line):
            output.extend(_repair_flattened_table_line(line))
        else:
            output.append(line)
    return "\n".join(output)


def _apply_outside_fenced_blocks(markdown: str, transform: Callable[[str], str]) -> str:
    """Apply a transform only outside fenced code blocks."""
    text = markdown or ""
    parts: list[str] = []
    pos = 0
    for match in _FENCED_BLOCK_RE.finditer(text):
        parts.append(transform(text[pos : match.start()]))
        parts.append(match.group(0))
        pos = match.end()
    parts.append(transform(text[pos:]))
    return "".join(parts)


def normalize_flattened_markdown_tables(markdown: str) -> str:
    """Restore Markdown table row boundaries outside fenced code blocks."""
    return _apply_outside_fenced_blocks(markdown or "", _normalize_tables_chunk)


def _normalize_example_marker_chunk(markdown: str) -> str:
    """Make theory examples a separate Markdown block after LLM rewrites."""
    text = _EXAMPLE_MARKER_RE.sub("**Пример:**", markdown or "")
    text = re.sub(r"\n{1,2}\s*\*\*Пример:\*\*", "\n\n**Пример:**", text)
    text = re.sub(r"([^\n])\s+\*\*Пример:\*\*", r"\1\n\n**Пример:**", text)
    return text


def normalize_example_blocks(markdown: str) -> str:
    """Ensure ``Пример`` markers are visually separated from preceding prose."""
    return _apply_outside_fenced_blocks(markdown or "", _normalize_example_marker_chunk)


def normalize_stray_leading_sentence_dots(markdown: str) -> str:
    """Remove a single stray dot that can remain after extracting a caption."""
    return _apply_outside_fenced_blocks(
        markdown or "",
        lambda chunk: _STRAY_LEADING_SENTENCE_DOT_RE.sub(r"\1\2", chunk),
    )


def strip_protected_block_instruction_leaks(markdown: str) -> str:
    """Remove internal protected-block instructions leaked into user-visible README prose."""
    def transform(chunk: str) -> str:
        text = _PROTECTED_BLOCK_COMMENT_RE.sub("", chunk or "")
        for pattern in _PROTECTED_INSTRUCTION_PATTERNS:
            text = pattern.sub(" ", text)
        text = re.sub(r"\[\[\[BLOCK_\d+\]\]\]", "", text)
        text = re.sub(r"\bPROTECTED_BLOCK\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\s+([.,;:!?])", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    return _apply_outside_fenced_blocks(markdown or "", transform)


def normalize_markdown_display_blocks(markdown: str) -> str:
    """Repair display-oriented Markdown blocks after model-based editing."""
    text = normalize_flattened_mermaid_fences(markdown or "")
    text = normalize_flattened_markdown_tables(text)
    text = re.sub(r"([^\n])([ \t]*```mermaid)", r"\1\n\n```mermaid", text, flags=re.IGNORECASE)
    text = normalize_example_blocks(text)
    text = normalize_stray_leading_sentence_dots(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
