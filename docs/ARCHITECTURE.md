# Архитектура Content Generator

## Обзор

Content Generator построен на модульной архитектуре с четким разделением ответственности между компонентами.

## Связанная документация

- [AGENTS.md](AGENTS.md) — подробное описание агентной системы и AgentFlow
- [CRITERIA.md](CRITERIA.md) — система валидации и критериев качества
- [REVERSE_EXTRACTION.md](REVERSE_EXTRACTION.md) — система обратного извлечения данных из README
- [API.md](API.md) — REST API документация
- [DEPLOYMENT.md](DEPLOYMENT.md) — инструкции по развертыванию
- [TESTING.md](TESTING.md) — система тестирования

## Основные компоненты

### 1. Orchestrator (Оркестратор)

**Файл:** `content_gen/orchestrator.py`

Оркестратор управляет полным пайплайном генерации контента через явный AgentFlow:

- Flow описывается в `content_gen/config/flow.yaml` (`context → … → finalize`)
- `AgentFlowRunner` выполняет узлы по графу, логирует `flow_trace` (step_index, node, status, duration)
- `GenerationFlowHandlers` владеет registry и реализацией concrete node handlers (`context`, `theory`, `practice`, `finalize` и т.д.)
- `run_v2()` запускает Flow, а `FlowResultFinalizer` проверяет наличие результата, собирает `flow_trace` и передает его в `MethodologyTraceRecorder`
- После ключевых узлов запускается `MethodologyGate`: deterministic stage review с `StageReviewResult`, который сохраняется в `report_json.methodology_reviews` и `methodology_summary`
- Для ограниченного набора замечаний запускается `MethodologyRepairController`: deterministic one-pass repair без LLM, с `StageRepairResult`, повторным post-review и записью в `report_json.methodology_repairs`
- `MethodologyTraceRecorder` синхронизирует review/repair объекты с `ProjectFlowState`, сериализует их и добавляет summaries в `report_json`
- `TaskPlanner` (через агент-конфиг) автоматически определяет количество практических задач (2–8) и сложность на основе уровня аудитории и контекста, пришедшего из учебного плана
- Финальная сборка вынесена в `ResultAssembler`: он собирает `ProjectSpec`, `report_json`, assets, translated assets и fallback-структуры из flow context
- При финальной сборке вызывается `mermaid_export` для конвертации всех ```mermaid``` блоков в изображения и прикладывает их к архиву выдачи

### ResultAssembler

**Файл:** `content_gen/result_assembly.py`

Отвечает только за сборку финального результата из уже подготовленных артефактов:

- нормализует markdown и translated markdown;
- конвертирует Mermaid-блоки в assets;
- добавляет файлы практических артефактов и dataset files;
- восстанавливает `TheoryPart` и `PracticeTask`, если structured outputs отсутствуют;
- собирает `ProjectSpec`, `OrchestratorResult` и `report_json`.

`Orchestrator` не формирует отчет напрямую: узел `finalize` вызывает `ResultAssembler` и возвращает typed updates в `AgentFlowRunner`.

### GenerationFlowHandlers

**Файл:** `content_gen/flow_handlers.py`

Содержит конкретные реализации AgentFlow-нод и registry для `AgentFlowRunner`:

- вызывает concrete node services/executors для фаз `context`, `skeleton`, `theory`, `practice`, `quality`, `evaluation`, `translate`;
- обновляет mutable flow context результатами стадий;
- делегирует финальную сборку в `ResultAssembler`;
- инкапсулирует технические helpers для issue serialization и hard-failure detection.

`Orchestrator` не держит phase wrappers: основная логика нод находится в `GenerationFlowHandlers`.

### FlowResultFinalizer

**Файл:** `content_gen/flow_result.py`

Отвечает за пост-обработку завершенного AgentFlow:

- проверяет, что flow создал `OrchestratorResult`;
- формирует сериализованный `flow_trace`;
- добавляет `flow_trace` и methodology summaries в результат через `MethodologyTraceRecorder`;
- поднимает `ContentGenerationError`, если flow остановился без результата.

### 2. Agents (Агенты)

**Директория:** `content_gen/agents/`

**Подробнее:** См. [AGENTS.md](AGENTS.md) для полного описания агентной системы, AgentFlow и всех типов агентов.

Специализированные агенты для генерации разных частей контента:

#### Основные агенты:

