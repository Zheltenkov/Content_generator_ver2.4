"""Агент извлечения образовательных результатов и навыков из учебных проектов."""

import json
import sys

from pydantic import BaseModel, Field

from ..llm.client import LLMClient


class LOAndSkills(BaseModel):
    """Структурированный результат извлечения LO и навыков."""

    learning_outcomes: list[str] = Field(
        default_factory=list,
        description="Список образовательных результатов. Каждый должен начинаться с 'Знает', 'Понимает' или 'Умеет'."
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Список навыков (например, 'Выявление источников информации')."
    )


SYSTEM_PROMPT = """Ты — агент извлечения образовательных результатов (learning outcomes) и навыков (skills) из учебных проектов.

Требования к формату:
- ВСЕГДА возвращай JSON-объект строго по этой схеме.
- НЕ пиши никакого текста до или после JSON.
- Не добавляй комментарии внутри JSON.
- Если какое-то поле пустое — возвращай пустой массив [] (но сам ключ должен быть).

--------------------------------
КАК ИЗВЛЕКАТЬ LEARNING OUTCOMES
--------------------------------

1. Сначала найди все фрагменты, которые описывают, чему этот модуль учит:
   - Явные блоки: "В этом проекте ты научишься", "По итогам ты сможешь", "Образовательные результаты", "Learning outcomes".
   - Явные формулировки: "ты познакомишься", "ты узнаешь", "ты научишься", "ты освоишь", "по итогам ты сможешь".
   - Плюс важные теоретические определения и объяснения (что такое X, какие есть виды Y, какие метрики используются и т.д.).
   - Плюс действия из заданий: если участник должен что-то уметь делать (построить диаграмму, оценить риск, составить план), это тоже кандидат на LO.

2. Для каждого такого фрагмента сформулируй измеримый LO в виде одной строки,
   которая НАЧИНАЕТСЯ со слова:
   - "Знает ..." — если это факт/определение/перечень, который нужно знать.
   - "Понимает ..." — если это про концепцию, связь между понятиями, смысл.
   - "Умеет ..." — если это действие/операция, которую участник должен уметь выполнять.

3. LO должны быть самодостаточными:
   - Не ссылайся на "это", "такое", "то, о чём речь выше".
   - Внутри формулировки повтори ключевые сущности (например, "Знает определение «черного лебедя» и его ключевые признаки...").
   - Избегай слишком общих фраз типа "Понимает важность управления рисками" — уточни, ЧТО именно понимает.

4. Правило маппинга формулировок:
   - "познакомишься", "узнаешь", "будешь знать" → "Знает" или "Понимает"
   - "научишься", "сможешь", "будешь уметь", "освоишь" → "Умеет"

5. Разрешено синтезировать LO на основе теории и заданий, если это напрямую следует из текста.
   НЕЛЬЗЯ добавлять темы и понятия, которых в документе нет.

Примеры допустимых формулировок:
- "Понимает понятие bus factor и его влияние на устойчивость проекта."
- "Знает основные метрики количественной оценки рисков (EF, SLE, AV, ARO, ALE) и их взаимосвязь."
- "Умеет строить диаграмму Фишера (Исикавы) для анализа причин рисков ИТ-продукта."
- "Знает определение «черного лебедя» и три критерия его идентификации по Талебу."

--------------------------------
КАК ИЗВЛЕКАТЬ НАВЫКИ (skills)
--------------------------------

1. Навыки — это короткие формулировки практических умений.
   Источники:
   - Формулировки заданий (составь, построй, оцени, проанализируй, выдели, определи, составь план).
   - Явные перечисления "навыков" в тексте, если они встречаются.
   - Действия, которые участник должен уметь выполнять.

2. Для каждого значимого действия сформулируй навык в виде:
   - существительного + пояснения, например:
     - "Построение диаграммы Фишера (Исикавы) для ИТ-продукта."
     - "Количественная оценка рисков с использованием метрик EF, SLE, AV, ARO, ALE."
     - "Подготовка плана управления рисками с триггерами и стратегиями митигирования."
     - "Выявление источников информации для проекта."
     - "Создание и ведение глоссария проекта."

3. Не дублируй дословно все LO в skills.
   - LO более широкие и описывают "знает/понимает/умеет".
   - skills — более короткие, "названия умений".

4. Если явных действий мало, но по заданиям очевидно, что навык есть (например, "выделить потенциальные черные лебеди"), — сформулируй его аккуратно, строго опираясь на текст документа.

5. Если в документе вообще нет заданий и действий (только общая вода) — skills могут быть [].

ВАЖНО:
- Не придумывай LO и навыки, которых нет в тексте.
- Если в документе нет явных формулировок и заданий — верни пустой массив [].
- Перефразировать можно, но только опираясь на конкретные фразы в документе.
- Каждый LO должен быть измеримым и самодостаточным.
"""

