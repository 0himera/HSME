# Documentation (public)

Тонкий публичный слой: обзор системы и ключевые пайплайны.  
Рабочие журналы этапов, карты для агентов, LLM call-sites и ops-отчёты живут локально (см. `.gitignore`) и не публикуются в репозитории.

## Обзор

| Файл | Содержание |
|------|------------|
| [reference/HSME_OVERVIEW.md](./reference/HSME_OVERVIEW.md) | Продуктовый и архитектурный обзор HSME |
| [topics/architecture/problem.md](./topics/architecture/problem.md) | Почему гиперграф + VSA, а не GraphRAG / embeddings |
| [HACKATHON_TASK_2_SCIENTIFIC_TANGLE.md](./HACKATHON_TASK_2_SCIENTIFIC_TANGLE.md) | ТЗ кейса «Научный клубок» |
| [reference/task.md](./reference/task.md) | Краткая копия ТЗ |

## Пайплайны

| Файл | Содержание |
|------|------------|
| [pipelines/retrieval-to-answer.md](./pipelines/retrieval-to-answer.md) | NL-запрос → VSA retrieval → LLM-синтез (L0–L4) |
| [pipelines/ingestion-pipeline.md](./pipelines/ingestion-pipeline.md) | Корпус → NLP → Experiment → VSA + Neo4j |
| [pipelines/README.md](./pipelines/README.md) | Index пайплайнов |

## Архитектурные заметки

| Файл | Содержание |
|------|------------|
| [topics/architecture/neo4j_vs_VSA_fix.md](./topics/architecture/neo4j_vs_VSA_fix.md) | Dual storage: Map ID, Outbox, hybrid query |
| [topics/architecture/topochunker.md](./topics/architecture/topochunker.md) | ADR: ChunkNorris-style chunking vs TopoChunker |

## Локально (не в git)

После clone у вас могут остаться (или появиться) файлы вроде `AGENTS.md`, `stages.md`, `navigations/` — они игнорируются VCS и нужны команде/агентам, не внешним читателям.
