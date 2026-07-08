# AGENTS.md — навигация по проекту HSME

> **HyperGraph Research Memory Engine** — система R&D-знаний для горно-металлургической отрасли (кейс хакатона «Научный клубок», задача 2).

Этот файл предназначен для AI-агентов и разработчиков: быстрый вход в кодовую базу без долгого обхода репозитория.

**Актуальность:** 2026-07-04 · Stage 1 (Neo4j) и Stage 2 (Eval) — `done`. Подробности этапов — [stages.md](./stages.md).

---

## Быстрый старт

```bash
# Python 3.12 через uv
uv sync
mkdir -p .local logs/relabel
cp .env.example .env   # заполнить LLM-креды (см. ниже)

# Neo4j (опционально; USE_NEO4J=true по умолчанию)
docker compose up -d neo4j

# Async graph sync (Stage 3, опционально): Redis + Neo4j worker
# mkdir -p .local/outbox && export OUTBOX_DB_PATH=.local/outbox/graph_sync_outbox.db
# docker compose up -d redis neo4j neo4j-worker

# Тесты
PYTHONPATH=. uv run pytest tests/ -v

# Frontend (Next.js static export → frontend/out/)
cd frontend && bun install && bun run build && cd ..

# API + UI на одном порту
uv run uvicorn backend.app:app --reload --port 8000
```

