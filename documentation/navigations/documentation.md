# Навигация: `documentation/`

Markdown-документация проекта: регламенты, этапы, тематические исследования.

## Корень `documentation/`

| Файл | Описание |
|------|----------|
| [`AGENTS.md`](../AGENTS.md) | Карта проекта для AI-агентов и разработчиков |
| [`HACKATHON_TASK_2_SCIENTIFIC_TANGLE.md`](../HACKATHON_TASK_2_SCIENTIFIC_TANGLE.md) | Полное ТЗ кейса «Научный клубок» |
| [`stages.md`](../stages.md) | Журнал этапов реализации (Stage 1–6, backlog) |
| [`merge-upstream-changelog.md`](../merge-upstream-changelog.md) | Changelog merge upstream |

## `navigations/`

Навигация по папкам репозитория — см. [`README.md`](./README.md).

## `pipelines/` — пайплайны данных

| Файл | Описание |
|------|----------|
| [`README.md`](../pipelines/README.md) | Index: retrieval, ingestion, LLM |
| [`retrieval-to-answer.md`](../pipelines/retrieval-to-answer.md) | NL-запрос → VSA → LLM-синтез (L0–L4) |
| [`ingestion-pipeline.md`](../pipelines/ingestion-pipeline.md) | Корпус → Experiment → VSA + Neo4j |
| [`llm-call-sites.md`](../pipelines/llm-call-sites.md) | Все LLM-вызовы с кодом и примерами |

## `topics/` — тематические материалы

### `topics/architecture/`

| Файл | Описание |
|------|----------|
| [`neo4j_vs_VSA.md`](../topics/architecture/neo4j_vs_VSA.md) | Риски интеграции in-memory VSA и Neo4j |
| [`neo4j_vs_VSA_fix.md`](../topics/architecture/neo4j_vs_VSA_fix.md) | Принятые паттерны: Map ID, Outbox, hybrid query |
| [`problem.md`](../topics/architecture/problem.md) | Гиперграфы + VSA, архитектурное обоснование |
| [`architecture_review_hsme.md`](../topics/architecture/architecture_review_hsme.md) | Архитектурный аудит (2026-07-04) |
| [`topochunker.md`](../topics/architecture/topochunker.md) | TopoChunker overview; выбор ChunkNorris-style chunking |

## `reference/` — дополнительные материалы

| Файл | Описание |
|------|----------|
| [`task.md`](../reference/task.md) | Краткая копия ТЗ хакатона |
| [`HSME_OVERVIEW.md`](../reference/HSME_OVERVIEW.md) | Обзор системы HSME |

### `topics/retrieval/`

| Файл | Описание |
|------|----------|
| [`deep_research_precision_l4_solution.md`](../topics/retrieval/deep_research_precision_l4_solution.md) | Стратегия rerank → evidence pack → L4 |
| [`deep_research_precision_l4_prompt.md`](../topics/retrieval/deep_research_precision_l4_prompt.md) | Промпт deep research по precision |

### `topics/ingestion/`

| Файл | Описание |
|------|----------|
| [`data_ingestion_overview.md`](../topics/ingestion/data_ingestion_overview.md) | Обзор пайплайна загрузки данных |
| [`data_ingestion_overview_summary.md`](../topics/ingestion/data_ingestion_overview_summary.md) | Сжатые рекомендации по проблемам ingestion |
| [`data_ingestion_overview_answer.md`](../topics/ingestion/data_ingestion_overview_answer.md) | Развёрнутые обоснования 80/20-решений |
| [`stage4_relabel_analysis.md`](../topics/ingestion/stage4_relabel_analysis.md) | Отчёт анализа corpus relabel (Stage 4) |

### `topics/gap-analysis/`

| Файл | Описание |
|------|----------|
| [`GAP_ANALYSIS.md`](../topics/gap-analysis/GAP_ANALYSIS.md) | Полный gap-анализ vs ТЗ хакатона |

### `topics/automation/`

| Файл | Описание |
|------|----------|
| [`automation_brief.md`](../topics/automation/automation_brief.md) | Контракт automation brief: входы, dry-run, откат |
