# Навигация: `backend/`

FastAPI-приложение: VSA retrieval, Neo4j dual-write, NLP ingestion, eval L0–L4.

## Точки входа

| Путь | Назначение |
|------|------------|
| [`app.py`](../../backend/app.py) | Сборка FastAPI: роутеры, CORS, lifespan (Neo4j bootstrap), static frontend |
| [`main.py`](../../backend/main.py) | Re-export `app` для Uvicorn |
| [`repository/corpus_loader.py`](../../backend/repository/corpus_loader.py) | CLI массового ingestion (`python -m backend.repository.corpus_loader`) |
| [`repository/corpus_relabel_loader.py`](../../backend/repository/corpus_relabel_loader.py) | CLI relabel с перезаписью существующих экспериментов |
| [`repository/migration.py`](../../backend/repository/migration.py) | Backfill VSA → Neo4j (`--dry-run`, `--via-outbox`) |
| [`evaluation/runners/run_e2e_eval.py`](../../backend/evaluation/runners/run_e2e_eval.py) | E2E eval L0–L4 |
| [`evaluation/runners/run_retrieval_eval.py`](../../backend/evaluation/runners/run_retrieval_eval.py) | Retrieval eval L1–L2 |
| [`workers/neo4j_consumer.py`](../../backend/workers/neo4j_consumer.py) | Async worker: Redis Streams → Neo4j MERGE (Stage 3) |

## Роутеры (`routers/`)

Префикс `/api`. Авторизация: заголовки `X-User-Name`, `X-User-Role`. RBAC — [`dependencies.py`](../../backend/routers/dependencies.py).

| Модуль | Эндпоинты | Описание |
|--------|-----------|----------|
| [`search.py`](../../backend/routers/search.py) | `GET /documents`, `POST /search`, `GET /graph`, `GET /statistics` | NL-поиск, VSA + Neo4j merge, L4-синтез, vis-network data |
| [`experiments.py`](../../backend/routers/experiments.py) | `POST /ingest`, `GET /experiments` | Ручной импорт одного эксперimentа, список с пагинацией |
| [`ingestion.py`](../../backend/routers/ingestion.py) | `POST /ingest-corpus`, `GET /ingest-status` | Фоновый импорт корпуса |
| [`analytics.py`](../../backend/routers/analytics.py) | `GET /counterfactuals/{id}`, `GET /reason/{id}` | Контрфакты, LLM-объяснение связей |
| [`gaps.py`](../../backend/routers/gaps.py) | `POST /gaps`, `POST /enrich-gap` | Поиск пробелов, LLM-гипотеза |
| [`audit.py`](../../backend/routers/audit.py) | `GET /audit-logs` | Журнал действий (Administrator) |
| [`admin.py`](../../backend/routers/admin.py) | `POST /upload-db`, `GET /debug-neo4j` | Загрузка pickle, отладка Neo4j |

## Core (`core/`)

| Путь | Назначение |
|------|------------|
| [`vsa.py`](../../backend/core/vsa.py) | Bipolar MAP-VSA: `bind`, `bundle`, `permute`, `similarity` |
| [`models.py`](../../backend/core/models.py) | Pydantic-схемы: Entity, Experiment, Relation |
| [`nlp_schemas.py`](../../backend/core/nlp_schemas.py) | Схемы и tolerant-валидация NLP extraction |
| [`config.py`](../../backend/core/config.py) | VSA dim, LLM (`resolve_llm_settings`), Neo4j, async graph sync flags |
| [`prompts.py`](../../backend/core/prompts.py) | Загрузка YAML из `backend/prompts/` |
| [`graph_sync_events.py`](../../backend/core/graph_sync_events.py) | События outbox для graph sync |

## Repository (`repository/`)

| Путь | Назначение |
|------|------------|
| [`database.py`](../../backend/repository/database.py) | `HSMEVectorDatabase`: codebook, search, counterfactuals, gaps |
| [`neo4j_graph.py`](../../backend/repository/neo4j_graph.py) | Async Neo4j: MERGE, batch, Map ID, kill switch |
| [`ingestion_outbox.py`](../../backend/repository/ingestion_outbox.py) | SQLite transactional outbox для graph sync |
| [`replay_outbox.py`](../../backend/repository/replay_outbox.py) | Replay / reclaim dead-letter из outbox |
| [`seeding.py`](../../backend/repository/seeding.py) | Демо-данные при первом запуске |

