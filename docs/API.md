# API Документация

## Связанная документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — общая архитектура системы
- [DEPLOYMENT.md](DEPLOYMENT.md) — инструкции по развертыванию и настройке
- [AGENTS.md](AGENTS.md) — описание агентной системы
- [REVERSE_EXTRACTION.md](REVERSE_EXTRACTION.md) — система обратного извлечения данных из README

## Базовый URL

```
http://localhost:8000/api/v1
```

## Аутентификация

Большинство endpoints требуют JWT токен в заголовке:

```
Authorization: Bearer <token>
```

Получить токен можно через `/api/v1/auth/login`

## Endpoints

### Генерация контента

#### POST /generate

Генерирует контент учебного проекта.

**Требует аутентификации:** Да

**Rate limit:** 10 запросов в минуту

**Параметры:**
- `track_files` (multipart/form-data, legacy, опционально) — сохраняется для совместимости; production-контекст берется из `seed_data.curriculum_context`
- `seed_data` (JSON в form-data) — данные проекта:
  ```json
  {
    "track": "string",
    "project_type": "string",
    "project_description": "string",
    "learning_outcomes": ["string"],
    "skills": ["string"],
    "required_tools": ["string"],
    "language": "ru|en|ky",
    "bonus_wish": "string (опционально)"
  }
  ```

**Ответ:**
```json
{
  "request_id": "uuid",
  "status": "success|error",
  "message": "string",
  "markdown": "string (опционально)",
  "report_json": {}
}
```

**Пример:**
```bash
curl -X POST "http://localhost:8000/api/v1/generate" \
  -H "Authorization: Bearer <token>" \
  -F "seed_data={\"track\":\"Python\",\"project_type\":\"Practice\",...}" \
  -F "track_files=@file1.md" \
  -F "track_files=@file2.md"
```

### Перегенерация контента

#### POST /regenerate

Перегенерирует часть контента на основе комментариев.

**Требует аутентификации:** Да

**Тело запроса:**
```json
{
  "original_md": "string",
  "comments": "string",
  "language": "ru|en|ky"
}
```

**Ответ:**
```json
{
  "regenerated_md": "string",
  "changes": ["string"],
  "text_stats": {
    "word_count": 0,
    "char_count": 0
  }
}
```

### Скачивание результатов

#### GET /download/{request_id}

Скачивает результаты генерации по request_id.

**Требует аутентификации:** Да

**Параметры:**
- `request_id` (path) — ID запроса
- `include_regenerated` (query, опционально) — включить перегенерированную версию

**Ответ:** ZIP архив с README и assets

### Health Check

#### GET /health

Проверка здоровья сервиса.

**Требует аутентификации:** Нет

**Ответ:**
```json
{
  "status": "healthy|unhealthy|degraded",
  "checks": {
    "database": {"status": "ok|error", "message": "string"},
    "llm": {"status": "ok|warning", "available": true|false},
    "resources": {
      "memory_percent": 0.0,
      "cpu_percent": 0.0
    }
  }
}
```

### Метрики

#### GET /metrics

Получение метрик системы.

**Требует аутентификации:** Да

**Ответ:**
```json
{
  "total_requests": 0,
  "successful_requests": 0,
  "failed_requests": 0,
  "average_generation_time": 0.0,
  "active_users": 0
}
```

### Аутентификация

#### POST /auth/login

Вход в систему.

**Требует аутентификации:** Нет

**Тело запроса:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Ответ:**
```json
{
  "access_token": "string",
  "token_type": "bearer",
  "user_id": "string",
  "session_id": "string"
}
```

### Административные функции

#### GET /admin/stats/users

Статистика по пользователям.

**Требует аутентификации:** Да (админ)

**Параметры:**
- `days` (query, опционально) — количество дней (по умолчанию 7)

**Ответ:**
```json
{
  "total_users": 0,
  "active_users": 0,
  "total_requests": 0,
  "requests_by_user": {}
}
```

#### GET /admin/stats/requests

Статистика по запросам.

**Требует аутентификации:** Да (админ)

**Параметры:**
- `days` (query, опционально) — количество дней

**Ответ:**
```json
{
  "total_requests": 0,
  "successful": 0,
  "failed": 0,
  "average_time": 0.0,
  "requests_by_day": {}
}
```

## Коды ошибок

- `400` — Неверный запрос
- `401` — Не авторизован
- `403` — Доступ запрещен
- `429` — Превышен rate limit
- `500` — Внутренняя ошибка сервера

## Rate Limiting

- `/generate`: 10 запросов в минуту
- Остальные endpoints: без ограничений (или по умолчанию)

## WebSocket (если реализовано)

Для отслеживания прогресса генерации можно использовать WebSocket (если реализовано).

## Структура ответов

### report_json

Поле `report_json` в ответе `/generate` содержит:

- `task_plan` — план практических задач (количество, сложность, обоснование)
- `context` — метаданные контекста учебного плана (позиция проекта, соседние проекты, метрики сборки контекста)
- `context_analysis` — результаты анализа контекста (выравнивание навыков, LO, инструментов)
- `practice_critic_issues` — проблемы, найденные PracticeCriticAgent
- `agent_config_versions` — версии конфигов агентов, использованных при генерации
- `flow_trace` — трассировка выполнения AgentFlow (шаги, статусы, длительность)

**Подробнее:** См. [ARCHITECTURE.md](ARCHITECTURE.md) и [AGENTS.md](AGENTS.md) для понимания структуры данных.

## Примеры использования

### Python

```python
import requests

# Вход
response = requests.post(
    "http://localhost:8000/api/v1/auth/login",
    json={"username": "user", "password": "pass"}
)
token = response.json()["access_token"]

# Генерация
headers = {"Authorization": f"Bearer {token}"}
files = {"track_files": open("project.md", "rb")}
data = {
    "seed_data": {
        "track": "Python",
        "project_type": "Practice",
        "project_description": "Описание проекта",
        "learning_outcomes": ["Результат 1"],
        "skills": ["Python"],
        "language": "ru"
    }
}

response = requests.post(
    "http://localhost:8000/api/v1/generate",
    headers=headers,
    files=files,
    data=data
)
result = response.json()
```

### JavaScript

```javascript
// Вход
const loginResponse = await fetch('http://localhost:8000/api/v1/auth/login', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({username: 'user', password: 'pass'})
});
const {access_token} = await loginResponse.json();

// Генерация
const formData = new FormData();
formData.append('seed_data', JSON.stringify({
  track: 'Python',
  project_type: 'Practice',
  // ...
}));

const response = await fetch('http://localhost:8000/api/v1/generate', {
  method: 'POST',
  headers: {'Authorization': `Bearer ${access_token}`},
  body: formData
});
const result = await response.json();
```
