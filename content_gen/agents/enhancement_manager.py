"""
content_gen/agents/enhancement_manager.py

Менеджер для координации агентов улучшения контента теории.

Координирует применение улучшений к частям теории:
- CodeExampleAgent: примеры кода
- FormulaTableAgent: формулы, таблицы, Mermaid диаграммы

Принимает решения на основе анализа темы и навыков.
"""

import json

from ..config.thresholds import CODE_EXAMPLE_CONFIG
from ..llm.client import LLMClient
from ..models.enhancement_models import EnhancementDecision, FormulaItem, TableItem, VisualItem
from ..models.enhancement_plan import EnhancementExecutionLog, EnhancementPlan, ImportanceLevel
from ..models.schemas import ProjectSeed, TheoryPart

from ..utils.logging import safe_print
from .code_example import CodeExampleAgent
from .formula_table import FormulaTableAgent

SYSTEM = """Ты — менеджер образовательного контента.
Твоя задача — решить, какие улучшения нужны для части теории:
1. Примеры кода (code_example)
2. Формулы, таблицы и Mermaid-диаграммы (formula_table)

Принимай решения на основе темы, навыков и контекста.

КРИТИЧЕСКИ ВАЖНО:
- ОБЯЗАТЕЛЬНО используй елочки « » для кавычек вместо прямых кавычек " "

Язык: {language}.
"""

DECISION_TMPL = """Проанализируй часть теории и реши, какие улучшения применить.

Тема: {topic}
Навыки: {skills}
Текст части (первые 500 символов): {theory_preview}
Контекст проекта: {project_description}

{existing_enhancements_context}

Доступные улучшения:
1. **use_code_examples** - генерация примеров кода и заданий на программирование
2. **use_formulas_tables** - генерация формул, таблиц и Mermaid диаграмм

Ограничения методолога:
- include_formulas: {include_formulas}
- include_tables: {include_tables}
- include_diagrams: {include_diagrams}

Верни строго JSON объект:
{{
  "use_code_examples": true/false,
  "use_formulas_tables": true/false,
  "reasoning": "Обоснование решения (2-3 предложения)"
}}

Критерии:
- **use_code_examples**: true ТОЛЬКО если навыки ЯВНО включают программирование (Python, JavaScript, Java, C++, код, программирование, разработка, алгоритмы программирования) И тема связана с написанием кода, программированием, разработкой ПО. НЕ используй для простых концепций, которые можно объяснить без кода.
- **use_formulas_tables**: true только если методолог разрешил хотя бы один тип (include_* = true) И тема явно выигрывает от визуальных элементов.
  * Формулы: только если есть метрики, расчеты, параметры или явные количественные связи
  * Таблицы: только для сравнения или классификации сложных концепций (не списки)
  * Диаграммы: только для сложных процессов/взаимодействий (не линейные списки)

ВАЖНО: если include_formulas/include_tables/include_diagrams = false, не включай соответствующие элементы.

Будь разумным: не включай улучшения, если они не дают понятной пользы.
"""


class TheoryEnhancementManager:
    """Менеджер для координации агентов улучшения контента теории."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.code_agent = CodeExampleAgent(llm)
        self.formula_agent = FormulaTableAgent(llm)

    def decide_enhancements(
        self,
        part: TheoryPart,
        seed: ProjectSeed,
        existing_enhancements: dict = None
    ) -> EnhancementDecision:
        """
        Принимает решение о том, какие улучшения применять к части теории.
        
        Args:
            part: Часть теории
            seed: Входные данные проекта
            existing_enhancements: Словарь с информацией о том, что уже использовано в предыдущих частях
                Формат: {"tables": 2, "diagrams": 1, "formulas": 0, "code_examples": 1}
        
        Returns:
            EnhancementDecision с решением
        """
        # Уважение настроек методолога: если все визуальные элементы запрещены — сразу выключаем
        if not (seed.include_formulas or seed.include_tables or seed.include_diagrams):
            return EnhancementDecision(
                use_code_examples=False,
                use_formulas_tables=False,
                reasoning="Методолог отключил формулы/таблицы/диаграммы"
            )

        # Формируем контекст о существующих улучшениях
        existing_context = ""
        if existing_enhancements:
            used_types = []
            if existing_enhancements.get("tables", 0) > 0:
                used_types.append(f"таблицы ({existing_enhancements['tables']} раз)")
            if existing_enhancements.get("diagrams", 0) > 0:
                used_types.append(f"диаграммы ({existing_enhancements['diagrams']} раз)")
            if existing_enhancements.get("formulas", 0) > 0:
                used_types.append(f"формулы ({existing_enhancements['formulas']} раз)")
            if existing_enhancements.get("code_examples", 0) > 0:
                used_types.append(f"примеры кода ({existing_enhancements['code_examples']} раз)")

            if used_types:
                existing_context = f"""
**Контекст варьирования:**
В предыдущих частях теории уже использовались: {', '.join(used_types)}.

