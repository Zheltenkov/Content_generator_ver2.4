# Инструкция по разворачиванию на сервере

## Связанная документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — общая архитектура системы
- [API.md](API.md) — REST API документация
- [AGENTS.md](AGENTS.md) — описание агентной системы и конфигурации
- [REVERSE_EXTRACTION.md](REVERSE_EXTRACTION.md) — система обратного извлечения данных из README
- [TESTING.md](TESTING.md) — система тестирования

## Подготовка к разворачиванию

### 1. Проверка окружения

Убедитесь, что на сервере установлены:
- Python 3.12+
- PostgreSQL 14+
- Git

### 2. Настройка переменных окружения

Создайте файл `.env` в корне проекта на основе `.env.example`:

```bash
# База данных (обязательно PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost:5432/content_generator

# Логирование и runtime
LOG_LEVEL=INFO
DB_ECHO=false
HOST=0.0.0.0
PORT=8000
RELOAD=false

# CORS (разрешенные домены, через запятую)
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# JWT секреты (сгенерируйте случайные строки)
JWT_SECRET_KEY=your-secret-key-here
JWT_EXPIRATION_HOURS=24

# OpenAI API (если используется)
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=gpt-4.1-mini

# Другие настройки
ACTIVITY_UPDATE_INTERVAL_SECONDS=60
ENABLE_EMAIL=false
```

---

## Разворачивание (пошагово)

### Шаг 1: Клонирование/обновление кода

```bash
# Если первый раз:
git clone <repository-url>
cd Content_generator_ver1

# Если обновление:
git pull origin main  # или master
```

### Шаг 2: Установка зависимостей

```bash
# Создайте виртуальное окружение (если еще нет)
python -m venv venv

# Активируйте виртуальное окружение
# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Установите зависимости
pip install -r requirements.txt
```

### Шаг 3: Настройка базы данных

#### Вариант A: PostgreSQL (рекомендуется для production)

```bash
# 1. Создайте базу данных (если еще не создана)
sudo -u postgres psql
CREATE DATABASE content_generator;
CREATE USER content_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE content_generator TO content_user;
\q

# 2. Проверьте подключение
psql -h localhost -U content_user -d content_generator

# 3. Убедитесь, что DATABASE_URL в .env указывает на PostgreSQL:
# DATABASE_URL=postgresql://content_user:your_password@localhost:5432/content_generator
```

### Шаг 4: Создание миграций для новых таблиц

```bash
# 1. Проверьте текущее состояние миграций
alembic current

# 2. Создайте новую миграцию для таблиц generation_results, rubric_results, report_results
alembic revision --autogenerate -m "add_generation_results_tables"

# 3. Проверьте созданный файл миграции
# Он должен быть в migrations/versions/004_add_generation_results_tables.py
# Убедитесь, что там есть создание всех трех таблиц:
# - generation_results
# - rubric_results  
# - report_results

# 4. Примените миграцию
alembic upgrade head

# 5. Проверьте, что миграция применена
alembic current
```

> ⚠️ После обновления кода убедитесь, что выполнена ревизия `004_add_config_versions_and_practice_critic.py`, добавляющая новые JSON-поля в `generation_results`. Команда: `alembic upgrade head`.

**Важно:** Если миграция не создалась автоматически (alembic не увидел изменения), создайте её вручную:

```bash
alembic revision -m "add_generation_results_tables"
```

Затем отредактируйте созданный файл в `migrations/versions/` и добавьте код создания таблиц (см. пример ниже).

### Шаг 5: Проверка структуры БД

#### Для PostgreSQL:

```bash
psql -h localhost -U content_user -d content_generator

# Проверьте наличие таблиц:
\dt

# Должны быть:
# - logs
# - user_sessions
# - request_logs
# - generation_results  ← новая
# - rubric_results      ← новая
# - report_results      ← новая

# Проверьте структуру новой таблицы:
\d generation_results

# Должны быть колонки:
# - id
# - request_id (UNIQUE)
# - user_id
# - seed_data (JSON)
# - markdown (TEXT)
# - text_stats (JSON)
# - task_plan (JSON)
# - issues (JSON)
# - regenerated_markdown (TEXT)
# - regeneration_comments (TEXT)
# - regeneration_changes (JSON)
# - original_markdown (TEXT)
# - created_at
# - updated_at

# Проверьте foreign keys:
\d rubric_results
\d report_results

# Оба должны иметь:
# - generation_result_id (FK -> generation_results.id, CASCADE DELETE)

# Выйдите из psql:
\q
```

