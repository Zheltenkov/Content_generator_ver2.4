import re

from content_gen.models.criteria_models import CheckMethod, CriteriaItem
from content_gen.models.readme_document import ReadmeDocument
from content_gen.validators.rubric.chapter2_checker import Chapter2Checker
from content_gen.validators.rubric.chapter3_checker import Chapter3Checker
from content_gen.validators.rubric.document_utils import chapter_content, section_artifact_paths
from content_gen.validators.rubric.section1_checker import Section1Checker
from content_gen.validators.rubric.section2_checker import Section2Checker
from content_gen.validators.rubric.section3_checker import Section3Checker
from content_gen.validators.rubric.section4_checker import Section4Checker
from content_gen.validators.rubric.similarity import SimilarityCalculator
from content_gen.validators.rubric.toc_checker import TOCChecker


def _item(item_id: str) -> CriteriaItem:
    return CriteriaItem(
        id=item_id,
        title=item_id,
        description=item_id,
        check_method=CheckMethod.SCRIPT,
        score=1,
        comments=[],
    )


def test_chapter_content_uses_typed_tree_and_ignores_fenced_headings() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "## Глава 2. Теоретический блок\n\n"
        "```md\n"
        "## Глава 3. Не настоящая глава\n"
        "```\n\n"
        "### 2.1. Настоящий раздел\n\n"
        "Текст."
    )

    assert "Не настоящая глава" in chapter_content(document, 2)
    assert chapter_content(document, 3) == ""


def test_section1_checker_reads_document_structure_without_regex_chapter_scan() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "Аннотация проекта.\n\n"
        "## Содержание\n\n"
        "- [Глава 1](#глава-1)\n- [Глава 2](#глава-2)\n- [Глава 3](#глава-3)\n\n"
        "## Глава 1. Введение и инструкция\n\n"
        f"{'текст ' * 20}### Введение\n\n{'вводная ' * 20}\n\n"
        "## Глава 2. Теоретический блок\n\n"
        f"{'теория ' * 60}\n\n"
        "```md\n## Глава 3. Фальшивая глава\n```\n"
    )

    items = Section1Checker(regex_patterns={}).check_document(document)

    by_id = {item.id: item for item in items}
    assert by_id["1.1"].score == 1
    assert by_id["1.5"].score == 1
    assert by_id["1.6"].score == 0


def test_section2_checker_passes_typed_chapters_to_subcheckers(monkeypatch) -> None:
    checker = Section2Checker(
        regex_patterns={
            "rx_h1": re.compile(r"^#\s+(.+)$", re.M),
            "rx_h2": re.compile(r"^##\s+(.+)$", re.M),
            "rx_h3": re.compile(r"^###\s+(.+)$", re.M),
        }
    )
    captured = {}

    def check_annotation(annotation, title, ch2):
        captured["annotation"] = (annotation, title, ch2)
        return [_item("2.1")]

    def check_chapter1(_document, ch1):
        captured["ch1"] = ch1
        return [_item("2.3")]

    def check_chapter2(_document, ch2, learning_outcomes=None):
        captured["ch2"] = (ch2, learning_outcomes)
        return [_item("2.4")]

    def check_chapter3(_document, ch3, ch2):
        captured["ch3"] = (ch3, ch2)
        return [_item("2.5")]

    monkeypatch.setattr(checker, "_check_annotation", check_annotation)
    monkeypatch.setattr(checker, "_check_toc_document", lambda document, md: [_item("2.2")])
    monkeypatch.setattr(checker, "_check_chapter1_document", check_chapter1)
    monkeypatch.setattr(checker, "_check_chapter2_document", check_chapter2)
    monkeypatch.setattr(checker, "_check_chapter3_document", check_chapter3)
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "Аннотация.\n\n"
        "## Глава 1. Введение\n\n"
        "Текст 1.\n\n"
        "## Глава 2. Теория\n\n"
        "Текст 2.\n\n"
        "## Глава 3. Практика\n\n"
        "Текст 3."
    )

    items = checker.check_document(document, learning_outcomes=["LO"])

    assert [item.id for item in items] == ["2.1", "2.2", "2.3", "2.4", "2.5"]
    assert captured["annotation"] == ("Аннотация.", "Проект", "Текст 2.")
    assert captured["ch1"] == "Текст 1."
    assert captured["ch2"] == ("Текст 2.", ["LO"])
    assert captured["ch3"] == ("Текст 3.", "Текст 2.")


def test_section3_and_section4_expose_typed_entrypoints() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "Аннотация.\n\n"
        "## Глава 1. Введение\n\n"
        "Команда делает один рабочий проект и сохраняет контекст.\n\n"
        "## Глава 2. Теория\n\n"
        "Теория объясняет тот же рабочий проект и решения команды.\n\n"
        "## Глава 3. Практика\n\n"
        "Практика продолжает этот проект и просит показать результат."
    )
    section3 = Section3Checker(SimilarityCalculator(embedding_function=None, language="ru"))
    section4 = Section4Checker(regex_patterns={})

    section3_items = section3.check_document(document)
    section4_items = section4.check_document(document)

    assert {item.id for item in section3_items} == {"3.1", "3.2"}
    assert {item.id for item in section4_items} == {"4.1", "4.2", "4.3"}