- **`TitleAnnotationAgent`** — генерация аннотации проекта
- **`SkeletonAgent`** — создание каркаса (структуры) проекта
- **`IntroRulesAgent`** — генерация введения и инструкции (Глава 1)
- **`TheoryAgent`** — генерация теоретической части (Глава 2)
- **`PracticeAgent`** — генерация практических заданий (Глава 3)
- **`TOCAgent`** — генерация оглавления
- **`RegenerationAgent`** — перегенерация частей контента

#### Агенты улучшения:

- **`CodeExampleAgent`** — добавление примеров кода
- **`FormulaTableAgent`** — добавление формул, таблиц, диаграмм
- **`DefinitionsAgent`** — генерация определений терминов
- **`LengthAgent`** — контроль длины контента
- **`ReadabilityAgent`** — улучшение читаемости

#### Агенты валидации и качества:

- **`StyleGuardAgent`** — проверка стиля и тона
- **`AntiPlagiarismAgent`** — проверка на плагиат
- **`TranslatorAgent`** — перевод на целевой язык

### 3. Validators (Валидаторы)

**Директория:** `content_gen/validators/`

**Подробнее:** См. [CRITERIA.md](CRITERIA.md) для полного описания системы критериев, методов проверки и структуры валидации.

#### Rubric Validators

**Директория:** `content_gen/validators/rubric/`

Модульная система проверки по критериям качества:

- **`scorer.py`** — основной класс `RubricScorer`
- **`annotation_checker.py`** — проверка аннотации (2.1.1-2.1.3)
- **`toc_checker.py`** — проверка оглавления (2.2.1-2.2.2)
- **`chapter1_checker.py`** — проверка Главы 1 (2.3.1-2.3.7)
- **`chapter2_checker.py`** — проверка Главы 2 (2.4.1-2.4.5)
- **`chapter3_checker.py`** — проверка Главы 3 (2.5.1-2.5.4)
- **`section1_checker.py`** — проверка Раздела 1 (2.1)
- **`section2_checker.py`** — проверка Раздела 2 (2.2-2.5)
- **`section3_checker.py`** — проверка Раздела 3 (2.6)
- **`section4_checker.py`** — проверка Раздела 4 (2.7)
- **`similarity.py`** — расчет семантической схожести (SBERT)
- **`utils.py`** — утилиты для checker'ов

#### Другие валидаторы:

- **`structural_preflight.py`** — предварительная проверка структуры
- **`theory_checks.py`** — проверки теории
- **`practice_checks.py`** — проверки практики
- **`structure.py`** — проверка структуры документа

### 5. Generation Context

**Основной источник контекста:** `curriculum_context` во входном `ProjectSeed`.

В текущем production-контуре генерация не требует локального `data/` каталога и предварительно построенного retrieval-индекса.

Используемые компоненты:

- `ContextPhaseExecutor` — собирает контекст проекта из учебного плана
- `ProjectContextMeta` — метаданные позиции проекта в учебном плане
- `ContextAnalysisResult` — типизированный контейнер для итогового контекста фазы 0
- `content_gen/curriculum/graph.py` — deterministic-анализ соседних проектов и прогресса

### 6. Models (Модели данных)

**Директория:** `content_gen/models/`

- **`schemas.py`** — Pydantic схемы для валидации данных
  - `ProjectSeed` — входные данные проекта
  - `ProjectSpec` — спецификация проекта
  - `ProjectContextMeta` — метаданные контекста учебного плана
- **`criteria_models.py`** — модели для критериев проверки
- **`enhancement_models.py`** — модели для улучшений контента
- **`enums.py`** — перечисления

### 7. API Layer

**Директория:** `api/`

FastAPI приложение с REST API:

- **`main.py`** — главное приложение
- **`routers/`** — API endpoints:
  - `generation.py` — генерация контента
  - `regeneration.py` — перегенерация
  - `download.py` — скачивание результатов
  - `health.py` — health check
  - `metrics.py` — метрики
  - `auth.py` — аутентификация
  - `admin.py` — административные функции
- **`db/`** — модели БД и сессии
- **`middleware/`** — middleware (логирование, rate limiting, activity tracking)

## Поток данных

### Генерация контента

1. **Входные данные** → `ProjectSeed` (Pydantic схема)
2. **Phase 0**: Intent & Curriculum Context
   - Анализ входных данных
   - Сбор контекста из учебного плана
   - Создание `ProjectContextMeta`