- UI: [http://localhost:8000](http://localhost:8000) (статика из `frontend/out/`, fallback — `frontend/`)
- OpenAPI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Neo4j Browser: [http://localhost:7474](http://localhost:7474) (`neo4j` / `hsme_password`)

**LLM-провайдеры** (приоритет: CLI → env → `.env`): OpenRouter, Yandex Cloud, Gemini fallback. См. [README.md §2](../README.md) и [INGESTION_LOADER.md](../INGESTION_LOADER.md).

**Python только через uv** — не `python script.py` / `pip install` вне venv. См. [stages.md §Правила](./stages.md).

---

## Документация

### Корень `documentation/`

| Файл | Содержание |
|------|------------|
| `AGENTS.md` | Этот файл — карта проекта |
| [HACKATHON_TASK_2_SCIENTIFIC_TANGLE.md](./HACKATHON_TASK_2_SCIENTIFIC_TANGLE.md) | Полное ТЗ кейса «Научный клубок» |
| [stages.md](./stages.md) | Журнал этапов реализации |
| [merge-upstream-changelog.md](./merge-upstream-changelog.md) | Changelog merge upstream |

### Пайплайны (`pipelines/`)

Пошаговая документация ключевых потоков — [pipelines/README.md](./pipelines/README.md):

| Файл | Содержание |
|------|------------|
| [retrieval-to-answer.md](./pipelines/retrieval-to-answer.md) | NL-запрос → VSA retrieval → LLM-синтез ответа (L0–L4) |
| [ingestion-pipeline.md](./pipelines/ingestion-pipeline.md) | Корпус → NLP → VSA + Neo4j |
| [llm-call-sites.md](./pipelines/llm-call-sites.md) | Все LLM-вызовы: код, промпты, примеры ответов |
| [hypergraph-memory-literature.md](./pipelines/hypergraph-memory-literature.md) | Анализ иерархической и гиперграфовой памяти (HGMem, HiGMem) |
| [memory-architecture-gaps.md](./pipelines/memory-architecture-gaps.md) | Gap-анализ систем памяти и дорожная карта оптимизаций |

### Навигация по репозиторию

Полные карты папок — [navigations/README.md](./navigations/README.md):

| Папка | Навигация |
|-------|-----------|
| `backend/` | [navigations/backend.md](./navigations/backend.md) |
| `frontend/` | [navigations/frontend.md](./navigations/frontend.md) |
| `tests/` | [navigations/tests.md](./navigations/tests.md) |
| `scripts/` | [navigations/scripts.md](./navigations/scripts.md) |
| `ingestion_reports/` | [navigations/ingestion_reports.md](./navigations/ingestion_reports.md) |
| `documentation/` | [navigations/documentation.md](./navigations/documentation.md) |
| `test_data/` | [navigations/test_data.md](./navigations/test_data.md) |
| Корень репозитория | [navigations/root.md](./navigations/root.md) |

---

## Архитектура (слои)

```
frontend/              → Next.js 16 + React 19, Tailwind 4, static export (out/)
backend/routers/       → FastAPI эндпоинты, авторизация по ролям
backend/services/      → NLP, парсинг документов, ingestion pipeline
backend/core/          → Pydantic-модели, VSA-ядро, config, prompts loader
backend/repository/    → VSA БД (pickle) + Neo4j dual-write + corpus loader
backend/prompts/       → YAML-промпты для LLM (parse, synthesize, judge, …)
backend/evaluation/    → Golden dataset, eval-раннеры L0–L4, judges, метрики
tests/                 → pytest: VSA, API, Neo4j, eval, ingestion, security
docker-compose.yml     → Neo4j 5 Community
```

**Ключевая идея:** эксперимент кодируется как **гиперребро** (единый VSA-вектор), а не набор разрозненных триплетов GraphRAG. Neo4j дополняет VSA для multi-hop обхода связей (dual storage, Map ID — векторы не дублируются в граф).

### Пайплайн ответа (L0–L4)

| Слой | Что происходит | Модули |
|------|----------------|--------|
| **L0** | NL-запрос → сущности (LLM + regex fallback) | `services/query_parse.py` → `parse_query_to_entities()` |
| **L1** | VSA retrieval по сходству | `database.py` → `search()` |
| **L2** | Top-K + фильтры (география, год) | `search.py`, eval snapshots |
| **L3** | Контрфакты, gaps, reason | `database.py`, `analytics.py`, `gaps.py` |
| **L4** | LLM-синтез ответа с цитатами | `search.py` → `synthesize_vsa_answer()` |

Гибридный `/api/search` и `/api/graph` мержат VSA-hits с Neo4j paths при `USE_NEO4J=true`. Детали API и модулей — [navigations/backend.md](./navigations/backend.md).

---

## Онтология (соответствие ТЗ)

**Типы сущностей:** Material, Process, Equipment, Property, Experiment, Publication, Expert, Facility

**Отношения:** `uses_material`, `operates_at_condition`, `produces_output`, `described_in`, `validated_by`, `contradicts`

---

## Статус vs ТЗ

| Область | Статус |
|---------|--------|
| VSA hyperedge + NL-поиск | ✅ |
| Neo4j dual-write + hybrid search/graph | ✅ Stage 1 |
| Eval L0–L4, golden dataset | ✅ Stage 2 |
| Next.js UI (NotebookLM-style) | 🔄 в работе |
| Async ingestion (Redis/Outbox) | ✅ Stage 3 (`USE_ASYNC_GRAPH_SYNC`, worker in compose) |
| Cascade inference (cheap→strong LLM) | 📋 backlog |
| RU/EN synonym mapping | ❌ |
| Экспорт PDF/Markdown/JSON-LD, уведомления | ❌ |
| Сравнительный анализ технологий «из коробки» | ❌ |

Подробный gap-анализ: [topics/gap-analysis/GAP_ANALYSIS.md](./topics/gap-analysis/GAP_ANALYSIS.md). План L4 precision: [topics/retrieval/deep_research_precision_l4_solution.md](./topics/retrieval/deep_research_precision_l4_solution.md).

---

## Куда смотреть при типичных задачах

| Задача | Начать с |
|--------|----------|
| API, модули backend | [navigations/backend.md](./navigations/backend.md) |
| UI, компоненты | [navigations/frontend.md](./navigations/frontend.md) |
| Тесты | [navigations/tests.md](./navigations/tests.md) |
| Как получается ответ (retrieval) | [pipelines/retrieval-to-answer.md](./pipelines/retrieval-to-answer.md) |
| Ingestion pipeline | [pipelines/ingestion-pipeline.md](./pipelines/ingestion-pipeline.md) |
| LLM-вызовы | [pipelines/llm-call-sites.md](./pipelines/llm-call-sites.md) |
| Импорт корпуса | [INGESTION_LOADER.md](../INGESTION_LOADER.md), [navigations/backend.md §Repository](./navigations/backend.md) |
| Конфиг, Docker, данные | [navigations/root.md](./navigations/root.md) |
| Тематические docs | [navigations/documentation.md](./navigations/documentation.md) |

---

## Стек

- **Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic, NumPy
- **LLM:** OpenRouter / Yandex Cloud / Gemini (OpenAI-compatible API)
- **Graph DB:** Neo4j 5 Community (async driver, optional kill switch)
- **Frontend:** Next.js 16, React 19, Tailwind CSS 4, vis-network
- **Eval:** pytest, custom runners, rule/LLM judges
- **Tooling:** uv, Docker Compose, bun (frontend)
