# Навигация: корень репозитория

Конфигурация, инфраструктура и корневые markdown-документы.

## Документация (корень репозитория)

| Файл | Описание |
|------|------------|
| [`README.md`](../../README.md) | Обзор, установка, VSA |
| [`README_EN.md`](../../README_EN.md) | English README |
| [`TECH_SPEC.md`](../../TECH_SPEC.md) | Техспецификация (§3.1 Neo4j частично устарел) |
| [`INGESTION_LOADER.md`](../../INGESTION_LOADER.md) | CLI corpus loader |

Дополнительные материалы — в [`documentation.md`](./documentation.md) (`documentation/reference/`, `topics/`).

## Инфраструктура

| Файл | Описание |
|------|------------|
| [`docker-compose.yml`](../../docker-compose.yml) | Neo4j 5, Redis, neo4j-worker, API (опционально) |
| [`Dockerfile`](../../Dockerfile) | Backend + frontend static |
| [`Dockerfile.worker`](../../Dockerfile.worker) | Neo4j graph-sync worker |
| [`pyproject.toml`](../../pyproject.toml) / [`uv.lock`](../../uv.lock) | Зависимости Python 3.12 (uv) |
| [`.python-version`](../../.python-version) | Целевая версия Python |
| [`.env.example`](../../.env.example) | Шаблон секретов: LLM, Neo4j |

## Runtime (`.local/`, `logs/` — gitignored)

| Путь | Назначение |
|------|------------|
| `.local/db_state.pkl` | Персистентное состояние VSA-БД (default `HSME_DATABASE_FILE`) |
| `.local/audit_logs.jsonl` | Журнал аудита API (рядом с pickle) |
| `.local/graph_sync_outbox.db` | SQLite outbox (Stage 3 async graph sync) |
| `.local/snapshots/` | Локальные snapshot pickle (не в git) |
| `logs/relabel/` | Логи corpus relabel / ingestion |
| `data/` | Полный prod-корпус |
| `test_data/` | Test-корпус → [test_data.md](./test_data.md) |
| `ingestion_reports/` | Отчёты прогонов → [ingestion_reports.md](./ingestion_reports.md) |
| `.cache/hsme_corpus_loader/` | Кэш скачанных zip-архивов |

## Переменные окружения (ключевые)

**Neo4j:** `USE_NEO4J`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_CONNECTION_TIMEOUT`

**Graph sync (Stage 3):** `USE_ASYNC_GRAPH_SYNC`, `ASYNC_GRAPH_SYNC_REQUIRED`, `REDIS_URL`, `OUTBOX_DB_PATH`

**LLM:** OpenRouter / Yandex Cloud / Gemini — см. [`README.md §2`](../../README.md)

## Legacy

| Путь | Примечание |
|------|------------|
| [`legacy/static-ui/`](../../legacy/static-ui/) | Static dashboard до Next.js |
| [`main.py`](../../main.py) | Re-export `backend.app:app` для uvicorn |
