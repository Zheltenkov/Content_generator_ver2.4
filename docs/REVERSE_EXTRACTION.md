# Система Обратного Извлечения (Reverse Extraction)

## Обзор

Система обратного извлечения выполняет обратную задачу к генератору контента: извлекает структурированные данные из готового README.md и передает их напрямую в пайплайн генерации для создания улучшенного README.

Система использует агентную архитектуру с LLM для семантического анализа и извлечения данных.

## Архитектура системы

### Общая схема

```
┌─────────────────────────────────────────────────────────────────┐
│          REVERSE EXTRACTION → README IMPROVEMENT FLOW            │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐
│  README.md   │
│  (исходный)  │
└──────┬───────┘
       │
       ▼
┌─────────────────┐
│  InputAgent     │  ← Нормализация README
│  - normalize()  │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ StructureExtractor│  ← Извлечение семантики
│  - extract()    │     - Title, description
│  (StructuredLLM)│     - Learning outcomes
└──────┬──────────┘     - Skills, tools
       │                - Tasks count
       ▼
┌─────────────────┐
│ ClassifierAgent │  ← Определение метаданных
│  - classify()    │     - Language, thematic_block
└──────┬──────────┘     - Audience level, project_type
       │
       ▼
┌─────────────────┐
│ extract_data_only│  ← Возврат данных
│  (orchestrator) │     - PartialProjectSeed
└──────┬──────────┘     - ClassificationResult
       │                - NormalizedReadme
       │
       ▼
┌─────────────────┐
│  Кэш данных     │  ← Сохранение для редактирования
│  (improvement_  │
│   cache)        │
└──────┬──────────┘
       │
       │ [Пользователь редактирует данные]
       │
       ▼
┌─────────────────┐
│ POST /readme/   │  ← Генерация улучшенного README
│ improve/generate│     - Конвертация в ProjectSeed
└──────┬──────────┘     - Запуск пайплайна генерации
       │
       ▼
┌─────────────────┐
│  Orchestrator   │  ← Полный пайплайн генерации
│  (генератор)    │     - Phase 0-6
└──────┬──────────┘
       │
       ▼
┌──────────────┐
│ Улучшенный   │
│ README.md    │
└──────────────┘
```

## Компоненты системы

### 1. InputAgent

**Файл:** `content_gen/reverse_extraction/agents/input_agent.py`

**Назначение:** Нормализация README.md и извлечение структуры документа.

**Методы:**
- `normalize(readme_text: str) -> NormalizedReadme`
  - Удаление HTML тегов
  - Нормализация markdown разметки
  - Извлечение структуры (заголовки, списки, секции)
  - Извлечение глав по номерам

**Модель:**
```python
class NormalizedReadme(BaseModel):
    raw_text: str                    # Очищенный текст
    structure: Dict[str, Any]        # Структура (заголовки, секции)
    chapters: Dict[int, str]         # Содержимое глав (1, 2, 3...)
```

**Пример использования:**
```python
agent = InputAgent()
normalized = agent.normalize(readme_text)
# normalized.chapters[1] - Глава 1
# normalized.chapters[2] - Глава 2 (теория)
# normalized.chapters[3] - Глава 3 (практика)
```

### 2. StructureExtractor

**Файл:** `content_gen/reverse_extraction/agents/structure_extractor.py`

**Назначение:** Извлечение семантики из README в частично заполненный `ProjectSeed`.

**Использует:** `StructuredLLMClient` с Pydantic моделью для гарантированного парсинга.

**Методы:**
- `extract(normalized_readme: NormalizedReadme) -> PartialProjectSeed`
  - Извлечение `title_seed` из первого h1/h2
  - Извлечение `project_description` из введения (1-3 предложения)
  - Извлечение `learning_outcomes` (переформулировка если неявно)
  - Извлечение `required_tools` (инструменты и технологии)
  - Извлечение `skills` из задач и теории
  - Подсчет `tasks_count` (количество практических задач)

