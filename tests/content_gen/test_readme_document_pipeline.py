from content_gen.models.readme_document import ReadmeDocument, ReadmeSection
from content_gen.readme_document_pipeline import (
    replace_readme_chapter_body,
    replace_readme_chapter_body_document,
    replace_readme_chapter_children_document,
    update_readme_bonus_section_children_document,
    update_readme_bonus_section_document,
)


def test_readme_document_pipeline_replaces_chapter_body_without_losing_document_shape() -> None:
    markdown = (
        "# Проект\n\n"
        "Аннотация.\n\n"
        "## Содержание\n\n"
        "- [Глава 2](#глава-2)\n\n"
        "## Глава 2. Теоретический блок\n\n"
        "Черновик.\n\n"
        "## Глава 3. Практический блок\n\n"
        "Практика."
    )

    updated = replace_readme_chapter_body(
        markdown,
        2,
        "Новая теория.\n\n### 2.1. Контекст\n\nДетали.",
        language="ru",
    )

    assert updated.startswith("# Проект")
    assert "## Содержание" in updated
    assert "Черновик." not in updated
    assert "### 2.1. Контекст" in updated
    assert "## Глава 3. Практический блок" in updated


def test_readme_document_pipeline_keeps_partial_h2_snippets_on_legacy_path() -> None:
    markdown = "## Глава 3. Практический блок\n\nЧерновик\n\n## Бонус\n\nЧерновик"

    updated = replace_readme_chapter_body(markdown, 3, "### Задание 1. Тест", language="ru")

    assert not updated.startswith("# README")
    assert "### Задание 1. Тест" in updated
    assert "## Бонус" in updated


def test_readme_document_pipeline_updates_chapter_as_document() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "Аннотация.\n\n"
        "## Глава 2. Теоретический блок\n\n"
        "Черновик.\n\n"
        "## Глава 3. Практический блок\n\n"
        "Практика."
    )

    updated, changed = replace_readme_chapter_body_document(
        document,
        2,
        "Новая теория.\n\n### 2.1. Контекст\n\nДетали.",
        language="ru",
    )

    assert changed is True
    assert updated.section_by_title_fragment("2.1").body == "Детали."
    assert document.section_by_title_fragment("2.1") is None


def test_readme_document_pipeline_updates_chapter_from_typed_children() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "## Глава 3. Практический блок\n\n"
        "Черновик.\n\n"
        "### Задание 0. Старое\n\n"
        "Удалить."
    )
    task = ReadmeSection(title="Задание 1. Новое", level=3, body="Новый текст.")

    updated, changed = replace_readme_chapter_children_document(document, 3, [task], language="ru")

    assert changed is True
    assert updated.section_by_title_fragment("Задание 1").body == "Новый текст."
    assert updated.section_by_title_fragment("Задание 0") is None


def test_readme_document_pipeline_upserts_and_removes_bonus_section_as_document() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "Аннотация.\n\n"
        "## Глава 3. Практический блок\n\n"
        "Практика.\n\n"
        "## Бонус\n\n"
        "Черновик."
    )

    updated = update_readme_bonus_section_document(document, "### Бонусное задание 1*. Расширить")
    removed = update_readme_bonus_section_document(updated, "")

    assert "### Бонусное задание 1*. Расширить" in updated.to_markdown()
    assert removed.section_by_title_fragment("Бонус") is None


def test_readme_document_pipeline_upserts_bonus_from_typed_children() -> None:
    document = ReadmeDocument.from_markdown("# Проект\n\n## Глава 3. Практика\n\nТекст.")
    bonus = ReadmeSection(title="Бонусное задание 1*. Расширить", level=3, body="Бонусный текст.")

    updated = update_readme_bonus_section_children_document(document, [bonus])
    removed = update_readme_bonus_section_children_document(updated, [])

    assert updated.section_by_title_fragment("Бонусное задание").body == "Бонусный текст."
    assert removed.section_by_title_fragment("Бонус") is None