### Контекст генерации

В текущем production-контуре локальный каталог `data/` и предварительное построение retrieval-индекса не требуются.

- Генерация использует `curriculum_context`, переданный во входном `seed`.
- Для запуска сервиса достаточно корректного `.env`, базы данных, статических файлов и API-доступа к LLM.
- Отсутствие локального retrieval-индекса не считается ошибкой развертывания.

### Проверка YAML-конфигов и Flow

**Подробнее:** См. [AGENTS.md](AGENTS.md) для описания структуры конфигов и AgentFlow.

Все агенты конфигурируются через `content_gen/config/agents/*.yaml`, а пайплайн описан в `content_gen/config/flow.yaml`. 

**Конфиги для Reverse Extraction:**
- `content_gen/config/agents/structure_extractor.yaml` — конфиг для извлечения структуры
- `content_gen/config/agents/classifier.yaml` — конфиг для классификации
- Промпты в `content_gen/prompts/reverse_extraction/`

Перед деплоем:

1. Проверьте, что в каждом YAML указаны `version` и, при необходимости, `updated_at`.
2. Убедитесь, что файлы доступны для чтения сервисом (ConfigLoader лениво загружает их с диска и кеширует в памяти).
3. При необходимости обновите промпты/LLM-параметры — изменения попадут в логи (`agent_config_versions`) и в БД (`generation_results`).
4. Если Flow дорабатывается (добавляются узлы/условия), укладывайте изменения в `config/flow.yaml` — рантайм AgentFlow автоматически проверяет граф на циклы.

### Шаг 6: Альтернативный способ (если Alembic не используется)

Если по какой-то причине Alembic не работает, можно использовать встроенную функцию `init_db()`:

```bash
# Запустите Python и выполните:
python -c "from api.db.session import init_db; init_db(); print('✅ Таблицы созданы')"
```

**⚠️ Внимание:** Этот способ создаст все таблицы, но не будет отслеживать версии миграций. Используйте только если Alembic недоступен.

### Шаг 7: Запуск приложения

```bash
# Проверьте, что виртуальное окружение активно
which python  # должен показать путь к venv

# Запустите приложение
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Или с помощью run.py (если есть):
python run.py
```

### Шаг 8: Проверка работоспособности

#### 8.1. Health Check

```bash
curl http://localhost:8000/api/v1/health
```

Должен вернуть:
```json
{"status": "ok", "database": "connected"}
```

#### 8.2. Проверка логирования

Проверьте логи приложения — не должно быть ошибок подключения к БД:

```bash
# Если логи в файле:
tail -f logs/app.log

# Или в консоли при запуске uvicorn должны быть сообщения:
# INFO:     Application startup complete.
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

#### 8.3. Тестовая генерация

1. Откройте UI: `http://your-server:8000`
2. Войдите в систему
3. Создайте тестовый проект
4. После генерации проверьте БД:

```sql
-- PostgreSQL:
SELECT id, request_id, user_id, created_at 
FROM generation_results 
ORDER BY created_at DESC 
LIMIT 1;

-- Проверьте связанные таблицы:
SELECT r.id, r.generation_result_id, r.created_at 
FROM rubric_results r
JOIN generation_results g ON r.generation_result_id = g.id
ORDER BY r.created_at DESC 
LIMIT 1;

SELECT r.id, r.generation_result_id, r.created_at 
FROM report_results r
JOIN generation_results g ON r.generation_result_id = g.id
ORDER BY r.created_at DESC 
LIMIT 1;
```

#### 8.4. Проверка скачивания ZIP

1. После генерации нажмите "Скачать"
2. Распакуйте архив
3. Должны быть:
   - `[Track][Index]_Title.md` (README с правильным именем)
   - `images/` (папка с диаграммами, если есть)
   - **НЕ должно быть:** `rubric.json`, `report.json`

---

## Откат миграций (если что-то пошло не так)

```bash
# 1. Посмотрите историю миграций
alembic history

# 2. Откатитесь на одну миграцию назад
alembic downgrade -1

# 3. Или откатитесь к конкретной версии
alembic downgrade <revision_id>

# 4. Проверьте состояние
alembic current
```