**Промежуточная модель:**
```python
class PartialProjectSeed(BaseModel):
    title_seed: Optional[str]
    project_description: Optional[str]
    learning_outcomes: List[str]
    required_tools: List[str]
    skills: List[str]
    tasks_count: Optional[int]
    theory_parts: List[str]  # для контекста
```

**Промпты:**
- `content_gen/prompts/reverse_extraction/structure_extractor/system.md`
- `content_gen/prompts/reverse_extraction/structure_extractor/user_template.md`

**Конфиг:** `content_gen/config/agents/structure_extractor.yaml`

**Fallback:** При ошибке LLM используется базовое извлечение (title из заголовка, подсчет задач по паттерну).

### 3. ClassifierAgent

**Файл:** `content_gen/reverse_extraction/agents/classifier_agent.py`

**Назначение:** Определение метаданных проекта с проверкой существующих тематических блоков.

**Особенность:** Сначала проверяет существующие блоки из `thematic_blocks.json`, затем использует LLM если не найдено.

**Методы:**
- `classify(partial_seed: PartialProjectSeed, normalized_readme: NormalizedReadme) -> ClassificationResult`

**Логика определения thematic_block:**

```
1. Загрузка thematic_blocks.json
   └─── { "Кибербезопасность": "Cb", "Проектный менеджмент": "PjM", ... }

2. Поиск по ключевым словам в README
   ├─── "кибербезопасность", "security", "пароль" → "Cb"
   ├─── "проектный менеджмент", "scrum", "agile" → "PjM"
   ├─── "тестирование", "testing", "qa" → "QA"
   └─── и т.д.

3. Если не найдено → LLM классификация
   ├─── Агент получает список существующих блоков
   ├─── Анализирует содержание README
   └─── Может предложить новый блок (thematic_block_suggested)
```

**Модель:**
```python
class ClassificationResult(BaseModel):
    language: str                    # ru, en, kg, uz
    thematic_block: Optional[str]    # Cb, PjM, QA, BSA, DO (существующий)
    thematic_block_suggested: Optional[str]  # Новый код (если не найден)
    thematic_block_name: Optional[str]        # Название нового блока
    audience_level: Optional[str]    # Начальный, Продвинутый, base, advanced
    project_type: Optional[str]      # individual, group
```

**Промпты:**
- `content_gen/prompts/reverse_extraction/classifier/system.md`
- `content_gen/prompts/reverse_extraction/classifier/user_template.md`

**Конфиг:** `content_gen/config/agents/classifier.yaml`

**Ключевые слова для блоков:**
- **BSA**: "бизнес аналитика", "requirements", "use case", "user story"
- **Cb**: "кибербезопасность", "security", "пароль", "шифрование", "сеть"
- **DO**: "devops", "ci/cd", "docker", "kubernetes", "развертывание"
- **PjM**: "проектный менеджмент", "scrum", "agile", "backlog", "sprint"
- **QA**: "тестирование", "testing", "qa", "test case", "баг"
- **DS**: "машинное обучение", "machine learning", "ml", "data science"

### 4. Orchestrator

**Файл:** `content_gen/reverse_extraction/orchestrator.py`

**Назначение:** Координация всех агентов в единый пайплайн.

**Методы:**

**`extract_data_only(readme_text: str)`**:
- Извлекает данные из README
- Возвращает: `Tuple[PartialProjectSeed, ClassificationResult, NormalizedReadme, Dict[str, Any]]`
- Используется в `/readme/improve/extract`

**Пайплайн выполнения:**

```
README text
    │
    ▼
InputAgent.normalize()
    │
    ▼
StructureExtractor.extract()  [StructuredLLMClient]
    │
    ▼
TasksExtractor.extract_tasks() [Уточнение количества задач]
    │
    ▼
ClassifierAgent.classify()    [StructuredLLMClient + проверка блоков]
    │
    ▼
PartialProjectSeed + ClassificationResult + NormalizedReadme + metadata
```

