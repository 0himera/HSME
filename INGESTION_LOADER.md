# Corpus Ingestion Loader

Standalone-скрипт для скачивания, распаковки и запуска ingestion pipeline корпуса документов с публичных ссылок Яндекс.Диска.

## Что делает

1. Скачивает архив по публичному URL Яндекс.Диска (Public API) — опционально, флаг `--archive-url`.
2. Распаковывает содержимое в локальный кэш `.cache/hsme_corpus_loader/`.
3. Парсит DOCX/PDF и режет на чанки.
4. Вызывает LLM через `NLPExtractor` (OpenRouter или Yandex Cloud — см. `.env`) для извлечения сущностей и связей.
5. Создаёт `Experiment` и пишет в локальную VSA-базу (pickle).
6. Опционально дублирует данные в Neo4j (`USE_NEO4J`, по умолчанию включён; отключить — `--no-neo4j`).

Повторный запуск идемпотентен: чанки с уже существующим ID пропускаются до вызова LLM.

**Формат ID эксперимента** (`make_experiment_id` в `backend/services/ingestion.py`):

- Если в документе найден код: `EXP-{code}-{index:02d}` (например `EXP-CM-01-15-03`).
- Если `code=N/A`: `EXP-{file_slug}-{index:02d}`, где `file_slug` — slug из basename PDF/DOCX (например `EXP-ЖУРНАЛ-ГОРНЫЙ-1-2020-00`).

После смены формата ID старые `EXP-RAW-*` в `db_state.pkl` / Neo4j становятся orphan — нужен полный relabel (см. `corpus_relabel_loader`).

## Corpus relabel (YandexGPT)

CLI: `backend/repository/corpus_relabel_loader.py` — повторный NLP-инжест через YandexGPT 5.1 с перезаписью VSA и dual-write Neo4j.

```bash
# Resume: пропустить первые 10 файлов, обработать следующие 5 (test mode)
PYTHONPATH=. uv run python -m backend.repository.corpus_relabel_loader \
  --mode test --skip-files 10 --no-neo4j

# Dry-run (без LLM)
PYTHONPATH=. uv run python -m backend.repository.corpus_relabel_loader \
  --mode test --skip-files 10 --dry-run
```

После прогона пишется manifest: `ingestion_reports/{run_id}/summary.json` с полями `counts` (ok / restored / skipped / validation_failed / moderation / empty) и `chunk_outcomes`.

**Breaking change:** ID формата `EXP-RAW-{index}` больше не используется для журналов без кода — каждый файл получает уникальный slug.

## Связанные файлы

| Файл | Роль |
|------|------|
| `backend/repository/corpus_loader.py` | CLI entrypoint |
| `backend/core/config.py` | `resolve_llm_settings()` — CLI → env → `.env` |
| `backend/services/nlp_extractor.py` | OpenAI-compatible клиент, промпт из YAML |
| `backend/prompts/nlp_extractor.yaml` | Промпт entity/relation extraction |
| `backend/services/ingestion.py` | Пайплайн, идемпотентность, инъекция экстрактора |
| `backend/services/document_parser.py` | Сканирование каталогов, парсинг файлов |
| `.env.example` | Шаблон LLM-кредов |
| `backend/repository/corpus_relabel_loader.py` | Re-label CLI (YandexGPT), manifest |
| `tests/test_corpus_relabel_loader.py` | Юнит-тесты relabel |
| `tests/test_ingestion_ids.py` | Тесты `make_experiment_id` / slug |

## Быстрый старт

```bash
# 1. Креды LLM (обязательны для реального прогона, не dry-run)
cp .env.example .env
# отредактируйте .env — см. раздел «Креды LLM» ниже

# 2. Dry-run: только сканирование test_data/, без LLM и записи в БД
PYTHONPATH=. uv run python -m backend.repository.corpus_loader --mode test --dry-run

# 3. Test mode: до 15 файлов из test_data/ (папки Обзоры / Статьи / Доклады)
PYTHONPATH=. uv run python -m backend.repository.corpus_loader --mode test

# 4. Prod: полный корпус — локально из data/ или с Яндекс.Диска
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --archive-url "https://disk.yandex.ru/d/npigiuw4Rbe9Pg" \
  --mode prod \
  --no-neo4j
```

## Режим test vs prod

| | test | prod |
|---|------|------|
| Папка по умолчанию | `test_data/` | `data/` |
| Каталоги | только `Обзоры`, `Статьи`, `Доклады` | те же + всё под `Источники информации` |
| Лимит файлов | 15 | без лимита (`999999`) |

Переопределить лимит: `--max-files N`. Переопределить корень: `--data-dir /path/to/corpus`.

### Откуда взять test_data/

