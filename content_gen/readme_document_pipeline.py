"""Typed README update helpers used while legacy phases still return Markdown."""

from __future__ import annotations

import re

from .models.readme_document import ReadmeDocument, ReadmeSection
from .utils.markdown_helpers import replace_chapter_content


def replace_readme_chapter_body_document(
    document: ReadmeDocument,
    chapter_number: int,
    body: str,
    *,
    language: str = "ru",
) -> tuple[ReadmeDocument, bool]:
    """Replace one chapter body in a typed README document."""
    return document.with_replaced_chapter_body(
        chapter_number,
        body,
        language=language,
    )


def replace_readme_chapter_children_document(
    document: ReadmeDocument,
    chapter_number: int,
    children: list[ReadmeSection],
    *,
    chapter_body: str = "",
    language: str = "ru",
) -> tuple[ReadmeDocument, bool]:
    """Replace one chapter with already materialized typed child sections."""
    return document.with_replaced_chapter_children(
        chapter_number,
        children,
        chapter_body=chapter_body,
        language=language,
    )


def replace_readme_chapter_body(
    markdown: str,
    chapter_number: int,
    body: str,
    *,
    language: str = "ru",
) -> str:
    """Replace a chapter through ReadmeDocument and fall back to legacy regex logic.

    The production skeleton has an explicit H1, so rendering from the typed
    document preserves the README contract. Old tests and partial snippets may
    start directly from H2; those stay on the Markdown-boundary path to avoid injecting a
    synthetic README title.
    """
    if not _has_explicit_h1(markdown):
        return replace_chapter_content(markdown, chapter_number, body, language)

    document = ReadmeDocument.from_markdown(markdown)
    updated, changed = document.with_replaced_chapter_body(
        chapter_number,
        body,
        language=language,
    )
    if not changed:
        return replace_chapter_content(markdown, chapter_number, body, language)
    return updated.to_markdown()


def update_readme_bonus_section_document(
    document: ReadmeDocument,
    bonus_body: str,
    *,
    language: str = "ru",
) -> ReadmeDocument:
    """Upsert or remove the optional bonus section in a typed README document."""
    fragment = _bonus_title_fragment(language)
    bonus_body = (bonus_body or "").strip()
    if not bonus_body:
        updated, _removed = document.without_section_by_title_fragment(fragment)
        return updated

    existing = document.section_by_title_fragment(fragment)
    title = existing.title if existing else _bonus_section_title(language)
    return document.with_upserted_section_by_title_fragment(
        fragment,
        f"## {title}\n\n{bonus_body}",
        fallback_level=2,
    )


def update_readme_bonus_section_children_document(
    document: ReadmeDocument,
    children: list[ReadmeSection],
    *,
    language: str = "ru",
) -> ReadmeDocument:
    """Upsert or remove the optional bonus section from typed child sections."""
    fragment = _bonus_title_fragment(language)
    if not children:
        updated, _removed = document.without_section_by_title_fragment(fragment)
        return updated

    existing = document.section_by_title_fragment(fragment)
    title = existing.title if existing else _bonus_section_title(language)
    bonus_section = ReadmeSection(
        title=title,
        level=2,
        children=[child.model_copy(deep=True) for child in children],
    )
    return document.with_upserted_section_by_title_fragment(
        fragment,
        bonus_section,
        fallback_level=2,
    )


def _has_explicit_h1(markdown: str) -> bool:
    """Detect whether Markdown can safely be rendered as a full typed README."""
    return bool(re.search(r"^#\s+.+$", markdown or "", flags=re.MULTILINE))


def _bonus_title_fragment(language: str) -> str:
    """Return the public bonus section title fragment for the target language."""
    normalized = (language or "ru").casefold().strip()
    if normalized == "en":
        return "Bonus"
    return "Бонус"


def _bonus_section_title(language: str) -> str:
    """Return a default bonus section title when the skeleton lacks one."""
    normalized = (language or "ru").casefold().strip()
    if normalized == "en":
        return "Bonus"
    return "Бонус"