**Обработка ошибок:**
- На каждом этапе логируются ошибки
- Fallback на базовые методы при ошибках LLM
- Возврат метаданных с предупреждениями и ошибками

**Метаданные:**
```python
{
    "status": "completed" | "error",
    "warnings": List[str],
    "errors": List[str],
    "extracted_fields": {
        "partial_seed": {...},
        "classification": {...}
    }
}
```

## Модели данных

### NormalizedReadme

```python
class NormalizedReadme(BaseModel):
    raw_text: str                    # Очищенный текст README
    structure: Dict[str, Any]        # Структура документа
    chapters: Dict[int, str]         # Главы по номерам
```

### PartialProjectSeed

```python
class PartialProjectSeed(BaseModel):
    title_seed: Optional[str]
    project_description: Optional[str]
    learning_outcomes: List[str]
    required_tools: List[str]
    skills: List[str]
    tasks_count: Optional[int]
    theory_parts: List[str]
```

### ClassificationResult

```python
class ClassificationResult(BaseModel):
    language: str
    thematic_block: Optional[str]              # Существующий блок
    thematic_block_suggested: Optional[str]    # Предложенный новый блок
    thematic_block_name: Optional[str]         # Название нового блока
    audience_level: Optional[str]
    project_type: Optional[str]
```

## API Integration

### REST Endpoints

**Файл:** `api/routers/readme_improvement.py`

##### POST /api/v1/readme/improve/extract

Извлекает данные из README для последующего улучшения.

**Request:**
```json
{
    "readme_text": "текст README.md",
    "learning_outcomes": ["опционально", "для контекста"]
}
```

**Response:**
```json
{
    "request_id": "uuid",
    "status": "completed",
    "partial_seed": {
        "title_seed": "...",
        "project_description": "...",
        "learning_outcomes": ["..."],
        "skills": ["..."],
        "required_tools": ["..."],
        "tasks_count": 5
    },
    "classification": {
        "language": "ru",
        "thematic_block": "Cb",
        "audience_level": "Начальный",
        "project_type": "individual"
    },
    "metadata": {
        "warnings": ["..."],
        "errors": [],
        "extracted_fields": {...}
    }
}
```

##### POST /api/v1/readme/improve/generate

Генерирует улучшенный README на основе извлеченных и отредактированных данных.

**Request:**
```json
{
    "request_id": "uuid из extract",
    "seed": {
        // Полный ProjectSeed с отредактированными данными
        "title_seed": "...",
        "project_description": "...",
        "learning_outcomes": ["..."],
        "skills": ["..."],
        "thematic_block": "Cb",
        "language": "ru",
        // ... остальные поля
    }
}
```

**Response:**
```json
{
    "request_id": "uuid из extract",
    "status": "pending",
    "generation_request_id": "uuid для отслеживания генерации"
}
```

##### GET /api/v1/readme/improve/status/{generation_request_id}

Получает статус генерации улучшенного README.

**Response:**
```json
{
    "status": "completed",
    "result": {
        "markdown": "# Улучшенный README...",
        "rubric": {...},
        "text_stats": {...},
        "assets": {...}
    }
}
```

##### GET /api/v1/readme/improve/diff/{request_id}

Получает diff между исходным и улучшенным README.

**Response:**
```json
{
    "original": "# Исходный README...",
    "improved": "# Улучшенный README...",
    "diff": "..."
}
```

##### GET /api/v1/readme/improve/download/{generation_request_id}

Скачивает ZIP архив с улучшенным README и дочерними файлами.

**Response:**
- Content-Type: `application/zip`
- Content-Disposition: `attachment; filename=regen_<название>.zip`

## UI Integration

### Интерфейс улучшения README

**Файл:** `static/index.html`

Добавлена секция "📄 Улучшение README":

