# VSA + Neo4j: принятое архитектурное решение

Краткая фиксация mitigation-паттернов для dual storage HSME. Этот документ описывает принятое публичное решение без привязки к внутренним risk notes.

## §1 Роли систем

- **VSA** — authoritative store для semantic retrieval (in-memory hypervectors).
- **Neo4j** — graph projection для multi-hop enrichment и visualization.
- **Связь** — Map ID (`entity.to_key()`), без дублирования VSA-векторов в Neo4j.

## §2 Async graph sync (Stage 3)

Паттерн: **Transactional Outbox (SQLite) + Redis Streams + Neo4j worker**.

```
VSA insert → outbox enqueue → relay → worker → Neo4j MERGE → ack
```

- Feature flag: `USE_ASYNC_GRAPH_SYNC=false` по умолчанию (sync fallback сохранён).
- Strict mode: `ASYNC_GRAPH_SYNC_REQUIRED=true` → fail-fast на enqueue/relay.
- Recovery: PEL reclaim, stale published requeue, dead-letter replay, VSA→outbox backfill.

## §3 Hybrid query contract

- Search path: **VSA first**, Neo4j **enriches** paginated slice (не intersection двух top-K).
- Paged API signals: `graph_enrichment_status`, `graph_sync_lag_hint`.
- Neo4j outage → VSA results сохраняются; graph context может быть пустым.

## §4 Residual accepted risks

- Нет single-transaction VSA + outbox.
- Eventual consistency между VSA и Neo4j в async mode.
- Orphan recovery требует operator tools (`migration --via-outbox`) при crash между VSA write и enqueue.

## §5 Operator checklist

1. Shared `OUTBOX_DB_PATH` для producer и worker.
2. `/api/ingest-status`: `outbox_pending == 0`, `outbox_published_not_acked == 0` перед hybrid demo.
3. После `--clear-neo4j`: direct или outbox backfill (авто в relabel loader).
4. Prod-like: `ASYNC_GRAPH_SYNC_REQUIRED=true`.