ВАЖНО: варьирование применимо только к таблицам и диаграммам.
Если уже были таблицы, можно предпочесть диаграммы (и наоборот), если это уместно.
"""
            else:
                existing_context = "\n**Контекст варьирования:** Это первая часть теории. Можно использовать подходящий тип визуализации, если он явно полезен.\n"
        else:
            existing_context = "\n**Контекст варьирования:** Это первая часть теории. Можно использовать подходящий тип визуализации, если он явно полезен.\n"

        system_prompt = SYSTEM.format(language=seed.language)
        user_prompt = DECISION_TMPL.format(
            topic=part.title,
            skills=", ".join(seed.skills) if seed.skills else "общие навыки",
            theory_preview=part.body[:500],
            project_description=seed.project_description[:300],
            existing_enhancements_context=existing_context,
            include_formulas=seed.include_formulas,
            include_tables=seed.include_tables,
            include_diagrams=seed.include_diagrams,
        )

        try:
            safe_print(f"  🤔 Анализ необходимости улучшений для части: {part.title[:50]}...", flush=True)

            response = self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                response_format="json_object",
                temperature=0.1
            )

            if not response or not response.strip():
                safe_print("  ⚠️ LLM вернул пустой ответ, используем значения по умолчанию", flush=True)
                return EnhancementDecision(
                    use_code_examples=False,
                    use_formulas_tables=False,
                    reasoning="Не удалось проанализировать, используем значения по умолчанию"
                )

            # Парсим JSON
            response_clean = response.strip()
            json_start = response_clean.find("{")
            json_end = response_clean.rfind("}") + 1

            if json_start == -1 or json_end <= json_start:
                safe_print("  ⚠️ В ответе LLM не найден JSON объект", flush=True)
                return EnhancementDecision(
                    use_code_examples=False,
                    use_formulas_tables=False,
                    reasoning="Ошибка парсинга"
                )

            json_str = response_clean[json_start:json_end]
            data = json.loads(json_str)

            decision = EnhancementDecision(
                use_code_examples=data.get("use_code_examples", False),
                use_formulas_tables=data.get("use_formulas_tables", False),
                reasoning=data.get("reasoning", "")
            )

            safe_print(f"  ✅ Решение для '{part.title[:50]}...':", flush=True)
            safe_print(f"     - Примеры кода: {'✅ ДА' if decision.use_code_examples else '❌ НЕТ'}", flush=True)
            safe_print(f"     - Формулы/таблицы/диаграммы: {'✅ ДА' if decision.use_formulas_tables else '❌ НЕТ'}", flush=True)
            if decision.reasoning:
                safe_print(f"     - Обоснование: {decision.reasoning[:200]}...", flush=True)

            return decision

        except json.JSONDecodeError as e:
            safe_print(f"  ⚠️ Ошибка парсинга JSON: {str(e)}", flush=True)
            return EnhancementDecision(
                use_code_examples=False,
                use_formulas_tables=False,
                reasoning="Ошибка парсинга JSON"
            )
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            safe_print(f"  ⚠️ Ошибка принятия решения: {str(e)}", flush=True)
            safe_print(f"     Детали: {error_details[:500]}", flush=True)
            return EnhancementDecision(
                use_code_examples=False,
                use_formulas_tables=False,
                reasoning=f"Ошибка: {str(e)}"
            )

    def enhance_part(
        self,
        part: TheoryPart,
        seed: ProjectSeed,
        existing_formulas: list[FormulaItem] = None,
        existing_tables: list[TableItem] = None,
        decision: EnhancementDecision = None,
        existing_enhancements: dict = None
    ) -> tuple[TheoryPart, list[FormulaItem], list[TableItem]]:
        """
        Применяет улучшения к части теории на основе решения менеджера.
        
        Args:
            part: Часть теории
            seed: Входные данные проекта
            existing_formulas: Уже сгенерированные формулы из других частей (для дедупликации)
            existing_tables: Уже сгенерированные таблицы из других частей (для дедупликации)
            decision: Решение о том, какие улучшения применять (если None, принимается автоматически)
            existing_enhancements: Словарь с информацией о том, что уже использовано (для варьирования)
        
        Returns:
            Кортеж: (улучшенная часть теории, новые формулы, новые таблицы)
        """
        # Принимаем решение, если оно не передано
        if decision is None:
            decision = self.decide_enhancements(part, seed, existing_enhancements=None)

        enhanced_body = part.body
        enhanced_part = TheoryPart(
            title=part.title,
            body=enhanced_body,
            example=part.example,
            bridge_questions=part.bridge_questions,
            covers_outcomes=part.covers_outcomes,
            references=part.references.copy() if part.references else []
        )

        new_formulas = []
        new_tables = []

        # Применяем улучшения в порядке приоритета

        try:
            # 1. Формулы и таблицы (встраиваются в текст)
            if decision.use_formulas_tables:
                safe_print("  📊 Генерация формул/таблиц...", flush=True)
                try:
                    # Передаем статистику использованных типов для варьирования
                    # Но нужно получить enhancement_stats из enhance_parts, поэтому передаем None
                    # (варьирование происходит на уровне decide_enhancements)
                    formula_result = self.formula_agent.analyze(
                        topic=part.title,
                        theory_text=part.body,
                        seed=seed,
                        existing_formulas=existing_formulas or [],
                        existing_tables=existing_tables or [],
                        existing_enhancements=existing_enhancements  # Передаем для варьирования
                    )

                    if formula_result.needs_formulas or formula_result.needs_tables or formula_result.needs_visuals:
                        new_formulas = formula_result.formulas or []
                        new_tables = formula_result.tables or []
                        new_visuals = formula_result.visuals or []

                        enhanced_body = self.formula_agent.embed_in_text(
                            enhanced_body,
                            new_formulas,
                            new_tables,
                            new_visuals
                        )
                        enhanced_part.body = enhanced_body

                        # Сохраняем visuals для правильного подсчета диаграмм
                        if new_visuals:
                            enhanced_part._has_visuals = True
                except Exception as e:
                    import traceback
                    safe_print(f"  ⚠️ Ошибка при генерации формул/таблиц: {str(e)}", flush=True)
                    safe_print(f"     Детали: {traceback.format_exc()[:500]}", flush=True)

            # 2. Примеры кода (встраиваются в текст)
            if decision.use_code_examples:
                safe_print("  💻 Генерация примеров кода...", flush=True)
                try:
                    code_result = self.code_agent.generate(
                        topic=part.title,
                        skills=seed.skills or [],
                        seed=seed,
                        context=part.body
                    )

                    # Встраиваем примеры в текст
                    if code_result and code_result.examples:
                        for example in code_result.examples[:2]:  # Максимум 2 примера
                            enhanced_body = self.code_agent.embed_example_in_text(enhanced_body, example)

                        enhanced_part.body = enhanced_body
                except Exception as e:
                    import traceback
                    safe_print(f"  ⚠️ Ошибка при генерации примеров кода: {str(e)}", flush=True)
                    safe_print(f"     Детали: {traceback.format_exc()[:500]}", flush=True)
        except Exception as e:
            import traceback
            safe_print(f"  ⚠️ Критическая ошибка при применении улучшений: {str(e)}", flush=True)
            safe_print(f"     Детали: {traceback.format_exc()[:500]}", flush=True)

        return enhanced_part, new_formulas, new_tables

    def enhance_parts_with_plan(
        self,
        parts: list[TheoryPart],
        seed: ProjectSeed,
        plan: EnhancementPlan
    ) -> tuple[list[TheoryPart], list[EnhancementExecutionLog]]:
        """
        Применяет улучшения к частям теории на основе глобального плана.
        
        Args:
            parts: Список частей теории
            seed: Входные данные проекта
            plan: Глобальный план улучшений
        
        Returns:
            Кортеж: (улучшенные части, логи выполнения)
        """
        safe_print(f"[ENHANCEMENT] Применение плана к {len(parts)} частям", flush=True)

        enhanced_parts = []
        execution_logs = []
        all_formulas = []
        all_tables = []
        all_visuals = []
        all_code_examples = []

        for i, part in enumerate(parts, 1):
            part_plan = plan.per_part.get(i)
            if not part_plan:
                safe_print(f"  ⚠️ Нет плана для части {i}, пропускаем", flush=True)
                enhanced_parts.append(part)
                continue

            safe_print(f"  🔧 Улучшение части {i}/{len(parts)}: {part.title[:50]}...", flush=True)
            safe_print(f"     План: formulas={part_plan.formulas.value}, tables={part_plan.tables.value}, diagrams={part_plan.diagrams.value}, code={part_plan.code_examples.value}", flush=True)

            log = EnhancementExecutionLog(
                part_index=i,
                topic=part.title,
                plan=part_plan,
                generated={},
                embedded_positions={},
                errors=[]
            )

            enhanced_body = part.body
            new_formulas = []
            new_tables = []
            new_visuals = []
            new_code_examples = []

            try:
                # 1. Формулы (если must или nice_to_have)
                if seed.include_formulas and part_plan.formulas in [ImportanceLevel.MUST, ImportanceLevel.NICE_TO_HAVE]:
                    try:
                        formula_result = self.formula_agent.analyze(
                            topic=part.title,
                            theory_text=part.body,
                            seed=seed,
                            existing_formulas=all_formulas,
                            existing_tables=all_tables,
                            existing_enhancements={}
                        )

                        if formula_result.needs_formulas:
                            generation_result = self.formula_agent._generate(
                                topic=part.title,
                                theory_text=part.body,
                                skills=seed.skills or [],
                                seed=seed,
                                needs_formulas=True,
                                needs_tables=False,
                                needs_visuals=False,
                                existing_formulas=all_formulas,
                                existing_tables=all_tables
                            )

                            if generation_result.get("formulas"):
                                new_formulas = [FormulaItem(**f) for f in generation_result.get("formulas", [])]
                                # Встраивание по якорям или общим правилам
                                enhanced_body = self._embed_formulas(enhanced_body, new_formulas, part_plan.anchor_hints)
                                log.embedded_positions["formulas"] = [f"встроено {len(new_formulas)} формул"]
                    except Exception as e:
                        error_msg = f"Ошибка генерации формул: {str(e)}"
                        log.errors.append(error_msg)
                        safe_print(f"     ⚠️ {error_msg}", flush=True)

                # 2. Таблицы (если must или nice_to_have; для MUST генерируем даже при seed.include_tables=False — план приоритетнее)
                if (seed.include_tables or part_plan.tables == ImportanceLevel.MUST) and part_plan.tables in [ImportanceLevel.MUST, ImportanceLevel.NICE_TO_HAVE]:
                    try:
                        # Для MUST таблицы генерируем принудительно, для NICE_TO_HAVE проверяем через analyze
                        is_must = part_plan.tables == ImportanceLevel.MUST

                        if is_must:
                            # Для MUST генерируем принудительно
                            needs_tables = True
                        else:
                            # Для NICE_TO_HAVE проверяем через analyze
                            formula_result = self.formula_agent.analyze(
                                topic=part.title,
                                theory_text=enhanced_body,
                                seed=seed,
                                existing_formulas=all_formulas + new_formulas,
                                existing_tables=all_tables,
                                existing_enhancements={}
                            )
                            needs_tables = formula_result.needs_tables

                        if needs_tables:
                            generation_result = self.formula_agent._generate(
                                topic=part.title,
                                theory_text=enhanced_body,
                                skills=seed.skills or [],
                                seed=seed,
                                needs_formulas=False,
                                needs_tables=True,
                                needs_visuals=False,
                                existing_formulas=all_formulas + new_formulas,
                                existing_tables=all_tables
                            )

                            if generation_result.get("tables"):
                                new_tables = [TableItem(**t) for t in generation_result.get("tables", [])]
                                enhanced_body = self._embed_tables(enhanced_body, new_tables, part_plan.anchor_hints)
                                log.embedded_positions["tables"] = [f"встроено {len(new_tables)} таблиц"]
                            elif is_must:
                                # Если таблицы MUST, но не сгенерированы - это ошибка
                                error_msg = f"Таблицы обязательны (MUST) для части '{part.title}', но не удалось сгенерировать"
                                log.errors.append(error_msg)
                                safe_print(f"     ⚠️ {error_msg}", flush=True)
                    except Exception as e:
                        error_msg = f"Ошибка генерации таблиц: {str(e)}"
                        log.errors.append(error_msg)
                        safe_print(f"     ⚠️ {error_msg}", flush=True)

                # 3. Диаграммы (план приоритетнее seed: при MUST или NICE_TO_HAVE пробуем генерировать даже если seed.include_diagrams=False)
                if (seed.include_diagrams or part_plan.diagrams in [ImportanceLevel.MUST, ImportanceLevel.NICE_TO_HAVE]) and part_plan.diagrams in [ImportanceLevel.MUST, ImportanceLevel.NICE_TO_HAVE]:
                    try:
                        is_must_diagrams = part_plan.diagrams == ImportanceLevel.MUST
                        # Раз план сказал MUST или NICE_TO_HAVE — пробуем сгенерировать (не зависим от analyze/seed)
                        needs_visuals = True
                        if needs_visuals:
                            generation_result = self.formula_agent._generate(
                                topic=part.title,
                                theory_text=enhanced_body,
                                skills=seed.skills or [],
                                seed=seed,
                                needs_formulas=False,
                                needs_tables=False,
                                needs_visuals=True,
                                existing_formulas=all_formulas + new_formulas,
                                existing_tables=all_tables + new_tables
                            )

                            if generation_result.get("visuals"):
                                new_visuals = [VisualItem(**v) for v in generation_result.get("visuals", [])]
                                enhanced_body = self.formula_agent.embed_in_text(
                                    enhanced_body,
                                    [],
                                    [],
                                    new_visuals[:1]  # Максимум 1 диаграмма на часть
                                )
                                log.embedded_positions["diagrams"] = [f"встроена {len(new_visuals)} диаграмма"]
                            elif is_must_diagrams:
                                error_msg = f"Диаграммы обязательны (MUST) для части '{part.title}', но не удалось сгенерировать"
                                log.errors.append(error_msg)
                                safe_print(f"     ⚠️ {error_msg}", flush=True)
                    except Exception as e:
                        error_msg = f"Ошибка генерации диаграмм: {str(e)}"
                        log.errors.append(error_msg)
                        safe_print(f"     ⚠️ {error_msg}", flush=True)

                # 4. Примеры кода (если must или nice_to_have и проект программистский)
                if plan.is_programming_project and part_plan.code_examples in [ImportanceLevel.MUST, ImportanceLevel.NICE_TO_HAVE]:
                    try:
                        code_result = self.code_agent.generate(
                            topic=part.title,
                            skills=seed.skills or [],
                            seed=seed,
                            context=enhanced_body[:500]  # Используем context вместо context_preview
                        )

                        if code_result.examples:
                            new_code_examples = code_result.examples
                            enhanced_body = self.code_agent.embed_example_in_text(
                                enhanced_body,
                                new_code_examples[0]  # Первый пример
                            )
                            log.embedded_positions["code_examples"] = [f"встроено {len(new_code_examples)} примеров"]
                    except Exception as e:
                        error_msg = f"Ошибка генерации примеров кода: {str(e)}"
                        log.errors.append(error_msg)
                        safe_print(f"     ⚠️ {error_msg}", flush=True)

            except Exception as e:
                error_msg = f"Критическая ошибка при улучшении части: {str(e)}"
                log.errors.append(error_msg)
                safe_print(f"     ❌ {error_msg}", flush=True)

            # Обновляем лог
            log.generated = {
                "formulas": len(new_formulas),
                "tables": len(new_tables),
                "diagrams": len(new_visuals),
                "code_examples": len(new_code_examples)
            }

            # Создаем улучшенную часть
            enhanced_part = TheoryPart(
                title=part.title,
                body=enhanced_body,
                example=part.example,
                bridge_questions=part.bridge_questions,
                covers_outcomes=part.covers_outcomes,
                references=part.references.copy() if part.references else [],
                text_markdown=part.body  # Сохраняем исходный текст
            )

            enhanced_parts.append(enhanced_part)
            execution_logs.append(log)

            # Обновляем общие списки
            all_formulas.extend(new_formulas)
            all_tables.extend(new_tables)
            all_visuals.extend(new_visuals)
            all_code_examples.extend(new_code_examples)

            safe_print(f"     ✅ Сгенерировано: {len(new_formulas)} формул, {len(new_tables)} таблиц, {len(new_visuals)} диаграмм, {len(new_code_examples)} примеров кода", flush=True)

        safe_print(f"  ✅ Всего сгенерировано: {len(all_formulas)} формул, {len(all_tables)} таблиц, {len(all_visuals)} диаграмм, {len(all_code_examples)} примеров кода", flush=True)

        return enhanced_parts, execution_logs

    def _embed_formulas(self, text: str, formulas: list[FormulaItem], anchor_hints: dict[str, str] | None = None) -> str:
        """Встраивает формулы в текст по якорям или общим правилам."""
        if not formulas:
            return text

        import re

        from ..utils.markdown_renderer import render_formula

        # Ищем якоря в тексте ({{INSERT_FORMULA:...}})
        anchor_pattern = r'\{\{INSERT_FORMULA:([^}]+)\}\}'

        for formula in formulas:
            formula_md = render_formula(formula.label, formula.latex, formula.parameters)

            # Пытаемся найти якорь для этой формулы
            matches = list(re.finditer(anchor_pattern, text))
            if matches:
                # Используем первый найденный якорь
                match = matches[0]
                anchor_name = match.group(1)
                # Заменяем якорь на формулу
                text = text[:match.start()] + formula_md + text[match.end():]
                safe_print(f"     ✅ Формула встроена по якорю: {anchor_name}", flush=True)
            else:
                # Если есть подсказка, пытаемся найти место по ключевым словам
                if anchor_hints and "formula" in anchor_hints:
                    hint = anchor_hints["formula"].lower()
                    # Ищем ключевые слова из подсказки в тексте
                    hint_words = hint.split()
                    # Ищем предложения, содержащие ключевые слова
                    sentences = re.split(r'([.!?]\s+)', text)
                    insert_pos = None
                    for i, sentence in enumerate(sentences):
                        if any(word in sentence.lower() for word in hint_words if len(word) > 3):
                            # Вставляем после этого предложения
                            insert_pos = sum(len(s) for s in sentences[:i+1])
                            break

                    if insert_pos is not None:
                        text = text[:insert_pos] + f"\n\n{formula_md}\n\n" + text[insert_pos:]
                        safe_print(f"     ✅ Формула встроена по подсказке: {hint[:50]}...", flush=True)
                        continue

                # Общие правила: вставляем перед **Пример:** или в конец
                if "**Пример:**" in text:
                    text = text.replace("**Пример:**", f"{formula_md}\n\n**Пример:**", 1)
                    safe_print("     ✅ Формула встроена перед **Пример:**", flush=True)
                else:
                    # Вставляем в конец перед **Вопросы к практике:**
                    if "**Вопросы к практике:**" in text:
                        text = text.replace("**Вопросы к практике:**", f"{formula_md}\n\n**Вопросы к практике:**", 1)
                        safe_print("     ✅ Формула встроена перед **Вопросы к практике:**", flush=True)
                    else:
                        # Вставляем в самый конец
                        text = f"{text}\n\n{formula_md}"
                        safe_print("     ✅ Формула встроена в конец текста", flush=True)

        return text

    def _embed_tables(self, text: str, tables: list[TableItem], anchor_hints: dict[str, str] | None = None) -> str:
        """Встраивает таблицы в текст по якорям или общим правилам."""
        if not tables:
            return text

        import re

        from ..utils.markdown_renderer import render_table

        # Ищем якоря в тексте ({{INSERT_TABLE:...}})
        anchor_pattern = r'\{\{INSERT_TABLE:([^}]+)\}\}'

        for table in tables:
            table_md = render_table(table.label, table.md_table, table.description)

            # Пытаемся найти якорь для этой таблицы
            matches = list(re.finditer(anchor_pattern, text))
            if matches:
                # Используем первый найденный якорь
                match = matches[0]
                anchor_name = match.group(1)
                # Заменяем якорь на таблицу
                text = text[:match.start()] + table_md + text[match.end():]
                safe_print(f"     ✅ Таблица встроена по якорю: {anchor_name}", flush=True)
            else:
                # Если есть подсказка, пытаемся найти место по ключевым словам
                if anchor_hints and "table" in anchor_hints:
                    hint = anchor_hints["table"].lower()
                    hint_words = hint.split()
                    sentences = re.split(r'([.!?]\s+)', text)
                    insert_pos = None
                    for i, sentence in enumerate(sentences):
                        if any(word in sentence.lower() for word in hint_words if len(word) > 3):
                            insert_pos = sum(len(s) for s in sentences[:i+1])
                            break

                    if insert_pos is not None:
                        text = text[:insert_pos] + f"\n\n{table_md}\n\n" + text[insert_pos:]
                        safe_print(f"     ✅ Таблица встроена по подсказке: {hint[:50]}...", flush=True)
                        continue

                # Общие правила: вставляем перед **Пример:**
                if "**Пример:**" in text:
                    text = text.replace("**Пример:**", f"{table_md}\n\n**Пример:**", 1)
                    safe_print("     ✅ Таблица встроена перед **Пример:**", flush=True)
                else:
                    if "**Вопросы к практике:**" in text:
                        text = text.replace("**Вопросы к практике:**", f"{table_md}\n\n**Вопросы к практике:**", 1)
                        safe_print("     ✅ Таблица встроена перед **Вопросы к практике:**", flush=True)
                    else:
                        text = f"{text}\n\n{table_md}"
                        safe_print("     ✅ Таблица встроена в конец текста", flush=True)

        return text

    def _embed_diagrams(self, text: str, diagrams: list[VisualItem], anchor_hints: dict[str, str] | None = None) -> str:
        """Встраивает диаграммы в текст по якорям или общим правилам."""
        if not diagrams:
            return text

        import re

        # Ищем якоря в тексте ({{INSERT_DIAGRAM:...}})
        anchor_pattern = r'\{\{INSERT_DIAGRAM:([^}]+)\}\}'

        for diagram in diagrams:
            # Используем embed_in_text из formula_agent для правильного форматирования
            # Но сначала проверяем якоря
            matches = list(re.finditer(anchor_pattern, text))
            if matches:
                # Используем первый найденный якорь
                match = matches[0]
                anchor_name = match.group(1)
                # Генерируем Markdown для диаграммы
                from ..utils.markdown_renderer import render_mermaid
                diagram_md = render_mermaid(diagram.label, diagram.mermaid, diagram.description)
                # Заменяем якорь на диаграмму
                text = text[:match.start()] + diagram_md + text[match.end():]
                safe_print(f"     ✅ Диаграмма встроена по якорю: {anchor_name}", flush=True)
            else:
                # Если есть подсказка, пытаемся найти место по ключевым словам
                if anchor_hints and "diagram" in anchor_hints:
                    hint = anchor_hints["diagram"].lower()
                    hint_words = hint.split()
                    sentences = re.split(r'([.!?]\s+)', text)
                    insert_pos = None
                    for i, sentence in enumerate(sentences):
                        if any(word in sentence.lower() for word in hint_words if len(word) > 3):
                            insert_pos = sum(len(s) for s in sentences[:i+1])
                            break

                    if insert_pos is not None:
                        from ..utils.markdown_renderer import render_mermaid
                        diagram_md = render_mermaid(diagram.label, diagram.mermaid, diagram.description)
                        text = text[:insert_pos] + f"\n\n{diagram_md}\n\n" + text[insert_pos:]
                        safe_print(f"     ✅ Диаграмма встроена по подсказке: {hint[:50]}...", flush=True)
                        continue

                # Используем стандартный метод встраивания
                enhanced_body = self.formula_agent.embed_in_text(
                    text,
                    [],
                    [],
                    [diagram]
                )
                text = enhanced_body
                safe_print("     ✅ Диаграмма встроена по общим правилам", flush=True)

        return text

    def enhance_parts(
        self,
        parts: list[TheoryPart],
        seed: ProjectSeed,
        parallel: bool = True
    ) -> list[TheoryPart]:
        """
        Применяет улучшения ко всем частям теории.
        
        Args:
            parts: Список частей теории
            seed: Входные данные проекта
            parallel: Использовать параллельную обработку (по умолчанию True)
        
        Returns:
            Список улучшенных частей теории
        """
        if not parts:
            return []

        # Собираем уже сгенерированные формулы и таблицы для дедупликации
        all_formulas: list[FormulaItem] = []
        all_tables: list[TableItem] = []

        # Отслеживаем, какие типы визуализаций уже использованы (для варьирования)
        enhancement_stats = {
            "tables": 0,
            "diagrams": 0,
            "formulas": 0,
            "code_examples": 0
        }

        safe_print(f"  🔧 Анализ и улучшение {len(parts)} частей теории...", flush=True)
        safe_print("     Менеджер будет принимать решения для каждой части:", flush=True)
        safe_print("     - Нужны ли примеры кода?", flush=True)
        safe_print("     - Нужны ли формулы, таблицы или диаграммы?", flush=True)
        safe_print("     - ВАРЬИРОВАНИЕ: разные типы визуализаций в разных частях для разнообразия", flush=True)

        if parallel and len(parts) > 1:
            # В параллельном режиме дедупликация сложнее, поэтому обрабатываем последовательно
            # но можем оптимизировать, обрабатывая части батчами
            enhanced_parts = []
            for i, part in enumerate(parts, 1):
                safe_print(f"  🔧 Улучшение части {i}/{len(parts)}: {part.title[:50]}...", flush=True)

                # Принимаем решение с учетом уже использованных типов
                decision = self.decide_enhancements(part, seed, existing_enhancements=enhancement_stats)

                # Применяем улучшения с уже принятым решением и статистикой
                enhanced_part, new_formulas, new_tables = self.enhance_part(
                    part, seed,
                    existing_formulas=all_formulas,
                    existing_tables=all_tables,
                    decision=decision,
                    existing_enhancements=enhancement_stats
                )

                # Обновляем статистику использованных типов
                if decision.use_code_examples:
                    enhancement_stats["code_examples"] += 1
                if decision.use_formulas_tables:
                    # Подсчитываем, что именно было сгенерировано
                    if new_formulas:
                        enhancement_stats["formulas"] += len(new_formulas)
                    if new_tables:
                        enhancement_stats["tables"] += len(new_tables)
                    # Проверяем, есть ли диаграммы - сначала проверяем сохраненный флаг, потом regex
                    import re
                    if hasattr(enhanced_part, '_has_visuals') and enhanced_part._has_visuals:
                        enhancement_stats["diagrams"] += 1
                    elif re.search(r'```mermaid', enhanced_part.body):
                        enhancement_stats["diagrams"] += 1

                    safe_print(f"     📊 Статистика после части {i}: таблицы={enhancement_stats['tables']}, диаграммы={enhancement_stats['diagrams']}, формулы={enhancement_stats['formulas']}, код={enhancement_stats['code_examples']}", flush=True)

                enhanced_parts.append(enhanced_part)
                # Добавляем новые элементы в общий список
                all_formulas.extend(new_formulas)
                all_tables.extend(new_tables)
        else:
            enhanced_parts = []
            for i, part in enumerate(parts, 1):
                safe_print(f"  🔧 Улучшение части {i}/{len(parts)}: {part.title[:50]}...", flush=True)

                # Принимаем решение с учетом уже использованных типов
                decision = self.decide_enhancements(part, seed, existing_enhancements=enhancement_stats)

                # Применяем улучшения с уже принятым решением и статистикой
                enhanced_part, new_formulas, new_tables = self.enhance_part(
                    part, seed,
                    existing_formulas=all_formulas,
                    existing_tables=all_tables,
                    decision=decision,
                    existing_enhancements=enhancement_stats
                )

                # Обновляем статистику использованных типов
                if decision.use_code_examples:
                    enhancement_stats["code_examples"] += 1
                if decision.use_formulas_tables:
                    # Подсчитываем, что именно было сгенерировано
                    if new_formulas:
                        enhancement_stats["formulas"] += len(new_formulas)
                    if new_tables:
                        enhancement_stats["tables"] += len(new_tables)
                    # Проверяем, есть ли диаграммы - сначала проверяем сохраненный флаг, потом regex
                    import re
                    if hasattr(enhanced_part, '_has_visuals') and enhanced_part._has_visuals:
                        enhancement_stats["diagrams"] += 1
                    elif re.search(r'```mermaid', enhanced_part.body):
                        enhancement_stats["diagrams"] += 1

                    safe_print(f"     📊 Статистика после части {i}: таблицы={enhancement_stats['tables']}, диаграммы={enhancement_stats['diagrams']}, формулы={enhancement_stats['formulas']}, код={enhancement_stats['code_examples']}", flush=True)

                enhanced_parts.append(enhanced_part)
                # Добавляем новые элементы в общий список
                all_formulas.extend(new_formulas)
                all_tables.extend(new_tables)

        safe_print(f"  ✅ Всего сгенерировано: {len(all_formulas)} формул, {len(all_tables)} таблиц", flush=True)

        safe_print(
            "  🔍 Проверка элементов улучшения: принудительное добавление диаграмм/формул отключено; "
            "используется только EnhancementPlan и content_type policy.",
            flush=True,
        )

        # Проверка обязательных элементов для программирования: хотя бы одно демонстрация кода
        total_code_examples = enhancement_stats["code_examples"]
        is_programming = self._is_programming_topic(seed)

        safe_print("  🔍 Проверка обязательных элементов для программирования:", flush=True)
        safe_print(f"     - Тема касается разработки/программирования: {'✅ ДА' if is_programming else '❌ НЕТ'}", flush=True)
        if is_programming:
            safe_print(f"     - Навыки: {', '.join(seed.skills or [])[:200]}", flush=True)
            safe_print(f"     - Описание: {seed.project_description[:200]}", flush=True)
        safe_print(f"     - Демонстрации кода: {total_code_examples} (требуется для программирования: минимум 1)", flush=True)

        # Если тема касается разработки/программирования, но нет демонстраций кода - добавляем
        if is_programming and total_code_examples == 0:
            safe_print("  ⚠️ Демонстрация кода отсутствует для темы программирования. Добавляем демонстрацию кода для наиболее сложной тематики...", flush=True)
            # Находим часть с наиболее сложными концепциями (обычно это средние или последние части)
            target_part_idx = min(len(enhanced_parts) - 1, max(0, len(enhanced_parts) // 2))
            target_part = enhanced_parts[target_part_idx]

            try:
                # Генерируем пример кода для сложной тематики
                safe_print(f"     🔧 Генерируем пример кода для части '{target_part.title[:50]}...'", flush=True)
                code_result = self.code_agent.generate(
                    topic=target_part.title,
                    skills=seed.skills or [],
                    seed=seed,
                    context=target_part.body
                )

                if code_result and code_result.examples:
                    safe_print(f"     ✅ Сгенерировано {len(code_result.examples)} примеров кода", flush=True)
                    # Встраиваем пример кода в текст
                    for example in code_result.examples[:1]:  # Только первый пример
                        enhanced_body = self.code_agent.embed_example_in_text(target_part.body, example)
                        enhanced_parts[target_part_idx].body = enhanced_body
                        enhancement_stats["code_examples"] += 1
                        safe_print(f"     ✅ Демонстрация кода добавлена в часть '{target_part.title[:50]}...'", flush=True)
                        # Проверяем, что код действительно встроен
                        if "```" in enhanced_body and example.language in enhanced_body:
                            safe_print("     ✅ Код подтвержден в тексте (найден блок кода)", flush=True)
                        else:
                            safe_print("     ⚠️ ВНИМАНИЕ: Код не найден в тексте после встраивания!", flush=True)
                        break
                else:
                    safe_print("     ⚠️ Не удалось сгенерировать примеры кода", flush=True)
            except Exception as e:
                import traceback
                safe_print(f"     ⚠️ Ошибка при добавлении демонстрации кода: {str(e)}", flush=True)
                safe_print(f"     Детали: {traceback.format_exc()[:500]}", flush=True)

        safe_print(f"  ✅ Финальная статистика: {enhancement_stats['formulas']} формул, {enhancement_stats['diagrams']} диаграмм, {enhancement_stats['tables']} таблиц, {enhancement_stats['code_examples']} демонстраций кода", flush=True)

        return enhanced_parts

    def _is_programming_topic(self, seed: ProjectSeed) -> bool:
        """
        Проверяет, касается ли тема проекта программирования или разработки.
        Используется для определения необходимости демонстрации кода.
        
        Args:
            seed: Входные данные проекта
        
        Returns:
            True, если тема касается программирования
        """
        if not CODE_EXAMPLE_CONFIG.get("enable_code_tasks_in_practice", False):
            return False

        # Ключевые слова, указывающие на программирование
        programming_keywords = [
            "программирование", "разработка программного обеспечения", "разработка по", "разработка приложений",
            "изучение языка программирования", "изучение python", "изучение javascript", "изучение java",
            "написание кода", "написание программы", "создание программы", "разработка программы",
            "python", "javascript", "java", "c++", "cpp", "go", "rust", "sql", "bash",
            "алгоритм программирования", "функция программирования", "класс программирования",
            "объектно-ориентированное программирование", "функциональное программирование",
            "разработка приложения", "разработка скрипта", "разработка модуля", "разработка библиотеки",
            "api разработка", "backend разработка", "frontend разработка"
        ]

        # Исключаем общие термины
        excluded_keywords = [
            "разработка проекта", "разработка решения", "разработка подхода",
            "алгоритм работы", "алгоритм процесса",
            "функция системы", "функция процесса",
        ]

        all_text = " ".join([
            " ".join(seed.skills or []),
            seed.project_description or "",
            " ".join(seed.learning_outcomes or [])
        ]).lower()

        # Если есть исключающие ключевые слова, код не нужен
        if any(excluded in all_text for excluded in excluded_keywords):
            return False

        # Проверяем наличие ключевых слов программирования
        return any(keyword in all_text for keyword in programming_keywords)