USER_TMPL = """Извлеки образовательные результаты (learning_outcomes) и навыки (skills) из следующего текста учебного проекта.

Требования к формату:
- ВСЕГДА возвращай JSON-объект строго по этой схеме.
- НЕ пиши никакого текста до или после JSON.
- Не добавляй комментарии внутри JSON.
- Если какое-то поле пустое — возвращай пустой массив [] (но сам ключ должен быть).

Текст проекта:
{text}

Твоя задача:
1. Проанализируй весь текст: найди явные формулировки ("ты научишься", "ты узнаешь"), теоретические определения, описания методов и метрик, а также задания.
2. Сформулируй learning_outcomes: каждый должен начинаться с "Знает", "Понимает" или "Умеет" и быть самодостаточным.
3. Сформулируй skills: короткие названия практических умений на основе заданий и действий.

Обязательный формат ответа (строго JSON):
{{
  "learning_outcomes": ["Знает ...", "Понимает ...", "Умеет ..."],
  "skills": ["Навык 1", "Навык 2"]
}}

Если ничего не найдено:
{{
  "learning_outcomes": [],
  "skills": []
}}

Верни ТОЛЬКО JSON, без пояснений и дополнительного текста.
"""


def normalize_text(text: str) -> str:
    """Нормализует текст для обработки."""
    # Приводим переносы строк к единому виду
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Убираем множественные переносы строк
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def extract_lo_and_skills_with_llm(
    md_text: str,
    llm_client: LLMClient,
    language: str = "ru",
    use_preprocessing: bool = True,
) -> LOAndSkills:
    """
    Извлекает образовательные результаты и навыки из текста через LLM с structured output.
    
    Args:
        md_text: Markdown текст учебного проекта
        llm_client: LLM клиент
        language: Язык проекта
        use_preprocessing: Использовать предобработку текста
        
    Returns:
        LOAndSkills с извлеченными данными
    """
    if not llm_client:
        return LOAndSkills()

    # Предобработка текста
    if use_preprocessing:
        text = normalize_text(md_text)
        text = text[:8000] if len(text) > 8000 else text
    else:
        text = md_text[:8000] if len(md_text) > 8000 else md_text

    user_prompt = USER_TMPL.format(text=text)

    try:
        print("  📤 Отправка запроса к LLM...", file=sys.stderr, flush=True)
        response = llm_client.complete(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            response_format="json_object",
            max_completion_tokens=16000,  # Максимальный лимит модели для structured extraction
        )

        print(f"  📥 Получен ответ от LLM, длина: {len(response) if response else 0} символов", file=sys.stderr, flush=True)
        if response and len(response) < 200:
            print(f"  Ответ LLM (первые 200 символов): {response[:200]}", file=sys.stderr, flush=True)

        if not response or not response.strip():
            print("  ⚠️  LLM вернул пустой ответ", file=sys.stderr, flush=True)
            print(f"  Тип response: {type(response)}, значение: {repr(response)}", file=sys.stderr, flush=True)
            return LOAndSkills()

        # Парсим JSON ответ
        response_clean = response.strip()
        json_start = response_clean.find("{")
        json_end = response_clean.rfind("}") + 1

        if json_start == -1 or json_end <= json_start:
            print("  ⚠️  В ответе LLM не найден JSON объект", file=sys.stderr, flush=True)
            return LOAndSkills()

        response_clean = response_clean[json_start:json_end]

        try:
            data = json.loads(response_clean)
        except json.JSONDecodeError as json_err:
            print(f"  ⚠️  Ошибка парсинга JSON: {json_err}", file=sys.stderr, flush=True)
            print(f"  JSON фрагмент (первые 500 символов): {response_clean[:500]}", file=sys.stderr, flush=True)
            # Пробуем восстановить частичный JSON, если ответ был обрезан
            if response_clean.count("{") > response_clean.count("}"):
                # Не хватает закрывающих скобок - пытаемся добавить
                missing_braces = response_clean.count("{") - response_clean.count("}")
                try:
                    # Пытаемся закрыть JSON объект
                    response_clean_fixed = response_clean + "}" * missing_braces
                    # Закрываем массивы, если они открыты
                    if '"learning_outcomes": [' in response_clean and '"learning_outcomes": [' not in response_clean_fixed:
                        response_clean_fixed = response_clean_fixed.rstrip("}") + "]}"
                    if '"skills": [' in response_clean and '"skills": [' not in response_clean_fixed:
                        response_clean_fixed = response_clean_fixed.rstrip("}") + "]}"
                    data = json.loads(response_clean_fixed)
                    print("  ✅ Удалось восстановить частичный JSON", file=sys.stderr, flush=True)
                except:
                    return LOAndSkills()
            else:
                return LOAndSkills()

        # Валидируем через Pydantic
        result = LOAndSkills(**data)

        # Минимальная нормализация: убираем пустые строки и нормализуем пробелы
        normalized_lo = []
        for lo in result.learning_outcomes:
            lo = lo.strip()
            if lo:
                # Убираем множественные пробелы
                lo = " ".join(lo.split())
                normalized_lo.append(lo)

        normalized_skills = []
        for skill in result.skills:
            skill = skill.strip()
            if skill:
                skill = " ".join(skill.split())
                # Убираем точку в конце, если есть
                if skill.endswith("."):
                    skill = skill[:-1]
                normalized_skills.append(skill)

        return LOAndSkills(
            learning_outcomes=normalized_lo,
            skills=normalized_skills,
        )

    except Exception as e:
        print(f"  ⚠️  Ошибка извлечения LO/skills через LLM: {e}", file=sys.stderr, flush=True)
        return LOAndSkills()


def extract_lo_and_skills_fallback(md_text: str) -> LOAndSkills:
    """
    Минимальный fallback метод (возвращает пустой результат).
    Основная работа выполняется через LLM.
    """
    return LOAndSkills()