- **Textarea** для вставки исходного README.md
- **Загрузка файла** через file input
- **Кнопка "Извлечь данные"** для запуска извлечения
- **Форма редактирования** извлеченных данных (появляется после извлечения)
- **Кнопка "Сгенерировать улучшенный README"** для запуска генерации
- **Область статуса** с предупреждениями и ошибками
- **Кнопка "Скачать улучшенный README"** (появляется после успешной генерации)
- **Просмотр diff** между исходным и улучшенным README

### JavaScript функции

**Файл:** `static/js/main.js`

**Функции для улучшения README:**
- `handleReadmeFileSelectForImprovement(event)` — обработка загрузки файла
- `extractDataForImprovement()` — отправка запроса на извлечение данных
- `generateImprovedReadme()` — отправка отредактированных данных на генерацию
- `checkImprovementStatus()` — проверка статуса генерации
- `downloadImprovedReadme()` — скачивание ZIP архива с улучшенным README
- `showReadmeDiff()` — отображение diff между исходным и улучшенным README

**Обработка:**
- Отображение статуса обработки на каждом этапе
- Показ предупреждений и ошибок
- Автоматическое обновление статуса генерации
- Отображение прогресса генерации

## Конфигурация

### Промпты

**Директория:** `content_gen/prompts/reverse_extraction/`

```
reverse_extraction/
├── structure_extractor/
│   ├── system.md          # Системный промпт для извлечения
│   └── user_template.md   # Шаблон пользовательского промпта
└── classifier/
    ├── system.md          # Системный промпт для классификации
    └── user_template.md   # Шаблон пользовательского промпта
```

### Конфиги агентов

**Директория:** `content_gen/config/agents/`

- `structure_extractor.yaml` — конфиг для StructureExtractor
- `classifier.yaml` — конфиг для ClassifierAgent

**Структура конфига:**
```yaml
name: structure_extractor
version: "1.0.0"
llm:
  temperature: 0.1
  max_tokens: 2000
prompts:
  system:
    type: file
    path: content_gen/prompts/reverse_extraction/structure_extractor/system.md
  user_template:
    type: file
    path: content_gen/prompts/reverse_extraction/structure_extractor/user_template.md
```

## Использование

### Программный интерфейс

```python
from content_gen.reverse_extraction import ReverseExtractionOrchestrator
from content_gen.llm.client import LLMClient

# Инициализация
llm = LLMClient()
extraction_orchestrator = ReverseExtractionOrchestrator(llm)

# Извлечение данных
readme_text = """
# Название проекта

## Глава 1
Введение...

## Глава 2
Теория...

## Глава 3
### Задача 1
Практика...
"""

# Извлекаем данные
partial_seed, classification, normalized_readme, metadata = \
    extraction_orchestrator.extract_data_only(readme_text)

# Дальше клиент или API формирует итоговый ProjectSeed
# и передает его в /readme/improve/generate
```

### REST API

```bash
# Шаг 1: Извлечение данных
curl -X POST "http://localhost:8000/api/v1/readme/improve/extract" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "readme_text": "...",
    "learning_outcomes": ["опционально"]
  }'

# Ответ: {"request_id": "uuid", "partial_seed": {...}, "classification": {...}}

# Шаг 2: Редактирование данных (на клиенте)
# Пользователь редактирует partial_seed и classification

# Шаг 3: Генерация улучшенного README
curl -X POST "http://localhost:8000/api/v1/readme/improve/generate" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "uuid из extract",
    "seed": {
      // Отредактированный ProjectSeed
    }
  }'

# Ответ: {"request_id": "uuid", "generation_request_id": "uuid"}

# Шаг 4: Проверка статуса
curl -X GET "http://localhost:8000/api/v1/readme/improve/status/{generation_request_id}" \
  -H "Authorization: Bearer <token>"

# Шаг 5: Скачивание улучшенного README
curl -X GET "http://localhost:8000/api/v1/readme/improve/download/{generation_request_id}" \
  -H "Authorization: Bearer <token>" \
  -o improved_readme.zip
```

## Особенности реализации

### Structured Outputs

