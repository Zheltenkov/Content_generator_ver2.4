"""Tests for Chapter3Checker contract alignment and stability."""

import re

from content_gen.validators.rubric.chapter3_checker import Chapter3Checker


def _get_item(items, item_id: str):
    return next(item for item in items if item.id == item_id)


def test_light_task_format_satisfies_goal_and_approach_checks():
    checker = Chapter3Checker(llm_client=None, embedding_function=None, language="ru")
    ch3 = (
        "### Задание 1. Настройка окружения\n\n"
        "**Ситуация:** Команда получила новый проект и не может начать работу, пока базовое окружение не приведено в рабочее состояние. Если не сделать это сейчас, дальнейшие шаги будут нестабильны.\n\n"
        "**Входные данные:** Базовый шаблон проекта и инструкция по запуску — см. файл `materials/setup_notes.md`\n\n"
        "**Цель:** Настрой рабочее окружение проекта и проверь базовый запуск.\n\n"
        "**Подход:**\n"
        "- Собери список обязательных зависимостей и параметров окружения.\n"
        "- Проверь запуск шаблона и зафиксируй, что нужно команде для старта.\n\n"
        "**Ожидаемый результат:** Файл `PjM20_FrontBack/part-03/task-01/README.md` с инструкцией по запуску и проверкой окружения.\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] В документе указан состав окружения.\n"
        "- [ ] Зафиксирован способ проверки базового запуска.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )

    items = checker.check(ch3, ch2_content="## Глава 2\n### 2.1. Основы\n")
    assert _get_item(items, "2.5.2").score == 1
    assert _get_item(items, "2.5.3").score == 1
    assert _get_item(items, "2.5.4").score == 1


def test_canonical_pdf_task_template_satisfies_structure_result_and_p2p_checks():
    checker = Chapter3Checker(llm_client=None, embedding_function=None, language="ru")
    ch3 = (
        "### Задание 1. Карта решений\n\n"
        "**Что нужно сделать**\n\n"
        "Ситуация: Команда выбирает решение для первого релиза, но критерии спорные и результат должен быть проверяемым.\n\n"
        "Исходные данные: Сырые заметки — см. файл `materials/task_01_source_notes.md`\n\n"
        "Цель: Сопоставь варианты решений и подготовь карту выбора.\n\n"
        "Подход:\n"
        "- Выдели критерии выбора.\n"
        "- Сравни варианты по влиянию на результат.\n\n"
        "**Что должно получиться**\n\n"
        "- [ ] Markdown-файл `PjM21_Project/part-03/task-01/decision_map.md` содержит минимум 3 варианта решений.\n"
        "- [ ] Выбранный вариант обоснован через критерии.\n"
        "- [ ] Файл размещен по указанному пути.\n\n"
        "**Формат сдачи**\n\n"
        "На p2p-ревью покажи артефакт по пути `PjM21_Project/part-03/task-01/decision_map.md`.\n\n"
        "**Переход к следующему заданию**\n\n"
        "В следующем задании используй этот результат как входные данные.\n"
    )

    items = checker.check(ch3, ch2_content="## Глава 2\n### 2.1. Решения\nКритерии выбора.\n")

    assert _get_item(items, "2.5.2").score == 1
    assert _get_item(items, "2.5.3").score == 1
    assert _get_item(items, "2.5.5").score == 1
    assert _get_item(items, "2.5.6").score == 1


def test_similarity_falls_back_when_embeddings_are_incomplete():
    checker = Chapter3Checker(
        llm_client=None,
        embedding_function=lambda _texts: [[1.0]],  # intentionally incomplete
        language="ru",
    )
    avg, scores = checker._compute_pairwise_similarities("теория", ["практика 1", "практика 2"])
    assert isinstance(avg, float)
    assert len(scores) == 2


def test_imperative_goal_and_explicit_p2p_check_pass():
    checker = Chapter3Checker(
        llm_client=None,
        embedding_function=None,
        language="ru",
        regex_patterns={"rx_task": re.compile(r"^###\s+(?:Задание|Задача)\s+(\d+)\.\s*(.+?)\s*$", re.M)},
    )
    ch3 = (
        "### Задание 1. Схема взаимодействия\n\n"
        "**Ситуация:** Команда обсуждает новый пользовательский сценарий, но frontend и backend по-разному понимают, какие данные и когда должны передаваться. Если не собрать схему сейчас, на тестировании появятся лишние баги и спор о границах ответственности.\n\n"
        "**Входные данные:** Описание API и ролей — см. файл `materials/api_context.md`\n\n"
        "**Цель:** Определи ключевые точки взаимодействия frontend и backend и подготовь схему.\n\n"
        "**Подход:**\n"
        "- Выдели HTTP-запросы и ответы.\n"
        "- Сопоставь роли frontend и backend.\n\n"
        "**Ожидаемый результат:** Схема взаимодействия в файле `PjM20_FrontBack/part-03/task-01/interaction_diagram.png`\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] На схеме указаны роли frontend и backend.\n"
        "- [ ] Отмечены минимум 3 точки обмена данными.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )

    items = checker.check(ch3, ch2_content="## Глава 2\n### Часть 1. API\nHTTP-запросы и ответы.\n")
    assert _get_item(items, "2.5.3").score == 1
    assert _get_item(items, "2.5.6").score == 1


def test_structure_check_fails_without_situation_block():
    checker = Chapter3Checker(
        llm_client=None,
        embedding_function=None,
        language="ru",
        regex_patterns={"rx_task": re.compile(r"^###\s+(?:Задание|Задача)\s+(\d+)\.\s*(.+?)\s*$", re.M)},
    )
    ch3 = (
        "### Задание 1. Анализ запроса\n\n"
        "**Входные данные:** Письмо заказчика — см. файл `materials/client_request.md`\n\n"
        "**Цель:** Сформируй список уточняющих вопросов.\n\n"
        "**Подход:**\n"
        "- Выдели неясные требования.\n"
        "- Подготовь вопросы к заказчику.\n\n"
        "**Ожидаемый результат:** Список вопросов в файле `PjM20_FrontBack/part-03/task-01/questions.md`\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] Есть минимум 5 уточняющих вопросов.\n"
        "- [ ] Вопросы связаны с ролями frontend и backend.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )

    items = checker.check(ch3, ch2_content="## Глава 2\n### Часть 1. Требования\n")
    assert _get_item(items, "2.5.2").score == 0


def test_structure_check_accepts_long_situation_without_explicit_risk_token():
    checker = Chapter3Checker(
        llm_client=None,
        embedding_function=None,
        language="ru",
        regex_patterns={"rx_task": re.compile(r"^###\s+(?:Задание|Задача)\s+(\d+)\.\s*(.+?)\s*$", re.M)},
    )
    ch3 = (
        "### Задача 1. Подготовка отчёта\n\n"
        "**Ситуация:** Команда несколько дней обсуждает, как представить результаты аудита для руководителя проекта, "
        "потому что решение должно быть понятным для всей группы и пригодным для последующей сверки на ревью.\n\n"
        "**Входные данные:** Материалы аудита — см. файл `materials/audit.md`\n\n"
        "**Цель:** Подготовь итоговый отчёт для команды.\n\n"
        "**Подход:**\n"
        "- Собери наблюдения по единому шаблону.\n"
        "- Сверь структуру отчёта с ожиданиями команды.\n\n"
        "**Ожидаемый результат:** Итоговый документ в файле `PjM21_Project/part-03/task-01/report.md`\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] В документе перечислены ключевые выводы.\n"
        "- [ ] Указаны подтверждающие материалы.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )

    items = checker.check(ch3, ch2_content="## Глава 2\n### Часть 1. Отчёт\n")
    assert _get_item(items, "2.5.2").score == 1


def test_p2p_check_accepts_observable_phrases_used_by_generator():
    checker = Chapter3Checker(
        llm_client=None,
        embedding_function=None,
        language="ru",
        regex_patterns={"rx_task": re.compile(r"^###\s+(?:Задание|Задача)\s+(\d+)\.\s*(.+?)\s*$", re.M)},
    )
    ch3 = (
        "### Задача 1. Бюджет\n\n"
        "**Ситуация:** Команда готовит смету проекта и должна показать её ревьюеру в проверяемом виде.\n\n"
        "**Входные данные:** Черновая смета — см. файл `materials/budget.xlsx`\n\n"
        "**Цель:** Подготовь итоговую смету расходов.\n\n"
        "**Подход:**\n"
        "- Сверь категории затрат.\n"
        "- Зафиксируй расчёты.\n\n"
        "**Ожидаемый результат:** Таблица в файле `PjM12_Budget/part-03/task-02/budget.xlsx`\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] В таблице перечислены все категории затрат.\n"
        "- [ ] Учтены человеко-часы и платные сервисы.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )

    items = checker.check(ch3, ch2_content="## Глава 2\n### Часть 1. Бюджет\n")
    assert _get_item(items, "2.5.6").score == 1


def test_theory_practice_connection_uses_titles_and_term_overlap_with_low_embeddings():
    def low_similarity_embeddings(texts):
        return [[1.0, 0.0]] + [[0.30, 0.95] for _ in texts[1:]]

    checker = Chapter3Checker(
        llm_client=None,
        embedding_function=low_similarity_embeddings,
        language="ru",
        regex_patterns={"rx_task": re.compile(r"^###\s+(?:Задание|Задача)\s+(\d+)\.\s*(.+?)\s*$", re.M)},
    )
    ch2 = (
        "## Глава 2. Теоретический блок\n\n"
        "### Часть 1. Дорожная карта\n\n"
        "**Дорожная карта** — это план релиза, который связывает задачи, сроки и ожидаемый результат.\n\n"
        "### Часть 2. Зависимости задач\n\n"
        "**Зависимости задач** — это связи, которые показывают, что нельзя делать параллельно.\n"
    )
    ch3 = (
        "### Задача 1. Собрать дорожную карту и зависимости задач\n\n"
        "**Ситуация:** Команда переводит сырой бэклог в план релиза и должна показать связи между задачами.\n\n"
        "**Входные данные:** Сырой бэклог — см. файл `materials/backlog.md`\n\n"
        "**Цель:** Сопоставь задачи, сроки и зависимости задач.\n\n"
        "**Подход:**\n"
        "- Выдели задачи, которые блокируют другие работы.\n"
        "- Собери дорожную карту первого релиза.\n\n"
        "**Ожидаемый результат:** Markdown-файл `PjM11_WorkPlan/part-03/task-01/roadmap.md`\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] Дорожная карта содержит задачи и сроки.\n"
        "- [ ] Зависимости задач перечислены явно.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )

    items = checker.check(ch3, ch2_content=ch2)

    connection_item = _get_item(items, "2.5.7")
    assert connection_item.score == 1
    assert connection_item.details["average_similarity"] < connection_item.details["threshold"]
    assert "Дорожная карта" in connection_item.details["matched_terms"]

