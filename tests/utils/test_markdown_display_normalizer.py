import pytest

from content_gen.utils.markdown_display_normalizer import (
    normalize_flattened_markdown_tables,
    normalize_flattened_mermaid_fences,
    normalize_example_blocks,
    normalize_markdown_display_blocks,
)


def test_normalize_flattened_mermaid_fence_restores_graph_lines():
    md = (
        "<div>```mermaid "
        '%%{init:{"theme":"dark"}}%% %%{init:{"theme":"dark"}}%% '
        "flowchart TD A[Сбор данных] --> B[Проверка качества] "
        "B --> C[Планирование действий] C --> D[Реализация] "
        "```<p>caption</p></div>"
    )

    normalized = normalize_flattened_mermaid_fences(md)

    assert "```mermaid\n" in normalized
    assert normalized.count("%%{init:") == 1
    assert "flowchart TD\n" in normalized
    assert "\n    A[Сбор данных] --> B[Проверка качества]\n" in normalized
    assert "\n    B --> C[Планирование действий]\n" in normalized
    assert "<div>\n```mermaid" in normalized
    assert "\n```" in normalized


def test_normalize_mermaid_splits_unlabeled_node_statement_chains():
    md = """<div>```mermaid
flowchart TD
    E --> F F --> G
```</div>"""

    normalized = normalize_flattened_mermaid_fences(md)

    assert "<div>\n```mermaid" in normalized
    assert "\n    E --> F\n" in normalized
    assert "\n    F --> G\n" in normalized


def test_normalize_mermaid_repairs_missing_closing_fence_before_caption():
    md = (
        "Текст перед диаграммой. ```mermaid\n"
        "flowchart TD\n"
        "A[Старт] --> B[Проверка]\n"
        "B --> C{Готово?}\n"
        "C -- да --> D[Финиш]\n"
        "<p style='text-align:center;font-style:italic;'>Алгоритм проверки</p> </div></div> "
        "**Контекст предыдущих частей:**\n"
        "- Первая часть"
    )

    normalized = normalize_markdown_display_blocks(md)

    assert "Текст перед диаграммой.\n\n```mermaid\n" in normalized
    assert "\n    A[Старт] --> B[Проверка]\n" in normalized
    assert "\n```\n\n*Алгоритм проверки*\n\n**Контекст предыдущих частей:**" in normalized
    assert "<p" not in normalized
    assert "</div>" not in normalized


@pytest.mark.parametrize("boundary", ["Ситуация", "Цель", "Входные данные"])
def test_normalize_mermaid_repairs_missing_closing_fence_before_extended_boundaries(boundary):
    md = (
        "```mermaid\n"
        "flowchart TD\n"
        "A[Старт] --> B[Проверка]\n"
        f"**{boundary}:**\n"
        "Текст следующего блока."
    )

    normalized = normalize_markdown_display_blocks(md)

    assert "```mermaid\nflowchart TD\n    A[Старт] --> B[Проверка]\n```\n" in normalized
    assert f"**{boundary}:**\nТекст следующего блока." in normalized


def test_normalize_flattened_markdown_table_restores_rows_and_caption():
    md = (
        "Ниже показаны категории задач. "
        "| Тип задачи | Описание | Примеры | "
        "|--------------------|----------|----------| "
        "| Аналитические | Работа с исходными данными | Разбор интервью | "
        "| Коммуникационные | Подготовка сообщений | Письмо команде | "
        "*Таблица 1. Категории задач*"
    )

    normalized = normalize_flattened_markdown_tables(md)

    assert "Ниже показаны категории задач.\n\n| Тип задачи | Описание | Примеры |" in normalized
    assert "\n|--------------------|----------|----------|\n" in normalized
    assert "\n| Аналитические | Работа с исходными данными | Разбор интервью |\n" in normalized
    assert "\n\n*Таблица 1. Категории задач*" in normalized


def test_normalize_markdown_display_blocks_keeps_tables_outside_fenced_code_only():
    md = (
        "```text\n"
        "| A | B | |---|---| | 1 | 2 |\n"
        "```\n\n"
        "Таблица: | A | B | |---|---| | 1 | 2 |"
    )

    normalized = normalize_markdown_display_blocks(md)

    assert "```text\n| A | B | |---|---| | 1 | 2 |\n```" in normalized
    assert "Таблица:\n\n| A | B |\n|---|---|\n| 1 | 2 |" in normalized


def test_normalize_example_blocks_separates_inline_example_marker():
    md = (
        "Для этого проекта важно разобраться с дорожной картой без лишнего тумана. "
        "Пример: В 2023 году команда связала задачи с релизными целями."
    )

    normalized = normalize_example_blocks(md)

    assert "тумана.\n\n**Пример:** В 2023" in normalized


def test_normalize_example_blocks_keeps_code_fences_unchanged():
    md = "```text\nПример: это часть кода\n```\n\nТекст.\nПример: это пример теории."

    normalized = normalize_markdown_display_blocks(md)

    assert "```text\nПример: это часть кода\n```" in normalized
    assert "Текст.\n\n**Пример:** это пример теории." in normalized