Все агенты, использующие LLM, применяют `StructuredLLMClient`:
- **StructureExtractor** → `PartialProjectSeed`
- **ClassifierAgent** → `ClassificationResult`

**Преимущества:**
- Гарантированное соответствие схеме
- Автоматическая валидация через Pydantic
- Fallback на JSON mode для неподдерживаемых моделей

### Интеграция с пайплайном генерации

Извлеченные данные передаются в основной пайплайн генерации:

1. **Конвертация данных:**
   - `PartialProjectSeed` и `ClassificationResult` возвращаются отдельно
   - Клиент или API слой собирает итоговый `ProjectSeed`
   - Это позволяет отредактировать извлеченные поля перед генерацией

2. **Запуск генерации:**
   - Используется существующий `Orchestrator.run()`
   - Выполняется полный пайплайн генерации (Phase 0-6)
   - Результат - улучшенный README с сохранением структуры исходного

3. **Кэширование:**
   - Исходный README сохраняется в `improvement_cache`
   - Извлеченные данные сохраняются для редактирования
   - Улучшенный README сохраняется после генерации
   - Поддерживается просмотр diff между исходным и улучшенным

### Проверка тематических блоков

**Двухэтапный процесс:**

1. **Поиск по ключевым словам:**
   - Загрузка `thematic_blocks.json`
   - Поиск ключевых слов в README
   - Сопоставление с существующими блоками

2. **LLM классификация (если не найдено):**
   - Агент получает список существующих блоков
   - Анализирует содержание
   - Может предложить новый блок с кодом и названием

### Обработка ошибок

**Стратегия:**
- Логирование всех ошибок на каждом этапе
- Fallback на базовые методы при ошибках LLM
- Возврат частичных результатов с предупреждениями
- Понятные сообщения об ошибках для пользователя

## Интеграция с основной системой

### Использование ProjectSeed

Система использует существующую модель `ProjectSeed` из `content_gen/models/schemas.py`:
- Максимальная совместимость с генератором
- Извлеченные данные маппятся в `ProjectSeed` на уровне API/клиента
- Прямая передача в пайплайн генерации для создания улучшенного README

### Конвертация данных

Отдельный `seed_converter.py` больше не используется.

Актуальный контракт такой:
- `extract_data_only()` возвращает `PartialProjectSeed` и `ClassificationResult`
- пользователь или API редактирует/дополняет данные
- в `/readme/improve/generate` передается уже готовый `ProjectSeed`

### Использование thematic_blocks.json

Проверка существующих блоков через:
- `api/routers/thematic_blocks.py` → `load_thematic_blocks()`
- Или прямое чтение `thematic_blocks.json`

## Расширяемость

### Добавление новых агентов

1. Создать агент в `content_gen/reverse_extraction/agents/`
2. Добавить в `agents/__init__.py`
3. Интегрировать в `Orchestrator`

### Добавление новых тематических блоков

1. Обновить `thematic_blocks.json`
2. Добавить ключевые слова в `ClassifierAgent._find_thematic_block_by_keywords()`

## Troubleshooting

### Проблема: Не извлекаются learning_outcomes

**Решение:**
- Проверьте, есть ли явные формулировки в README
- LLM переформулирует неявные результаты, но может пропустить если их нет

### Проблема: Не определяется thematic_block

**Решение:**
- Проверьте ключевые слова в README
- Если блок новый, система предложит его через `thematic_block_suggested`

## Метрики и мониторинг

### Логирование

Все этапы логируются:
- Нормализация README
- Извлечение структуры
- Классификация

### Метаданные

В ответе API возвращаются:
- Количество извлеченных полей
- Предупреждения и ошибки
- Статус выполнения

## Связанная документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — общая архитектура системы
- [AGENTS.md](AGENTS.md) — описание агентной системы
- [API.md](API.md) — REST API документация
- [DEPLOYMENT.md](DEPLOYMENT.md) — инструкции по развертыванию
