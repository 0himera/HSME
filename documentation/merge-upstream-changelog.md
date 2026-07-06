# Изменения относительно upstream/main

Документ описывает состояние ветки `features-update-v2` после merge `upstream/main` (upstream: `https://github.com/0himera/HSME.git`, ref `088efa1`).

Дата merge: 2026-07-07.

---

## 1. Файлы с merge conflicts (разрешены вручную)

| Файл | Решение |
|------|---------|
| `backend/core/config.py` | Upstream: strip кавычек и placeholder-фильтрация для ключей. Наше: `YANDEX_BASE_URL`, блок async graph sync (Redis/outbox). **Объединено.** |
| `backend/prompts/nlp_extractor.yaml` | Upstream: chain-of-thought промпт, 6 типов сущностей. Наше: расширенная схема (Publication, contradicts, validated_by, described_in), moderation retry. **Взята наша схема + фраза upstream «рассуждай скрыто, только JSON».** |
| `backend/routers/search.py` | Upstream: inline `parse_query_to_entities` (~110 строк). Наше: import из `query_parse.py`, graph enrichment status, sync lag hint. **Оставлен наш роутер; inline-функция удалена.** |
| `backend/services/ingestion.py` | Upstream: `auto_save=False`, skip уже проиндексированных файлов, сортировка «Статьи → Обзоры». Наше: graph sync outbox, `skip_files`, chunk outcomes, relabel sort «Обзоры → Статьи». **Объединено.** |
| `backend/services/nlp_extractor.py` | Upstream: default YandexGPT 5.1, `reasoning_content`. Наше: NLP schemas, validation, moderation retry, regex enrich. **Объединено: 5.1 + reasoning_content + наша логика.** |
| `docker-compose.yml` | Upstream: `backend`, `frontend`. Наше: `redis`, `neo4j-worker`. **Объединены все сервисы.** |
| `pyproject.toml` | Upstream: `python-multipart`. Наше: `redis`. **Обе зависимости.** |
| `tests/test_corpus_loader.py` | Upstream: упрощённый mock httpx stream. **Взято upstream mock + patch `os.path.exists` для dry-run тестов.** |

Дополнительно обновлён без конфликта, но в рамках merge-решения:

| Файл | Изменение |
|------|-----------|
| `backend/services/query_parse.py` | Перенесены из upstream: `max_tokens=2500`, fallback на `reasoning_content`. |
| `tests/test_llm_config.py` | Тесты изолированы от `.env` через `patch.dict(os.environ, {}, clear=True)`. |
| `tests/test_corpus_relabel_loader.py` | Обновлены моки под backfill (`insert_experiment_async`, `close`), ожидание `parse_file` ×4 (skip-indexed + ingest). |

---

## 2. Что пришло из upstream/main (auto-merge, без конфликтов)

Merge подтянул ~41 коммит upstream. Ключевые изменения, уже в рабочем дереве:

### Backend
- Admin API (`backend/routers/admin.py`) — загрузка состояния БД, debug Neo4j
- Увеличенные Neo4j timeouts (10s connect / 60s query)
- Background DB writes (`auto_save=False`, `save_to_disk(..., run_in_background=True)`)
- JSONL audit logging
- Gap analysis: weak / foreign_only / domestic_only / missing
- Search router: улучшенное ранжирование, gap summary в RAG
- YandexGPT 5.1 как default model
- `python-multipart` для upload endpoints
- `tests/conftest.py` — reset DB fixture

### Frontend
- Docker: `frontend/Dockerfile`, `frontend/nginx.conf`
- i18n: `frontend/lib/i18n.ts`, `LangProvider.tsx`
- API client: `frontend/lib/api.ts`, `types.ts`, `mock.ts`
- Mobile-responsive layout (bottom nav, скрытие элементов)
- Graph physics fix (отключение после стабилизации)

### Infra
- `Dockerfile`, `backend/Dockerfile`, `.dockerignore`
- `docker-compose.yml`: сервисы `backend` (port 8000), `frontend` (port 3001)
- `HSME_OVERVIEW.md`, обновления `TECH_SPEC.md`, `INGESTION_LOADER.md`

---

## 3. Что осталось уникальным для features-update-v2 (Stage 3)

Относительно `upstream/main` в ветке сохранены/добавлены следующие изменения (`git diff upstream/main --name-status`):

### Новые файлы (A)

| Путь | Назначение |
|------|------------|
| `Dockerfile.worker` | Docker-образ Neo4j worker |
| `backend/core/graph_sync_events.py` | Схема событий outbox |
| `backend/core/nlp_schemas.py` | Pydantic-валидация NLP extraction |
| `backend/repository/corpus_relabel_loader.py` | Relabel pipeline с YandexGPT |
| `backend/repository/ingestion_outbox.py` | SQLite outbox для graph sync |
| `backend/repository/replay_outbox.py` | Replay failed outbox events |
| `backend/services/graph_sync.py` | Enqueue experiment upserts |
| `backend/services/query_parse.py` | Shared L0 query parsing (API + eval) |
| `backend/services/redis_streams.py` | Redis Streams producer/consumer |
| `backend/services/yandex_aistudio_client.py` | Yandex AI Studio client |
| `backend/workers/neo4j_consumer.py` | Background Neo4j sync worker |
| `tests/test_graph_sync.py` | Graph sync unit tests |
| `tests/test_ingestion_outbox.py` | Outbox tests |
| `tests/test_ingestion_ids.py` | Stable experiment ID tests |
| `tests/test_corpus_relabel_loader.py` | Relabel loader tests |
| `tests/test_nlp_extractor.py` | NLP extractor tests |
| `tests/test_nlp_schemas.py` | Schema validation tests |
| `tests/test_query_parse.py` | Query parse tests |
| `tests/test_yandex_aistudio.py` | Yandex client tests |

