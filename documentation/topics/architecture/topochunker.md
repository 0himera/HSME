# TopoChunker — обзор и решение для HSME

**Дата:** 2026-07-17  
**Связано:** [stages.md — Stage 4.1](../../stages.md), [ChunkNorris paper](https://ar5iv.labs.arxiv.org/html/2602.00010), [TopoChunker paper](https://ar5iv.labs.arxiv.org/html/2603.18409)

---

## Что такое TopoChunker

[TopoChunker](https://ar5iv.labs.arxiv.org/html/2603.18409) — agentic framework для topology-aware chunking в RAG:

1. **Inspector Agent** — маршрутизация документа по сложности (rule / semantic LLM / VLM).
2. **Structured Intermediate Representation (SIR)** — дерево разделов с lineage parent→child.
3. **Refiner Agent** — capacity audit, semantic slicing, disambiguation местоимений, генерация thematic titles.

Цель статьи — качество retrieval/generation на GutenQA и GovReport, с контролем token overhead относительно LumberChunker.

---

## Почему рассматривали

Для HSME актуален тот же класс проблем, что у TopoChunker:

- fixed-size чанки (~1800) рвут смысловые разделы;
- PDF режется по страницам без иерархии заголовков;
- «semantic islands» ухудшают NLP extraction (entities/relations).

Идеи, которые полезны концептуально:

- сохранять топологию разделов (parent headers / lineage);
- не дробить атомарные блоки без необходимости;
- адаптировать стоимость обработки к сложности документа.

---

## Почему HSME выбрал ChunkNorris-style, а не TopoChunker

Главный cost-driver ingest в HSME — **LLM extraction на каждый чанк** (`NLPExtractor`), а не embedding retrieval.

| Подход | LLM на chunking | Подходит HSME? |
|--------|-----------------|----------------|
| **TopoChunker (full)** | Да (Inspector + Refiner + иногда VLM) | Нет — добавляет токены *до* extraction |
| **TopoChunker Path 1 only** | Нет (rules) | Частично — близко к нужной эвристике |
| **ChunkNorris** | Нет (PyMuPDF + heuristics) | **Да** — скорость, CPU-only, section headers |

Выбран **ChunkNorris-style** deterministic chunking:

- section-aware границы по заголовкам;
- soft/hard limits вместо слепого fixed-size;
- parent headers в контексте чанка;
- oversized tables → split с **повтором заголовков столбцов**;
- code-like fragments → skip до LLM;
- versioned IDs: `EXP-{code}-{cn_v1}-{index}`.

Реализация: [`backend/services/document_parser.py`](../../../backend/services/document_parser.py) (`CHUNK_VERSION=cn_v1`).

---

## Что взяли из TopoChunker без агентов

- идея **топологического контекста** (section path / parent headers);
- идея **атомарности** таблиц (не рвать без нужды; при split — сохранять header).

Не берём: dual-agent ReAct, VLM layout path, LLM semantic slicer, thematic title generation.

---

## Инварианты для HSME

1. Chunking **не** вызывает LLM/VLM.
2. Смена границ чанков = новая `chunk_version` (новая волна ingest).
3. Unsupported formats (PPTX/DOC/XLS) вне scope.
4. Rollback: прежние `EXP-*` без `cn_v1` остаются в БД до явного re-ingest / wipe.

Подробный stage-план и чек-лист Composer: [stages.md § Stage 4.1](../../stages.md).