**Вариант A** — скачать сэмпл с Яндекс.Диска (локальный helper, каталог `scripts/` в `.gitignore`):

```bash
PYTHONPATH=. python3 scripts/download_yadisk_samples.py
```

Скрипт кладёт по одному файлу из каждой подпапки в `test_data/`.

**Вариант B** — сразу через loader с `--archive-url` (скачивает zip-архив в кэш).

## Креды LLM

Создайте `.env` в корне проекта из шаблона:

```bash
cp .env.example .env
```

**OpenRouter** (рекомендуется для локальной разработки):

```env
LLM_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
```

**Yandex Cloud**:

```env
LLM_API_KEY=AQVN...
LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1
LLM_FOLDER_ID=b1g...
LLM_MODEL=gpt://b1g.../yandexgpt-5.1/latest
```

Приоритет конфигурации: **CLI-флаги** → **переменные окружения процесса** → **`.env` файл** (путь — `--llm-env-file`, по умолчанию `.env`).

Жёстко зашитых API-ключей в коде нет. Для не-dry-run прогона нужны как минимум `LLM_API_KEY` и `LLM_BASE_URL`; для Yandex дополнительно `LLM_FOLDER_ID` или полный URI модели в `LLM_MODEL`.

```bash
# Достаточно .env:
PYTHONPATH=. uv run python -m backend.repository.corpus_loader --mode test

# Другой файл с секретами:
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --mode test \
  --llm-env-file secrets/llm.env

# Переопределение через CLI:
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --mode test \
  --llm-api-key "YOUR_API_KEY" \
  --llm-base-url "https://openrouter.ai/api/v1" \
  --llm-model-id "openai/gpt-4o-mini"
```

`--llm-folder-id` — ID каталога Yandex Cloud (не папка на Яндекс.Диске). Нужен только для YandexGPT; для OpenRouter не требуется.

## CLI-аргументы

| Аргумент | По умолчанию | Описание |
|----------|--------------|----------|
| `--archive-url` | — | Публичная ссылка Яндекс.Диска; скачивает архив в `.cache/hsme_corpus_loader/` |
| `--mode` | `test` | `test` — `test_data/`, 3 папки, до 15 файлов; `prod` — `data/`, полный корпус |
| `--max-files` | из mode | Явный лимит файлов |
| `--data-dir` | из mode | Корень корпуса (`test_data/` или `data/`) |
| `--db-file` | `db_state.pkl` | Pickle-файл VSA-базы (читается и дописывается) |
| `--llm-env-file` | `.env` | Dotenv с `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` и др. |
| `--llm-base-url` | из конфига | Base URL LLM API |
| `--llm-api-key` | из конфига | API key |
| `--llm-folder-id` | из конфига | Yandex Cloud folder ID |
| `--llm-model-id` | из конфига | ID модели (`LLM_MODEL` / `LLM_MODEL_ID`) |
| `--no-neo4j` | Neo4j включён | Отключить dual-write в Neo4j |
| `--dry-run` | `false` | Только парсинг и подсчёт чанков, без LLM и записи в БД |
| `--concurrency` | `6` | Параллельных чанков в LLM |

При `--llm-base-url` с `openrouter.ai` и дефолтном `--concurrency 6` loader автоматически снижает concurrency до `2`, чтобы реже упираться в rate limit.

## Детали реализации

1. **Идемпотентность.** ID через `make_experiment_id(doc_meta, chunk_index)`: код документа или `file_slug` + index. Если эксперимент уже в БД — LLM не вызывается.
2. **Tolerant validation.** NLP extractor принимает partial JSON: invalid relations отбрасываются, entities сохраняются.
3. **Neo4j writes.** По умолчанию — inline dual-write в том же процессе. При `USE_ASYNC_GRAPH_SYNC=true` событие попадает в SQLite outbox и relay в Redis Streams; Neo4j обновляет отдельный worker (`backend/workers/neo4j_consumer.py`).
4. **Отдельный экземпляр БД.** Loader создаёт свой `HSMEVectorDatabase` и пишет в `--db-file`, не трогая in-memory singleton FastAPI-приложения.
5. **Общая конфигурация LLM.** Loader и API (`/api/search`, ingestion) читают одни и те же переменные через `resolve_llm_settings()`; CLI-флаги loader'а переопределяют их только на время этого запуска.
6. **Кэш.** Скачанные архивы — в `.cache/hsme_corpus_loader/` (в `.gitignore`).

## Async graph sync (Stage 3)

VSA-first ingestion с eventual consistency для Neo4j:

