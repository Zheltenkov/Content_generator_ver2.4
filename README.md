# Content Generator для Школы 21

Система автоматической генерации учебного контента для проектов Школы 21.

## Описание

Content Generator создает структурированные README-файлы для учебных проектов с использованием LLM и curriculum-aware контекста.

**Основные возможности:**
- Генерация полного README проекта
- Проверка README по 39 критериям качества
- Обратное извлечение данных из README
- Поддержка нескольких языков (ru, en, kg, uz)
- Веб-интерфейс и REST API

**Технологии:**
- LLM для генерации контента
- Curriculum-aware контекст из учебного плана в production-контуре
- Извлечение ЗУНов и служебные LLM-утилиты для regeneration/reverse extraction
- Модульная валидация по критериям качества
- Фазовый пайплайн генерации с встроенными проверками

## Структура проекта

```
Content Generator
│
├── 📦 content_gen/              # Ядро системы генерации
│   │
│   ├── 🤖 agents/               # Агенты генерации контента
│   │   ├── theory.py            # Генерация теоретической части
│   │   ├── practice.py          # Генерация практических заданий
│   │   ├── skeleton.py          # Создание каркаса документа
│   │   └── ...                  # Другие специализированные агенты
│   │
│   ├── ✅ validators/           # Валидаторы качества
│   │   ├── rubric/              # Проверка по критериям рубрики
│   │   ├── structural/          # Проверка структуры
│   │   └── ...                  # Другие валидаторы
│   │
│   ├── 🎯 orchestrator.py       # Оркестратор пайплайна (AgentFlow)
│   │
│   ├── 📋 orchestrator_phases_modules/  # Модули фаз генерации
│   │   └── phases/              # Phase 0-7 (Curriculum Context → Skeleton → Theory → Practice → Quality → Antiplag → Evaluation → Translate)
│   │
│   ├── 📚 curriculum/           # Контекст учебного плана и граф проектов
│   ├── 🧩 extraction/           # Служебное извлечение ЗУНов
│   │
│   ├── 🔄 reverse_extraction/   # Обратное извлечение данных
│   │   ├── agents/              # Агенты извлечения
│   │   ├── orchestrator.py      # Оркестратор извлечения
│   │   └── excel_writer.py      # Запись в Excel
│   │
│   ├── 🧠 llm/                  # Клиенты LLM
│   │   ├── client.py            # Базовый клиент
│   │   └── structured_output.py # Структурированные выходы
│   │
│   ├── ⚙️ config/               # Конфигурация
│   │   ├── agents/              # Конфиги агентов
│   │   ├── flow.yaml            # Граф выполнения (AgentFlow, исполняемый)
│   │   └── flow_documented.yaml # Карта процессов (описание нод/входов/выходов)
│   │
│   └── 📝 prompts/              # Шаблоны промптов
│
├── 🌐 api/                      # FastAPI приложение
│   │
│   ├── 📡 routers/              # API endpoints
│   │   ├── generation.py        # Генерация контента
│   │   ├── reverse_extraction.py # Извлечение данных
│   │   └── ...                  # Другие endpoints
│   │
│   ├── 💾 db/                   # База данных
│   │   ├── models.py            # SQL модели
│   │   └── session.py           # Сессии БД
│   │
│   └── 🔧 middleware/           # Middleware
│       ├── request_logging.py   # Логирование запросов
│       └── activity_tracking.py # Трекинг активности
│
├── 🎨 static/                   # Веб-интерфейс
│   ├── index.html               # Страница генерации
│   ├── checker.html             # Страница проверки
│   ├── js/main.js               # JavaScript логика
│   └── css/styles.css           # Стили
│
├── 🧪 tests/                    # Тесты
    ├── agents/                  # Тесты агентов
    ├── validators/              # Тесты валидаторов
    └── integration/             # Интеграционные тесты

```

**Основные компоненты:**

- **`content_gen/`** — ядро системы: агенты генерации, валидаторы, оркестратор, контекст учебного плана, обратное извлечение
- **`api/`** — REST API: endpoints, модели БД, middleware для логирования и трекинга
- **`static/`** — веб-интерфейс: HTML страницы, JavaScript, CSS
- **`tests/`** — тесты: unit-тесты, интеграционные тесты
- **`docs/`** — документация: архитектура, API, инструкции

Подробная документация по каждому компоненту: [docs/](docs/)

## Установка

**Требования:**
- Python 3.12+
- PostgreSQL 14+
- OpenAI API ключ

**Шаги:**
1. Клонируйте репозиторий и перейдите в директорию
2. Создайте виртуальное окружение: `python -m venv venv`
3. Активируйте окружение: `source venv/bin/activate` (Linux/Mac) или `venv\Scripts\activate` (Windows)
4. Установите зависимости: `pip install -r requirements.txt`
5. Создайте `.env` на основе `.env.example` и настройте переменные окружения
6. Инициализируйте БД: `alembic upgrade head`

## Запуск

**Разработка:**
```bash
python run.py
```

**Production:**
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Сервер доступен по адресу: `http://127.0.0.1:8000`

## Использование

**Веб-интерфейс:** `http://127.0.0.1:8000`

**API документация:** `http://127.0.0.1:8000/docs`

**Инструкция для пользователей:** [docs/ИНСТРУКЦИЯ_ПО_ИСПОЛЬЗОВАНИЮ.md](docs/ИНСТРУКЦИЯ_ПО_ИСПОЛЬЗОВАНИЮ.md)

## Тестирование

```bash
pytest
pytest --cov=content_gen --cov=api  # с покрытием
```

## Документация

- [Карта процессов (Flow)](docs/flow_map.md) — ноды, входы/выходы, условия переходов пайплайна генерации
- [💰 Бизнес-выгоды и ROI](docs/BUSINESS_VALUE.md) - экономическая эффективность и выгоды внедрения
- [Архитектура](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [Агентная система](docs/AGENTS.md)
- [Карта процессов](docs/flow_map.md)
- [Критерии качества](docs/CRITERIA.md)
- [Обратное извлечение](docs/REVERSE_EXTRACTION.md)
- [Инструкция по использованию](docs/ИНСТРУКЦИЯ_ПО_ИСПОЛЬЗОВАНИЮ.md)