---

## Резервное копирование БД

### PostgreSQL:

```bash
# Создайте бэкап
pg_dump -h localhost -U content_user -d content_generator > backup_$(date +%Y%m%d_%H%M%S).sql

# Восстановление из бэкапа
psql -h localhost -U content_user -d content_generator < backup_20240101_120000.sql
```

---

## Мониторинг и диагностика

### Проверка размера таблиц (PostgreSQL):

```sql
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Проверка последних записей:

```sql
-- Последние 10 генераций
SELECT 
    g.id,
    g.request_id,
    g.user_id,
    g.created_at,
    CASE WHEN g.regenerated_markdown IS NOT NULL THEN 'Yes' ELSE 'No' END AS has_regeneration,
    (SELECT COUNT(*) FROM rubric_results r WHERE r.generation_result_id = g.id) AS has_rubric,
    (SELECT COUNT(*) FROM report_results r WHERE r.generation_result_id = g.id) AS has_report
FROM generation_results g
ORDER BY g.created_at DESC
LIMIT 10;
```

### Проверка целостности Foreign Keys:

```sql
-- Должно вернуть 0 строк (нет "осиротевших" записей)
SELECT r.id, r.generation_result_id
FROM rubric_results r
LEFT JOIN generation_results g ON r.generation_result_id = g.id
WHERE g.id IS NULL;

SELECT r.id, r.generation_result_id
FROM report_results r
LEFT JOIN generation_results g ON r.generation_result_id = g.id
WHERE g.id IS NULL;
```

---

## Troubleshooting

### Проблема: "Table already exists"

**Решение:**
```bash
# Проверьте, какие таблицы уже есть
alembic current

# Если таблицы созданы вручную через init_db(), но миграции нет:
# 1. Создайте пустую миграцию
alembic revision -m "mark_generation_results_as_existing"

# 2. В файле миграции замените upgrade() на:
def upgrade():
    # Таблицы уже существуют, ничего не делаем
    pass

# 3. Примените миграцию
alembic upgrade head
```

### Проблема: "Foreign key constraint failed"

**Решение:**
```sql
-- Проверьте, нет ли записей с несуществующими generation_result_id
-- Если есть — удалите их или исправьте вручную
```

### Проблема: "Connection refused" к PostgreSQL

**Решение:**
```bash
# 1. Проверьте, запущен ли PostgreSQL
sudo systemctl status postgresql

# 2. Проверьте настройки в pg_hba.conf
sudo nano /etc/postgresql/14/main/pg_hba.conf

# 3. Проверьте, слушает ли PostgreSQL на нужном порту
sudo netstat -tlnp | grep 5432
```

### Проблема: "No module named 'api'"

**Решение:**
```bash
# Убедитесь, что вы в корневой директории проекта
pwd  # должен показать путь к Content_generator_ver1

# Убедитесь, что виртуальное окружение активно
which python

# Переустановите зависимости
pip install -r requirements.txt
```

### Проблема: Миграция не видит новые таблицы

**Решение:**
```bash
# 1. Убедитесь, что все модели импортированы в api/db/models.py
# 2. Проверьте, что Base.metadata включает все модели
# 3. Попробуйте создать миграцию вручную:

alembic revision -m "add_generation_results_tables"

# Затем отредактируйте файл миграции и добавьте код создания таблиц
```

---

## Production рекомендации

1. **Используйте PostgreSQL** для всех окружений
2. **Настройте автоматические бэкапы** БД (cron job)
3. **Мониторьте размер БД** — таблицы могут расти быстро
4. **Настройте логирование** в файлы с ротацией
5. **Используйте reverse proxy** (nginx) перед приложением
6. **Настройте SSL/TLS** для HTTPS
7. **Ограничьте доступ** к БД только с сервера приложения
8. **Используйте connection pooling** для PostgreSQL
9. **Настройте мониторинг** (Prometheus, Grafana)
10. **Регулярно проверяйте целостность данных** (foreign keys, индексы)

### Пример настройки systemd service (Linux):

Создайте файл `/etc/systemd/system/content-generator.service`:

```ini
[Unit]
Description=Content Generator API
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/Content_generator_ver1
Environment="PATH=/path/to/Content_generator_ver1/venv/bin"
ExecStart=/path/to/Content_generator_ver1/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Затем:
```bash
sudo systemctl daemon-reload
sudo systemctl enable content-generator
sudo systemctl start content-generator
sudo systemctl status content-generator
```

