"""Typed README helpers for rubric checkers."""

from __future__ import annotations

from ...models.readme_blocks import ReadmeBlock
from ...models.readme_document import ReadmeDocument, ReadmeSection


def _is_canonical_theory_part(section: ReadmeSection) -> bool:
    return section.level == 3 and section.title.strip().casefold().startswith("2.")


def _is_canonical_practice_task(section: ReadmeSection) -> bool:
    return section.level == 3 and section.title.strip().casefold().startswith("задание ")


def section_content(section: ReadmeSection | None) -> str:
    """Render a section body and children without the section's own heading."""
    if section is None:
        return ""
    blocks: list[str] = []
    body = (section.body or "").strip()
    if body:
        blocks.append(body)
    blocks.extend(child.to_markdown().strip() for child in section.children if child.to_markdown().strip())
    return "\n\n".join(blocks).strip()


def chapter_content(document: ReadmeDocument, chapter_number: int, *, language: str = "ru") -> str:
    """Return one chapter content without its H2 heading."""
    return section_content(document.chapter_section(chapter_number, language=language))


def chapter_sections(document: ReadmeDocument, chapter_number: int, *, language: str = "ru") -> list[ReadmeSection]:
    """Return direct child sections for one typed chapter."""
    chapter = document.chapter_section(chapter_number, language=language)
    return list(chapter.children) if chapter else []


def theory_part_sections(document: ReadmeDocument, *, language: str = "ru") -> list[ReadmeSection]:
    """Return typed theory subsections from Chapter 2."""
    return [
        section
        for section in chapter_sections(document, 2, language=language)
        if _is_canonical_theory_part(section)
    ]


def practice_task_sections(document: ReadmeDocument, *, language: str = "ru") -> list[ReadmeSection]:
    """Return typed practice task sections from Chapter 3."""
    return [
        section
        for section in chapter_sections(document, 3, language=language)
        if _is_canonical_practice_task(section)
    ]


def section_blocks(section: ReadmeSection | None) -> list[ReadmeBlock]:
    """Return typed content blocks for one section."""
    return section.content_blocks() if section else []


def section_artifact_paths(section: ReadmeSection | None) -> list[str]:
    """Return artifact paths inferred by the typed README section model."""
    if section is None:
        return []
    raw_paths = section.metadata.get("artifact_paths") or []
    return [str(path) for path in raw_paths if str(path).strip()]


def chapter_blocks(document: ReadmeDocument, chapter_number: int, *, language: str = "ru") -> list[ReadmeBlock]:
    """Return typed content blocks for one chapter."""
    return section_blocks(document.chapter_section(chapter_number, language=language))


def toc_section(document: ReadmeDocument) -> ReadmeSection | None:
    """Find the document TOC section by localized title fragments."""
    for section in document.sections:
        if section.metadata.get("section_kind") == "toc" and section.level == 2:
            return section
    for fragment in ("Содержание", "Оглавление", "Content", "Table of contents", "Мазмун"):
        section = document.section_by_title_fragment(fragment)
        if section is not None and section.level == 2:
            return section
    return None