def test_toc_checker_uses_typed_toc_and_headings_without_regex_patterns() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "Аннотация.\n\n"
        "## Содержание\n\n"
        "- [Глава 1. Введение](#глава-1-введение)\n"
        "  - [Введение](#введение)\n"
        "- [Глава 2. Теория](#глава-2-теория)\n"
        "  - [2.1. Основы](#21-основы)\n"
        "- [Глава 3. Практика](#глава-3-практика)\n"
        "  - [Задание 1. Артефакт](#задание-1-артефакт)\n\n"
        "## Глава 1. Введение\n\n"
        "### Введение\n\n"
        "Введение объясняет проект.\n\n"
        "## Глава 2. Теория\n\n"
        "### 2.1. Основы\n\n"
        "Основы объясняют теорию.\n\n"
        "## Глава 3. Практика\n\n"
        "### Задание 1. Артефакт\n\n"
        "Практика продолжает проект."
    )

    items = TOCChecker(regex_patterns={}).check_document(document)

    by_id = {item.id: item for item in items}
    assert by_id["2.2.1"].score == 1
    assert by_id["2.2.2"].score == 1
    assert by_id["2.2.3"].score == 1


def test_chapter2_checker_uses_typed_theory_sections_without_regex_patterns() -> None:
    repeated_text = (
        "**Термин** — это понятие, которое помогает описать рабочий процесс. "
        "Пример: команда сверяет решение с требованиями и фиксирует выводы. "
    )
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "## Глава 2. Теория\n\n"
        "### 2.1. Первый раздел\n\n"
        f"{repeated_text * 25}\n\n"
        "**Пример:** команда проверяет артефакт.\n\n"
        "### 2.2. Второй раздел\n\n"
        f"{repeated_text * 25}\n\n"
        "**Пример:** команда проверяет артефакт.\n\n"
        "### 2.3. Третий раздел\n\n"
        f"{repeated_text * 25}\n\n"
        "**Пример:** команда проверяет артефакт."
    )

    items = Chapter2Checker(regex_patterns={}).check_document(document)

    by_id = {item.id: item for item in items}
    assert by_id["2.4.1"].score == 1
    assert by_id["2.4.4"].score == 1
    assert by_id["2.4.6"].score == 1


def test_chapter3_checker_uses_typed_task_sections_without_resplitting(monkeypatch) -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "## Глава 2. Теория\n\n"
        "Теория про карту рисков и проверяемые артефакты.\n\n"
        "## Глава 3. Практика\n\n"
        "### Задание 1. Карта рисков\n\n"
        "**Что нужно сделать:**\n"
        "Цель: разработать карту рисков для проекта.\n"
        "- Сопоставь риск с причиной.\n"
        "- Зафиксируй действие команды.\n\n"
        "**Что должно получиться:**\n"
        "- В таблице перечислены риски.\n"
        "- Указан путь `Project/part-03/task-01/risks.md`.\n"
        "- Есть объяснение решения.\n\n"
        "**Формат сдачи:** файл `Project/part-03/task-01/risks.md`."
    )
    checker = Chapter3Checker(regex_patterns={})

    monkeypatch.setattr(checker, "_split_tasks", lambda _text: (_ for _ in ()).throw(AssertionError("markdown split used")))

    items = checker.check_document(document)

    assert {item.id for item in items} == {"2.5.1", "2.5.2", "2.5.3", "2.5.4", "2.5.5", "2.5.6", "2.5.7"}


def test_chapter3_checker_uses_typed_artifact_paths_from_section_metadata() -> None:
    document = ReadmeDocument.from_markdown(
        "# Проект\n\n"
        "## Глава 2. Теория\n\n"
        "Теория про риск проектного решения и проверяемые артефакты.\n\n"
        "## Глава 3. Практика\n\n"
        "### Задание 1. Карта рисков\n\n"
        "**Что нужно сделать:**\n"
        "Ситуация: команда видит риск в проекте и должна подготовить проверяемый артефакт.\n"
        "Цель: разработать карту рисков для проекта.\n"
        "Подход:\n"
        "- Сопоставь риск с причиной.\n"
        "- Зафиксируй действие команды.\n\n"
        "**Что должно получиться:**\n"
        "- В таблице перечислены риски.\n"
        "- В документе указаны причины.\n"
        "- Есть объяснение решения.\n\n"
        "**Формат сдачи:** файл `Project/part-03/task-01/risks.md`.\n"
    )
    task = document.chapter_section(3).children[0]

    assert section_artifact_paths(task) == ["Project/part-03/task-01/risks.md"]

    items = Chapter3Checker(regex_patterns={}).check_document(document)
    by_id = {item.id: item for item in items}

    assert by_id["2.5.5"].score == 1
    assert by_id["2.5.6"].score == 1
