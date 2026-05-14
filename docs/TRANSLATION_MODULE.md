# Модуль перевода: CPO brief

Дата: 2026-05-12  
Аудитория: CPO, продуктовая команда, delivery/operations  
Статус: описание текущей реализации в репозитории

## 1. Executive summary

Модуль перевода расширяет Content Generator из генератора русскоязычных README в продукт для мультиязычной доставки учебного контента. В текущей реализации он покрывает два продуктовых сценария:

1. Перевод README/Markdown-документов на поддерживаемые языки.
2. Перевод видео через транскрипцию русской речи, генерацию субтитров и опциональный MP4 с вшитыми субтитрами.

Ключевая продуктовая ценность:

- сокращение ручной локализации учебных материалов;
- единый UX для генерации, проверки и перевода контента;
- сохранение структуры учебного README, кода, формул, таблиц и диаграмм;
- быстрый выход на мультиязычные потоки без отдельного translation management system;
- возможность масштабировать контент на регионы/языки `en`, `kg`, `uz`, `tg` при сохранении русского master-документа.

Важно: это не просто "вызов LLM для перевода". В модуле уже есть продуктовые guardrails: секционное разбиение, защита markdown-блоков, структурная валидация, repair непереведенных секций, async job model, прогресс выполнения и отдельные артефакты для видео.

## 2. Что уже реализовано

### 2.1 Документы README/Markdown

Пользовательский сценарий:

1. Пользователь открывает экран `/app/translate`.
2. Загружает `.md/.markdown/.txt` или вставляет markdown вручную.
3. Выбирает целевой язык и режим перевода.
4. Запускает перевод.
5. UI показывает прогресс и после завершения отображает original/translated side-by-side.
6. Пользователь скачивает переведенный Markdown.

Backend API:

- `POST /api/v1/translate/readme` стартует перевод и возвращает `request_id`.
- `GET /api/v1/translate/status/{request_id}` возвращает статус, фазу и результат.

Поддерживаемые языки:

| Код | Язык | Комментарий |
|---|---|---|
| `ru` | русский | пропуск перевода / identity path |
| `en` | английский | American English, простые формулировки |
| `kg` | киргизский | кириллица, контроль алфавита частично в видео-пайплайне |
| `uz` | узбекский | кириллица для субтитров |
| `tg` | таджикский | кириллица для субтитров |

Режимы перевода:

| Режим | Что делает | Продуктовый смысл |
|---|---|---|
| `literal` | Переводит документ максимально близко к оригиналу | Быстрее и дешевле; базовый режим |
| `combined` | Делает literal-перевод, затем refiner для читаемости, затем combiner | Выше качество текста, но выше latency/cost |

### 2.2 Перевод внутри основного generation flow

Если пользователь генерирует README не на русском языке, система сначала строит качественный русский master-документ, затем запускает Phase 6 `translate`.

Позиция в pipeline:

```text
context -> task_planning -> title_annotation -> skeleton -> theory -> practice
-> global_quality -> evaluation -> translate -> finalize
```

Причина такого дизайна: качество генерации и проверки держится на одном master-языке, а перевод выполняется после финальной оценки. Это снижает риск, что валидаторы и методологические проверки будут работать на нескольких языковых вариантах с разным качеством.

### 2.3 Видео и субтитры

Пользовательский сценарий:

1. Пользователь открывает `/app/translate` и переключается в режим видео.
2. Загружает видео до 100 MB.
3. Выбирает язык и тип результата: видео с субтитрами, только субтитры или оба варианта.
4. Система извлекает аудио, транскрибирует русскую речь, переводит сегменты, строит VTT/SRT/ASS и при необходимости рендерит MP4.
5. Пользователь скачивает доступные артефакты.

Backend API:

- `POST /api/v1/translate/video` стартует видео-задачу.
- `GET /api/v1/translate/status/{request_id}` возвращает прогресс и список доступных артефактов.
- `GET /api/v1/translate/download/{request_id}?type=video|vtt|srt|ass|transcript` скачивает результат.

Артефакты:

| Артефакт | Назначение |
|---|---|
| `subtitles.vtt` | WebVTT для web-плееров |
| `subtitles.srt` | универсальные субтитры |
| `subtitles.ass` | стилизованные субтитры |
| `transcript_ru.json` | русская транскрипция для аудита |
| `output_with_subs.mp4` | видео с вшитыми субтитрами, если рендер успешен |

