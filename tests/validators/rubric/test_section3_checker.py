import json

from content_gen.validators.rubric.section3_checker import Section3Checker
from content_gen.validators.rubric.similarity import SimilarityCalculator


class NarrativeLLM:
    def complete(self, **kwargs):
        user = kwargs["user"]
        has_drift = "DevOps" in user and "Types and data structures" in user
        return json.dumps({
            "has_unified_focus": not has_drift,
            "anchors": ["бэклог", "дорожная карта", "диаграмма Ганта"],
            "drift": ["DevOps", "Types and data structures"] if has_drift else [],
            "reason": "Найден чужой учебный контекст" if has_drift else "Фокус сохранен",
        })


def test_narrative_focus_reports_curriculum_drift() -> None:
    md = """
# План работ

## Глава 1. Введение и инструкция

### Введение
Проект про бэклог, дорожную карту и диаграмму Ганта. Теперь акцент смещается на DevOps, Types and data structures.

### Инструкция
Следуй общим правилам платформы.

## Глава 2. Теоретический блок

### Часть 1. Бэклог
Бэклог помогает команде связать задачи, зависимости и дорожную карту.

## Глава 3. Практический блок

### Задача 1. Собери план
**Цель:** Сформировать дорожную карту на основе бэклога.
**Ожидаемый результат:** Markdown-файл с планом работ.
"""

    checker = Section3Checker(SimilarityCalculator(), llm_client=NarrativeLLM())
    item = next(item for item in checker.check(md) if item.id == "3.2")

    assert item.score == 0
    assert item.details["drift"] == ["DevOps", "Types and data structures"]
    assert "чужой учебный контекст" in item.comments[0].lower()