## Services (`services/`)

| Путь | Назначение |
|------|------------|
| [`ingestion.py`](../../backend/services/ingestion.py) | Pipeline: документ → эксперименты → VSA + Neo4j dual-write |
| [`document_parser.py`](../../backend/services/document_parser.py) | PDF/DOCX, чанкинг, метаданные |
| [`nlp_extractor.py`](../../backend/services/nlp_extractor.py) | LLM: извлечение сущностей и связей |
| [`query_parse.py`](../../backend/services/query_parse.py) | L0: LLM parse + regex fallback |
| [`graph_sync.py`](../../backend/services/graph_sync.py) | Relay outbox → Redis Streams |
| [`redis_streams.py`](../../backend/services/redis_streams.py) | Redis Streams client |
| [`yandex_aistudio_client.py`](../../backend/services/yandex_aistudio_client.py) | Yandex AI Studio API client |

## Промпты (`prompts/`)

| Файл | Назначение |
|------|------------|
| [`nlp_extractor.yaml`](../../backend/prompts/nlp_extractor.yaml) | Extraction JSON из чанков документов |
| [`search_parse_query.yaml`](../../backend/prompts/search_parse_query.yaml) | L0 parse NL-запроса |
| [`search_synthesize.yaml`](../../backend/prompts/search_synthesize.yaml) | L4 синтез ответа с цитатами |
| [`gaps_enrich.yaml`](../../backend/prompts/gaps_enrich.yaml) | Гипотеза для gap |
| [`analytics_reason.yaml`](../../backend/prompts/analytics_reason.yaml) | Объяснение причинно-следственных связей |
| [`llm_judge.yaml`](../../backend/prompts/llm_judge.yaml) | LLM-as-judge для eval |

## Evaluation (`evaluation/`)

| Путь | Назначение |
|------|------------|
| [`golden/questions.jsonl`](../../backend/evaluation/golden/questions.jsonl) | 11 эталонных вопросов хакатона |
| [`golden/coverage_matrix.json`](../../backend/evaluation/golden/coverage_matrix.json) | Покрытие корпуса vs вопросы |
| [`golden/README.md`](../../backend/evaluation/golden/README.md) | Схема golden dataset |
| [`runners/run_retrieval_eval.py`](../../backend/evaluation/runners/run_retrieval_eval.py) | L1–L2: P@K, R@K, MRR |
| [`runners/run_e2e_eval.py`](../../backend/evaluation/runners/run_e2e_eval.py) | L0–L4: Success Rate, TTFT/TTFA |
| [`runners/layer_snapshots.py`](../../backend/evaluation/runners/layer_snapshots.py) | JSON-снимки L0…L4 |
| [`judges/rule_judge.py`](../../backend/evaluation/judges/rule_judge.py) | Rule-based judge |
| [`judges/llm_judge.py`](../../backend/evaluation/judges/llm_judge.py) | LLM-as-judge |
| [`metrics.py`](../../backend/evaluation/metrics.py) | Precision, Recall, MRR |
| [`README.md`](../../backend/evaluation/README.md) | Обзор eval-инфраструктуры |

```bash
PYTHONPATH=. uv run python backend/evaluation/runners/run_retrieval_eval.py
PYTHONPATH=. uv run python backend/evaluation/runners/run_e2e_eval.py
PYTHONPATH=. uv run python backend/evaluation/runners/run_e2e_eval.py --no-llm
```

## Пайплайн L0–L4 (код)

| Слой | Модули |
|------|--------|
| L0 | `services/query_parse.py` |
| L1–L2 | `repository/database.py` → `search()`, `routers/search.py` |
| L3 | `database.py`, `routers/analytics.py`, `routers/gaps.py` |
| L4 | `routers/search.py` → `synthesize_vsa_answer()` |