## 3. Архитектура

### 3.1 Основные компоненты

| Слой | Компонент | Ответственность |
|---|---|---|
| UI | `static/translator.html`, `static/js/main.js` | загрузка файлов, выбор языка/режима, polling статуса, скачивание результата |
| API | `api/routers/readme_translate.py` | async endpoints, валидация входов, запуск фоновых задач, выдача статуса/артефактов |
| Application | `content_gen/phase_executors.py`, `content_gen/node_services.py` | typed contract Phase 6 внутри generation flow |
| Domain/LLM agent | `content_gen/agents/translator.py` | markdown translation, chunking, protection, validation, repair |
| Refinement | `content_gen/agents/translation_refiner.py` | улучшение читаемости и объединение literal/refined версии |
| Video pipeline | `content_gen/subtitles/pipeline.py`, `content_gen/subtitles/burned_pipeline.py` | audio extraction, ASR, segment translation, subtitle rendering, ffmpeg burn-in |
| Runtime state | `api/utils/result_cache.py` | in-memory job state, phase, progress, result TTL |
| Observability | `api/db/logging_db.py`, `api/db/user_runs_db.py`, logger | request logs, user runs, phase logs, ошибки pipeline |

### 3.2 Документный перевод: data flow

```text
Markdown input
  -> language/source validation
  -> protect_blocks(code, formulas, mermaid)
  -> section-aware chunking
  -> LLM translation per chunk
  -> restore protected blocks
  -> optional refiner
  -> optional combiner
  -> cleanup service prefixes/context headers
  -> structure validation
  -> language coverage gate
  -> repair untranslated sections
  -> retries with smaller chunks
  -> translated Markdown
```

Ключевой инженерный принцип: markdown-структура и технические блоки являются контрактом. LLM переводит текст, но не должен менять код, формулы, mermaid-блоки, ссылки и базовую структуру.

### 3.3 Видео-перевод: data flow

```text
Video upload
  -> file validation
  -> temp video storage
  -> extract audio via ffmpeg
  -> Whisper transcription, source language RU
  -> segment deduplication
  -> LLM translation by segment id
  -> strict JSON normalization
  -> missing-id fill rounds
  -> fallback to per-segment translation
  -> SRT/VTT/ASS build
  -> optional MP4 rendering via ffmpeg
  -> downloadable artifacts
```

Сегменты переводятся 1:1 по `id`. Это важно для таймингов: система не должна объединять или дробить реплики, иначе субтитры перестанут совпадать с видео.

## 4. Качество и guardrails

### 4.1 Уже реализованные механизмы качества

| Механизм | Где применяется | Зачем нужен |
|---|---|---|
| Защита блоков | README/Markdown | сохраняет код, LaTeX, mermaid и технические вставки |
| Section-aware chunking | README/Markdown | не разрывает заголовок и тело секции |
| Finish reason handling | README/Markdown | при обрезанном ответе делит chunk и повторяет перевод |
| Structural validation | README/Markdown | сравнивает количество/уровни заголовков, таблицы, mermaid |
| Language coverage gate | README/Markdown | ищет секции, похожие на оригинал, то есть вероятно непереведенные |
| Repair mode | README/Markdown | точечно переводит проблемные секции |
| Retry with smaller chunks | README/Markdown | снижает риск token overflow / частичного ответа |
| Strict JSON by segment id | Видео | сохраняет тайминги субтитров |
| Missing-id fill rounds | Видео | дозапрашивает пропущенные сегменты |
| Per-segment fallback | Видео | гарантирует завершение даже при batch failure |
| Async status polling | Оба сценария | пользователь не блокируется долгой операцией |

### 4.2 Остаточные риски качества

