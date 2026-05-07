# Карта процессов генерации контента (AgentFlow)

Граф выполнения пайплайна генерации описан в конфиге и выполняется рантаймом `AgentFlowRunner` (`content_gen/agents/flow.py`). Конкретные handlers нод находятся в `GenerationFlowHandlers` (`content_gen/flow_handlers.py`). Исполняемый конфиг: `content_gen/config/flow.yaml`. Документированная версия с комментариями по нодам: [content_gen/config/flow_documented.yaml](../content_gen/config/flow_documented.yaml).

## Схема переходов

Линейная цепочка (все переходы безусловные):

```
context → task_planning → skeleton → theory → practice → global_quality → antiplag → evaluation → translate → finalize
```

## Таблица нод: входы, выходы, переходы

| # | Node ID | Назначение | Входы (из контекста) | Выходы в контекст | Переход |
|---|---------|------------|----------------------|-------------------|--------|
| 0 | context | Seed + контекст учебного плана | — | seed, context_meta, context_analysis, similar_projects, context_bundle, warnings | → task_planning |
| 1 | task_planning | План практических задач | seed, context_meta, context_analysis | seed, task_plan, warnings | → skeleton |
| 2 | skeleton | Каркас README (структура глав) | seed, context_meta | markdown, title, annotation, intro_section, blueprint, warnings, issues | → theory |
| 3 | theory | Глава 2 (теория) | seed, context_meta, markdown | markdown, theory_parts, warnings, issues | → practice |
| 4 | practice | Глава 3 + critic | seed, markdown | markdown, practice_tasks, practice_critic_issues, blueprint, warnings, issues | → global_quality |
| 5 | global_quality | Глобальное качество текста | seed, markdown | markdown | → antiplag |
| 6 | antiplag | Антиплагиат | seed, markdown | markdown | → evaluation |
| 7 | evaluation | Оценка по рубрике | seed, markdown | rubric_json, issues | → translate |
| 8 | translate | Перевод (или пропуск, если язык совпадает) | seed, markdown | markdown, translated_markdown | → finalize |
| 9 | finalize | Сборка результата через ResultAssembler | seed, markdown, context_meta, context_analysis, context_bundle, rubric_json, task_plan, translated_markdown | result, project_spec, markdown, translated_markdown, assets_binary | — |

После завершения графа `FlowResultFinalizer` проверяет, что `finalize` создал `OrchestratorResult`, сериализует `flow_trace` и передает результат в `MethodologyTraceRecorder` для записи review/repair summaries.

## Условия переходов

- В YAML все рёбра заданы без поля `condition`: после каждой ноды выполняется ровно одна следующая по графу.
- Единственная логическая ветка реализована **внутри хендлера** `translate`: если язык контента уже совпадает с `target_language`, перевод не выполняется; переход в `finalize` выполняется в любом случае.

## Методологический gate

После ключевых нод `context`, `task_planning`, `skeleton`, `theory`, `practice`, `evaluation`, `finalize` запускается `MethodologyGate`.

Gate не генерирует контент и не является свободным агентом. Это deterministic evaluation layer с typed-контрактом `StageReviewResult`:

- `status`: `passed`, `warning`, `failed`, `skipped`
- `issues`: список методологических замечаний с severity и code
- `repair_instructions`: инструкции для repair-pass или human review
- `human_review_required`: флаг ручной проверки
- `metrics` и `evidence`: проверяемые признаки стадии

Результаты gate попадают в `report_json.methodology_reviews`, `report_json.methodology_summary` и issues соответствующего шага в `flow_trace`.

После gate может запускаться `MethodologyRepairController`: deterministic repair-pass с typed-контрактом `StageRepairResult`. Он не вызывает LLM и не переписывает контент свободно. Текущая политика:

- максимум одна попытка repair на стадию;
- только allowlist issue-кодов (`task_planning`, `skeleton.blueprint_missing`, `theory.parts_missing`, `practice.tasks_missing`);
- repair делает только безопасные структурные правки: синхронизация `TaskPlan`/`ProjectSeed`, восстановление `ProjectBlueprint`, парсинг `TheoryPart` и `PracticeTask` из уже сгенерированного markdown;
- после успешной правки gate запускается повторно один раз, чтобы trace видел состояние после repair.

Результаты repair попадают в `report_json.methodology_repairs`, `report_json.methodology_repair_summary` и issues соответствующего шага в `flow_trace`.

Запись этих артефактов выполняет `MethodologyTraceRecorder`: он синхронизирует `ProjectFlowState`, сериализует `StageReviewResult`/`StageRepairResult` и добавляет summaries в финальный `report_json`.

## Связанные файлы

- Конфиг (исполняемый): `content_gen/config/flow.yaml`
- Конфиг с комментариями: `content_gen/config/flow_documented.yaml`
- Рантайм графа: `content_gen/agents/flow.py`
- Реализации нод: `content_gen/flow_handlers.py`
- Методологический gate: `content_gen/methodology/gate.py`
- Ограниченный repair-pass: `content_gen/methodology/repair.py`
- Trace/report recorder методологии: `content_gen/methodology/trace.py`
- Финальная сборка результата: `content_gen/result_assembly.py`
- Пост-обработка завершенного Flow: `content_gen/flow_result.py`
- Компоновка зависимостей и запуск: `content_gen/orchestrator.py`
