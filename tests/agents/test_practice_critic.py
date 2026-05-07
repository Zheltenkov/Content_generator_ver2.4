from types import SimpleNamespace

from content_gen.agents.practice_critic import PracticeCriticAgent, PracticeIssue


def test_practice_critic_filters_false_positive_story_and_p2p_issues():
    practice_md = (
        "### Задача 1. Выбор СУБД\n\n"
        "**Ситуация:** Команда запускает новый сервис и спорит, какая СУБД выдержит нагрузку и не создаст лишних рисков по безопасности. Если не принять решение сейчас, архитектура уйдёт в работу с неверными допущениями.\n\n"
        "**Входные данные:** Техническое задание — см. файл `materials/requirements.md`\n\n"
        "**Цель:** Проанализируй требования и обоснуй выбор СУБД.\n\n"
        "**Подход:**\n"
        "- Выдели требования к данным и нагрузке.\n"
        "- Сопоставь их с возможностями вариантов СУБД.\n\n"
        "**Ожидаемый результат:** Документ с анализом и выбором СУБД — `PjM21_ITInfStruct/part-03/task-01/README.md`.\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] Указаны требования к данным и нагрузке.\n"
        "- [ ] Выбор СУБД обоснован через минимум 3 аргумента.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )
    issues = [
        PracticeIssue(task_index=0, kind="story_alignment", severity="warning", message="story", suggestion="fix"),
        PracticeIssue(task_index=1, kind="p2p_check", severity="critical", message="p2p", suggestion="fix"),
    ]

    filtered = PracticeCriticAgent._suppress_false_positives(
        seed=SimpleNamespace(sjm=""),
        practice_markdown=practice_md,
        theory_summary="1. Типы хостинга\n2. Безопасность данных\n3. СУБД",
        issues=issues,
    )

    assert filtered == []


def test_practice_critic_drops_sjm_issue_when_sjm_absent():
    issues = [
        PracticeIssue(task_index=1, kind="sjm_alignment", severity="warning", message="sjm", suggestion="fix"),
    ]

    filtered = PracticeCriticAgent._suppress_false_positives(
        seed=SimpleNamespace(sjm=""),
        practice_markdown="### Задача 1. Пример\n\n**Ситуация:** Есть задача и дедлайн.\n",
        theory_summary="1. СУБД",
        issues=issues,
    )

    assert filtered == []


def test_practice_critic_filters_theory_alignment_by_token_overlap():
    practice_md = (
        "### Задача 2. Анализ пути пользователя\n\n"
        "**Ситуация:** Команда обсуждает, где пользователь теряет интерес, и хочет зафиксировать это в артефакте для ревью.\n\n"
        "**Входные данные:** Черновой сценарий — см. файл `materials/cjm_notes.md`\n\n"
        "**Цель:** Проанализируй путь пользователя и выдели болевые точки.\n\n"
        "**Подход:**\n"
        "- Опиши ключевые шаги пути пользователя.\n"
        "- Зафиксируй болевые точки и моменты потери интереса.\n\n"
        "**Ожидаемый результат:** Документ в файле `PjM22_Product/part-03/task-02/cjm_analysis.md`.\n\n"
        "**Критерии проверки (P2P):**\n"
        "- [ ] В документе перечислены шаги пути пользователя.\n"
        "- [ ] Указаны минимум 3 болевые точки.\n"
        "- [ ] Файл размещён по указанному пути.\n"
    )
    issues = [
        PracticeIssue(task_index=2, kind="theory_alignment", severity="warning", message="theory", suggestion="fix"),
    ]

    filtered = PracticeCriticAgent._suppress_false_positives(
        seed=SimpleNamespace(sjm=""),
        practice_markdown=practice_md,
        theory_summary="1. Customer Journey Map: путь пользователя\n2. Болевые точки и ожидания пользователя",
        issues=issues,
    )

    assert filtered == []