3. **Phase 1**: Skeleton
   - Генерация каркаса через `SkeletonAgent`
   - Проверка структуры через `StructuralPreflight`
4. **Phase 2**: Theory
   - Генерация теории через `TheoryAgent`
   - Улучшения через `EnhancementManager`
   - Проверки через `TheoryChecks`
5. **Phase 3**: Practice
   - Генерация практики через `PracticeAgent`
   - Проверки через `PracticeChecks`
6. **Phase 4**: Quality
   - Глобальные проверки качества
   - Улучшение читаемости, стиля
7. **Phase 5**: Anti-plagiarism & Translation
   - Проверка на плагиат
   - Перевод на целевой язык
8. **Phase 6**: Final Scoring
   - Оценка по всем критериям через `RubricScorer`
   - Формирование отчета
9. **Результат** → Markdown + JSON отчет

## Валидация

### Структура валидации

1. **Предварительная проверка** (`StructuralPreflight`)
   - Проверка структуры документа
   - Проверка наличия обязательных разделов

2. **Проверки во время генерации**
   - `TheoryChecks` — проверки теории
   - `PracticeChecks` — проверки практики
   - `MethodologyGate` — review стадий AgentFlow по typed-контрактам
   - `MethodologyRepairController` — безопасное восстановление структурных артефактов (`TaskPlan`, `ProjectBlueprint`, `TheoryPart`, `PracticeTask`) без повторной генерации
   - `MethodologyTraceRecorder` — единая запись review/repair trace в state и report

3. **Итоговая проверка** (`RubricScorer`)
   - Проверка по всем критериям (50+)
   - Формирование детального отчета

### Методы проверки

- **SCRIPT** — программная проверка (regex, парсинг)
- **AI** — проверка через LLM
- **SEMANTIC** — семантическая схожесть (SBERT)

## Конфигурация

**Директория:** `content_gen/config/`

- **`thresholds.py`** — пороги и лимиты для валидации
- **`banned_phrases.py`** — запрещенные фразы
- **`loader.py`** — центральный загрузчик YAML-конфигов (лениво читает, кеширует и выдаёт версии)
- **`agents/*.yaml`** — параметры агентов (LLM-настройки, промпты, флаги поведения). Промпты вынесены в `content_gen/prompts/...`
- **`flow.yaml`** — декларативное описание AgentFlow (узлы, ребра, условия, входы/выходы), которое подхватывает `AgentFlowRunner`

Каждый агент загружает свой конфиг через `get_agent_config`, что позволяет:
- централизованно менять промпты и параметры без правок кода;
- логировать версии конфигов для трассировки (сохраняются в `generation_results.agent_config_versions` и в `logs.meta_data`);
- повторно использовать одни и те же промпты (TitleAnnotation, IntroRules, Theory, Practice, ContentEditor, StyleGuard и др.).

Дополнительно в Phase 3 подключён `PracticeCriticAgent`, который анализирует главу 3 совместно с суммаризованной теорией и логирует найденные проблемы (`practice_critic_issues` в отчёте и БД).

## Утилиты

**Директория:** `content_gen/utils/`

- **`text_analysis.py`** — анализ текста (подсчет слов, проверка стиля)
- **`markdown_helpers.py`** — работа с Markdown
- **`logging.py`** — логирование
- **`metrics.py`** — метрики

## База данных

Используется SQLAlchemy с PostgreSQL.

**Модели:**
- `LogEntry` — логи операций
- `RequestLog` — логи запросов
- `UserSession` — сессии пользователей
- `GenerationResult` — итоговые Markdown/метаданные генерации (seed, задачи, статусы, перегенерации, `flow_trace`)
- `RubricResult` — полные `rubric.json`, привязанные внешним ключом к `GenerationResult`
- `ReportResult` — сокращённые `report.json` без диаграмм и бинарных assets (также связаны с `GenerationResult`)

Хранение готового контента в трёх таблицах позволяет:
- восстановить README даже после очистки кэша;
- хранить полные rubric отчёты для аналитики и аудита;
- сокращать отчёты в БД (без бинарных assets), но оставлять все данные для zip-выгрузки;
- трассировать выполнение AgentFlow (поле `flow_trace`).

**Миграции:** Alembic в `migrations/`

## Безопасность