| Риск | Вероятность | Влияние | Текущая защита | Что нужно усилить |
|---|---:|---:|---|---|
| Непереведенные фразы в длинных README | средняя | среднее/высокое | language coverage + repair | добавить language-specific detectors и отчет покрытия |
| Потеря смысла при `combined` | низкая/средняя | среднее | combiner требует полноту literal-версии | добавить diff-based semantic validation |
| Терминологическая несогласованность | средняя | среднее | prompt-level правила | добавить glossary/termbase per track |
| Ошибка ASR в видео | средняя | высокое | Whisper + transcript artifact | вернуть опциональный ASR correction pass для high-quality режима |
| Неверная кириллица/латиница для `kg/uz/tg` | средняя | среднее | alphabet hints в subtitle translation | добавить hard validation и repair по алфавиту для README |
| Потеря job state при рестарте backend | средняя | среднее | отсутствует, in-memory cache | вынести translation jobs в Redis/Postgres |
| Долгий video render | средняя | среднее | progress + output_mode subtitles_only | очередь задач, worker pool, лимиты по duration |

## 5. Product behavior и UX-контракты

### 5.1 Статусы задач

Документный перевод:

| Status | Meaning |
|---|---|
| `in_progress` | задача выполняется |
| `completed` | перевод готов |
| `failed` | перевод завершился ошибкой |

Видео-перевод:

| Phase | Примерный progress | Meaning |
|---|---:|---|
| `queued` | 0% | задача поставлена в очередь |
| `extract_audio` | 10% | извлечение аудио |
| `chunk_audio` | 15% | подготовка аудио-чанков |
| `transcribe` | 35% | распознавание речи |
| `correct_asr` | 45% | зарезервированная фаза коррекции ASR |
| `translate` | 60% | перевод сегментов |
| `build_subtitles` | 75% | сборка VTT/SRT/ASS |
| `render_video` | 90% | рендер видео |
| `done` | 100% | результат готов |

### 5.2 Ограничения текущего UX

- Нет редактирования перевода внутри интерфейса перед скачиванием.
- Нет side-by-side quality report: пользователь видит результат, но не видит, какие секции проходили repair.
- Нет пользовательского glossary/терминологической базы.
- Нет выбора source language: текущая продуктовая модель исходит из русского master-документа и русской речи в видео.
- Для видео нет оценки длительности до старта.

## 6. Операционные ограничения

| Область | Текущее ограничение |
|---|---|
| Хранение job state | in-memory, TTL 2 часа для translation jobs |
| Хранение видео-артефактов | файловая директория `STORAGE_DIR/translations/{request_id}` |
| Размер видео | default 100 MB |
| Параллельность видео | `VIDEO_MAX_CONCURRENT_JOBS`; кодовый default 1, в `.env.example` указано 2 |
| ffmpeg | обязателен для audio extraction и video rendering |
| OpenAI API key | обязателен для Whisper ASR в текущем pipeline |
| LLM provider | OpenAI / DeepSeek / Azure / GigaChat через `LLMGateway` / LiteLLM; subtitle model может переопределяться env |
| Cache | LLM cache in-memory или Redis при `REDIS_URL`; result cache in-memory |

Продуктовое следствие: текущий модуль уже подходит для MVP/controlled rollout, но для production-нагрузки с SLA нужны persistent job queue, persistent artifact metadata и более явные retention policies.

## 7. Privacy, safety, compliance

Текущие меры:

- endpoints требуют аутентификацию через `get_current_user`;
- видеофайлы валидируются по расширению и размеру;
- временный исходный видеофайл удаляется после обработки;
- result artifacts хранятся под `request_id`;
- user run сохраняет принадлежность задачи пользователю;
- path traversal частично предотвращается через filename validation.

Зоны, которые нужно закрыть перед enterprise rollout:

- привязать доступ к `request_id` к владельцу задачи при скачивании и статусе;
- добавить retention policy для `STORAGE_DIR/translations`;
- добавить audit log скачиваний артефактов;
- маскировать потенциальные персональные данные в логах;
- определить политику передачи видео/текста внешним LLM/ASR провайдерам;
- добавить DPA/региональные ограничения, если контент студентов или внутренних сотрудников попадает в видео.

## 8. Метрики продукта и качества

### 8.1 Product metrics

| Метрика | Почему важна |
|---|---|
| Translation jobs started/completed/failed | базовая воронка использования |
| Completion rate by language | качество и надежность по языкам |
| Median / p95 latency by document size and video size | SLA и UX ожидания |
| Downloads per completed job | прокси полезности результата |
| Retry/repair rate | ранний сигнал деградации LLM или prompts |
| Video render failure rate | качество media pipeline |
| Mode mix: `literal` vs `combined` | спрос на качество против скорости |

### 8.2 Quality metrics