---

## Тестирование после развертывания

### Тестирование Reverse Extraction

**Подробнее:** См. [REVERSE_EXTRACTION.md](REVERSE_EXTRACTION.md) для полного описания системы.

1. **Проверка API endpoint:**
```bash
# Извлечение данных из README
curl -X POST "http://localhost:8000/api/v1/reverse-extract/extract" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"readme_text": "# Тестовый проект\n\n## Глава 1\n..."}'
```

2. **Проверка UI:**
   - Откройте `http://your-server:8000/app/generate`
   - Найдите секцию "📄 Извлечение данных из README"
   - Вставьте тестовый README.md
   - Нажмите "Извлечь данные"
   - Проверьте, что появилась кнопка "Скачать Excel"
   - Скачайте и проверьте Excel файл

3. **Проверка конфигов:**
   - Убедитесь, что существуют `content_gen/config/agents/structure_extractor.yaml` и `classifier.yaml`
   - Проверьте, что промпты доступны в `content_gen/prompts/reverse_extraction/`

4. **Проверка thematic_blocks.json:**
   - Убедитесь, что файл `thematic_blocks.json` существует в корне проекта
   - Проверьте, что ClassifierAgent может загрузить блоки

## Тестирование после развертывания (основные функции)

**Подробнее:** См. [TESTING.md](TESTING.md) для полного описания системы тестирования.

После развертывания рекомендуется запустить тесты:

```bash
# Запуск всех тестов
pytest

# Запуск только unit-тестов (быстрые)
pytest -m unit

# Запуск интеграционных тестов
pytest -m integration

# Запуск с покрытием кода
pytest --cov=content_gen --cov-report=html
```

**Важно:** Медленные тесты (требующие LLM API) можно пропустить при проверке развертывания:
```bash
pytest -m "not slow"
```

## Чек-лист перед запуском в production

- [ ] Переменные окружения настроены (`.env` на основе `.env.example`)
- [ ] PostgreSQL создан и доступен
- [ ] Миграции применены (`alembic upgrade head`)
- [ ] Таблицы созданы и проверены
- [ ] YAML-конфиги проверены (версии, доступность)
- [ ] Health check возвращает `{"status": "ok"}`
- [ ] Тестовая генерация работает
- [ ] ZIP скачивается с правильным именем файла
- [ ] Данные сохраняются в БД
- [ ] Логирование работает
- [ ] Тесты пройдены (опционально, но рекомендуется)
- [ ] Бэкапы настроены
- [ ] SSL/TLS настроен (HTTPS)
- [ ] Firewall настроен
- [ ] Мониторинг настроен
- [ ] Systemd service настроен (если используется)

---

## Обновление существующего развертывания

При обновлении кода с новыми изменениями:

```bash
# 1. Остановите приложение (если запущено через systemd)
sudo systemctl stop content-generator

# 2. Создайте бэкап БД
pg_dump -h localhost -U content_user -d content_generator > backup_before_update_$(date +%Y%m%d_%H%M%S).sql

# 3. Обновите код
git pull origin main

# 4. Обновите зависимости (если изменились)
pip install -r requirements.txt

# 5. Примените новые миграции
alembic upgrade head

# 6. Проверьте, что миграции применены
alembic current

# 7. Запустите приложение
sudo systemctl start content-generator

# 8. Проверьте логи
sudo journalctl -u content-generator -f
```

---

## Контакты и поддержка

При возникновении проблем:
1. Проверьте логи приложения
2. Проверьте логи БД
3. Проверьте статус сервисов (PostgreSQL, приложение)
4. Обратитесь к документации:
   - [ARCHITECTURE.md](ARCHITECTURE.md) — общая архитектура
   - [API.md](API.md) — API документация
   - [AGENTS.md](AGENTS.md) — агентная система
   - [REVERSE_EXTRACTION.md](REVERSE_EXTRACTION.md) — система обратного извлечения
   - [CRITERIA.md](CRITERIA.md) — система валидации
   - [TESTING.md](TESTING.md) — тестирование