- JWT аутентификация
- Rate limiting (slowapi)
- Логирование всех операций
- Маскирование чувствительных данных

## Reverse Extraction System

**Директория:** `content_gen/reverse_extraction/`

Система обратного извлечения выполняет обратную задачу к генератору: извлекает структурированные данные из готового README.md и заполняет Excel-шаблон спецификации проекта.

**Подробнее:** См. [REVERSE_EXTRACTION.md](REVERSE_EXTRACTION.md) для полного описания системы.

**Основные компоненты:**
- `InputAgent` — нормализация README
- `StructureExtractor` — извлечение семантики через StructuredLLMClient
- `ClassifierAgent` — определение метаданных (с проверкой существующих thematic_blocks)
- `MapperAgent` — преобразование в формат Excel
- `ValidatorAgent` — валидация с автоматическими правками
- `ExcelWriterTool` — заполнение Excel-шаблона
- `ReverseExtractionOrchestrator` — координация всех агентов

**API Endpoints:**
- `POST /api/v1/reverse-extract/extract` — извлечение данных из README
- `GET /api/v1/reverse-extract/download/{file_id}` — скачивание Excel

**Особенности:**
- Использует `StructuredLLMClient` для гарантированного парсинга
- Проверяет существующие thematic_blocks перед использованием LLM
- Автоматическая валидация и правка данных
- Интеграция с UI в отдельной секции

## Structured Outputs

**Директория:** `content_gen/llm/structured_output.py`

Система использует OpenAI Structured Outputs как транспортный слой между LLM и Pydantic моделями:

- **Pydantic = доменная модель**: Все модели данных остаются в Pydantic (TaskPlan, ContextAnalysisResult, PracticeIssue и т.д.)
- **Structured Outputs = транспорт**: Используются только для структурированных выходов (списки, планы, результаты анализа)
- **Plain text для длинных текстов**: Markdown (главы, теория, практика) остаются в text режиме
- **Fallback на JSON mode**: Если модель не поддерживает structured outputs, используется обычный JSON mode

**Использование:**

```python
from content_gen.llm.structured_output import StructuredLLMClient

structured_client = StructuredLLMClient(llm_client)
result = structured_client.complete_structured(
    output_model=TaskPlan,
    system="...",
    user="..."
)
# result - уже валидированный объект TaskPlan!
```

**Где используется:**
- `TaskPlanner` → `TaskPlan`
- `PracticeCriticAgent` → `List[PracticeIssue]`
- `EnhancementPlanner` → `EnhancementPlan`
- `StructureExtractor` (reverse extraction) → `PartialProjectSeed`
- `ClassifierAgent` (reverse extraction) → `ClassificationResult`

**Где НЕ используется:**
- `TheoryAgent`, `PracticeAgent`, `IntroRulesAgent` → длинные markdown тексты (plain text)

## Масштабируемость

- Асинхронная обработка (FastAPI)
- Кэширование LLM запросов (`CachedLLMClient`)
- Batch processing для эмбеддингов
- Structured outputs для гарантированного соответствия схеме

## Тестирование

**Подробнее:** См. [TESTING.md](TESTING.md) для полного описания системы тестирования.

Система тестирования построена на pytest и включает:

- **Unit-тесты** — тестирование отдельных компонентов (агенты, валидаторы, утилиты)
- **Интеграционные тесты** — тестирование полного flow генерации
- **Моки и фикстуры** — изоляция тестов от внешних зависимостей (LLM, БД)
- **Покрытие кода** — мониторинг покрытия критичных компонентов

**Структура тестов:**
- `tests/agents/` — тесты агентов
- `tests/validators/` — тесты валидаторов
- `tests/integration/` — интеграционные тесты
- `tests/curriculum/` — тесты контекста учебного плана
- `tests/utils/` — тесты утилит

## Расширяемость

Архитектура позволяет легко:

- Добавлять новые агенты (наследование от базового класса) — см. [AGENTS.md](AGENTS.md)
- Добавлять новые checker'ы (модульная структура) — см. [CRITERIA.md](CRITERIA.md)
- Добавлять новые flow-ноды через `flow.yaml`, `GenerationFlowHandlers` и concrete node service
- Интегрировать новые LLM провайдеры (через `LLMClient`)
- Расширять контекстный слой через `content_gen/curriculum/` и typed-контракты фазы 0