| Метрика | Как считать |
|---|---|
| Structure preservation rate | доля документов без structural validation issues |
| Untranslated section rate | доля секций, ушедших в repair / оставшихся после repair |
| Term consistency | сравнение с glossary по ключевым терминам |
| Subtitle id coverage | `%` сегментов с валидным переводом по id |
| ASR confidence proxy | ручная выборка transcript QA или WER на тестовом наборе |
| Human edit distance | сколько правок делает методолог после перевода |

### 8.3 Cost metrics

| Метрика | Комментарий |
|---|---|
| LLM calls per README | растет на длинных документах, repair и `combined` |
| Tokens per translated document | основной driver стоимости |
| ASR minutes per video | основной driver стоимости видео |
| Render CPU/GPU time | влияет на infra cost |
| Cache hit rate | снижает стоимость повторных операций |

## 9. Рекомендуемый rollout

### Phase A. Internal beta

Цель: проверить качество на реальных README и коротких учебных видео.

Scope:

- README translation: `ru -> en`;
- видео: subtitles_only как основной режим, MP4 render как optional;
- ручная QA-выборка методологом;
- сбор latency/cost/failure metrics.

Exit criteria:

- `completed` rate >= 95% для README;
- structural preservation >= 98%;
- untranslated section rate после repair < 2%;
- p95 README translation latency согласован с продуктовой командой;
- не менее 20 документов прошли human review.

### Phase B. Regional pilot

Цель: проверить языки `kg/uz/tg` на реальных пользователях.

Scope:

- добавить glossary по образовательным и техническим терминам;
- включить отчет качества перевода в UI;
- собирать feedback по фрагментам;
- добавить language/script validation для README.

Exit criteria:

- human acceptance rate >= 85% без существенной редакторской переработки;
- нет критичных ошибок в терминах для core glossary;
- video subtitle timing complaints < 5% задач.

### Phase C. Production hardening

Цель: сделать модуль надежным под регулярную нагрузку.

Scope:

- Redis/Postgres для translation jobs;
- worker queue для видео;
- retention policy и cleanup job;
- owner-based authorization для всех `request_id`;
- dashboard метрик;
- eval set и regression tests по языкам.

Exit criteria:

- восстановление после backend restart без потери job status;
- понятные SLA по документам и видео;
- мониторинг latency/cost/failure по языкам;
- документированная privacy policy для внешних LLM/ASR провайдеров.

## 10. Roadmap

| Priority | Инициатива | Продуктовый эффект |
|---|---|---|
| P0 | Persistent job storage | не теряем задачи при рестарте backend |
| P0 | Owner check для status/download | закрывает privacy/security risk |
| P0 | Translation QA report | CPO и методологи видят качество, repair, риски |
| P1 | Glossary/termbase per track | меньше терминологических ошибок |
| P1 | Language/script validators для README | меньше смешения языков и латиницы |
| P1 | Human feedback loop | данные для улучшения prompts/evals |
| P1 | Queue workers для видео | управляемая нагрузка и предсказуемый SLA |
| P2 | Multi-source language support | перевод не только из RU |
| P2 | Inline translation editor | меньше переключений в сторонние редакторы |
| P2 | Batch translation | массовая локализация пакета проектов |

## 11. Решения, которые нужно принять CPO

1. Основной quality tier для MVP: `literal` как default или `combined` как premium-quality режим.
2. Приоритет языков: начинать с `en` или сразу проверять `kg/uz/tg`.
3. Видео scope: только субтитры на первом релизе или MP4 render входит в обещание продукта.
4. Допустимый SLA: отдельно для README, коротких видео и длинных видео.
5. Политика качества: нужен ли обязательный human review перед публикацией перевода.
6. Privacy policy: можно ли отправлять видео/README внешним LLM/ASR провайдерам для всех клиентов.

## 12. Краткое позиционирование для стейкхолдеров

Модуль перевода превращает Content Generator в мультиязычную платформу доставки учебного контента. Технически это уже не прототип "переведи текст", а отдельный translation workflow с контрактами, асинхронным выполнением, контролем структуры и fallback-логикой. Для полноценного production rollout следующий главный шаг не в качестве промпта, а в надежности продуктового контура: persistent jobs, access control, quality reporting, glossary и eval-набор по языкам.