1. `process_chunk` пишет эксперимент в VSA.
2. При `USE_ASYNC_GRAPH_SYNC=true` создаётся запись в SQLite outbox (`OUTBOX_DB_PATH`).
3. Relay публикует pending-события в Redis Stream (`REDIS_STREAM_KEY`).
4. Worker сначала **reclaim**-ит зависшие pending-сообщения (`XAUTOCLAIM` / `XCLAIM`), затем читает новые (`">"`) и вызывает `neo4j_graph.insert_experiment_async()`.

**Strict mode:** при `ASYNC_GRAPH_SYNC_REQUIRED=true` ошибка enqueue/relay поднимается до caller-а; chunk получает статус `graph_sync_failed`, ingestion не считается успешным.

**Ограничение docker-compose:** compose поднимает `redis`, `neo4j` и `neo4j-worker`, но **не** API/producer. Producer (loader или локальный API) должен использовать **тот же** `OUTBOX_DB_PATH`, что и worker.

```bash
# Общий outbox для локального producer + compose worker
mkdir -p .local/outbox
export OUTBOX_DB_PATH=.local/outbox/graph_sync_outbox.db

# Инфраструктура
docker compose up -d redis neo4j neo4j-worker

# Producer (локально, тот же OUTBOX_DB_PATH)
USE_ASYNC_GRAPH_SYNC=true USE_NEO4J=true REDIS_URL=redis://127.0.0.1:6379/0 \
  OUTBOX_DB_PATH=.local/outbox/graph_sync_outbox.db \
  PYTHONPATH=. uv run python -m backend.repository.corpus_loader --help

# Worker отдельно (если не через compose)
USE_ASYNC_GRAPH_SYNC=true REDIS_URL=redis://127.0.0.1:6379/0 \
  OUTBOX_DB_PATH=.local/outbox/graph_sync_outbox.db \
  PYTHONPATH=. uv run python -m backend.workers.neo4j_consumer
```

**Recovery smoke-run** (enqueue → publish → worker crash → restart → ack):

```bash
# 1) Включить async sync и общий outbox (см. выше)
# 2) Прогнать ingestion chunk / loader — outbox_pending → published
# 3) Остановить worker до ack (kill neo4j-worker)
# 4) Проверить lag: curl .../api/ingest-status → outbox_published_not_acked > 0
# 5) Запустить worker снова — pending reclaim → ack, outbox_published_not_acked → 0
# 6) Dead-letter / stale published replay:
PYTHONPATH=. uv run python -m backend.repository.replay_outbox --requeue-dead-letters
PYTHONPATH=. uv run python -m backend.repository.replay_outbox --requeue-stale-published 300
```

```bash
# Статус очереди (API)
curl -H "X-User-Role: Administrator" http://127.0.0.1:8000/api/ingest-status
# Поля: outbox_pending, outbox_published_not_acked, outbox_dead_letter, outbox_acked
```

Переменные окружения — см. `.env.example` (`USE_ASYNC_GRAPH_SYNC`, `REDIS_URL`, `OUTBOX_DB_PATH`, `ASYNC_GRAPH_SYNC_REQUIRED`, `REDIS_PENDING_MIN_IDLE_MS`, `OUTBOX_STALE_PUBLISHED_S`).

### Stage 3.1: residual risk coverage

**Non-strict deferred sync:** при ошибке enqueue/relay chunk получает статус `graph_sync_deferred` (VSA ok, graph sync отложен).

**Hybrid search lag hint:** paged `/api/search` возвращает `graph_enrichment_status` и `graph_sync_lag_hint`, если Neo4j ещё не догнал VSA.

**Auto stale recovery:** worker автоматически вызывает `requeue_stale_published(OUTBOX_STALE_PUBLISHED_S)` в начале цикла.

**VSA → outbox backfill:**

```bash
PYTHONPATH=. uv run python -m backend.repository.migration --via-outbox --dry-run
PYTHONPATH=. uv run python -m backend.repository.migration --via-outbox
```

**Pre-flight перед hybrid demo:**

```bash
curl -s -H "X-User-Role: Administrator" http://127.0.0.1:8000/api/ingest-status | python -m json.tool
# Ожидается: outbox_pending == 0, outbox_published_not_acked == 0
# Producer и worker используют один OUTBOX_DB_PATH
```

**После `--clear-neo4j` в relabel loader:** автоматически запускается direct backfill или `--via-outbox` backfill, чтобы VSA-only skip не оставил пустой граф.

## Тесты

```bash
USE_NEO4J=false PYTHONPATH=. uv run pytest tests/test_corpus_loader.py tests/test_corpus_relabel_loader.py tests/test_ingestion_ids.py tests/test_nlp_schemas.py tests/test_nlp_extractor.py tests/test_ingestion_neo4j.py tests/test_ingestion_outbox.py tests/test_graph_sync.py -q
```