### Изменённые файлы (M)

| Путь | Суть изменений |
|------|----------------|
| `.env.example`, `.env.template` | Redis, outbox, async graph sync vars |
| `.gitignore` | Outbox DB, reports, logs |
| `INGESTION_LOADER.md` | Stage 3 ingestion docs |
| `backend/app.py` | Worker lifecycle hooks |
| `backend/core/config.py` | Async graph sync config, `YANDEX_BASE_URL` |
| `backend/evaluation/runners/query_parse.py` | Shared query_parse import |
| `backend/evaluation/runners/run_e2e_eval.py` | Eval harness updates |
| `backend/prompts/nlp_extractor.yaml` | Расширенная entity/relation schema |
| `backend/repository/corpus_loader.py` | Loader improvements |
| `backend/repository/migration.py` | Neo4j backfill |
| `backend/repository/neo4j_graph.py` | Dual-write + graph context |
| `backend/routers/ingestion.py` | Ingestion API updates |
| `backend/routers/search.py` | Graph sync lag hint, enrichment status |
| `backend/services/document_parser.py` | `slugify_filename`, sort order |
| `backend/services/ingestion.py` | Outbox enqueue, chunk outcomes, skip_files |
| `backend/services/nlp_extractor.py` | Schema validation, moderation retry |
| `docker-compose.yml` | `redis`, `neo4j-worker` (+ upstream backend/frontend) |
| `pyproject.toml` | `redis`, `python-multipart` |
| `tests/test_corpus_loader.py` | Mock fixes |
| `tests/test_eval.py` | Eval tests |
| `tests/test_ingestion_neo4j.py` | Neo4j ingestion tests |
| `tests/test_llm_config.py` | Env isolation in tests |
| `tests/test_security.py` | Security test updates |
| `uv.lock` | Lockfile refresh |

### Артефакты (не для коммита)

Следующие файлы есть в diff, но являются локальными артефактами запуска:

- `relabel*.log`
- `ingestion_reports/*/summary.json`

---

## 4. Ключевые архитектурные решения при merge

### Async Graph Sync (наше)
```
IngestionPipeline → ingestion_outbox (SQLite) → Redis Streams → neo4j-worker → Neo4j
```
Конфиг: `USE_ASYNC_GRAPH_SYNC`, `REDIS_URL`, `OUTBOX_DB_PATH` и др. в `config.py`.

### Ingestion persistence (upstream + наше)
- `insert_experiment(..., auto_save=False)` — batch save после файла (upstream)
- Graph sync enqueue или direct Neo4j write с semaphore (наше)
- Skip fully indexed files перед ingest (upstream)
- `skip_files` для resume relabel (наше)

### LLM defaults (merged)
- Default model: **YandexGPT 5.1** (upstream)
- `reasoning_content` fallback для пустого `content` (upstream → `nlp_extractor.py`, `query_parse.py`)
- Расширенный промпт и Pydantic schemas (наше)

### Search (merged)
- Парсинг запроса: `backend/services/query_parse.py` (наше), не inline в router
- Graph enrichment status + sync lag hint в `/api/search` (наше)
- Gap analysis в synthesize (upstream, auto-merged)

---

## 5. Docker Compose — итоговый stack

| Сервис | Источник | Порт |
|--------|----------|------|
| `neo4j` | общий | 7474, 7687 |
| `redis` | features-update-v2 | 6379 |
| `neo4j-worker` | features-update-v2 | — |
| `backend` | upstream | 8000 |
| `frontend` | upstream | 3001 |

---

## 6. Тесты после merge

```
158 passed, 1 skipped, 3 failed (локальное окружение)
```

| Падение | Причина |
|---------|---------|
| `test_parser.py` (2) | Нет файлов в `data/Задача 2...` |
| `test_yandex_aistudio.py::test_integration_*` | Live Yandex API / proxy 403 |

Все merge-related тесты (`test_corpus_loader`, `test_corpus_relabel_loader`, `test_llm_config`, `test_graph_sync`, `test_ingestion_outbox`) проходят.

---

## 7. Следующий шаг

Merge conflicts разрешены и зафиксированы двумя коммитами:

1. `Merge upstream/main into features-update-v2` — интеграция upstream + conflict resolution (см. §1–2).
2. `chore: reorganize repo layout and runtime paths` — `.local/`, `legacy/`, `logs/relabel/`, `documentation/`.
