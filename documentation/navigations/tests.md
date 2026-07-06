# Навигация: `tests/`

Pytest-набор: VSA, API, ingestion, Neo4j, eval, security. Запуск: `PYTHONPATH=. uv run pytest tests/ -v`.

| Файл | Покрытие |
|------|----------|
| [`conftest.py`](../../tests/conftest.py) | Общие фикстуры, env для тестов |
| [`test_vsa.py`](../../tests/test_vsa.py) | Математика VSA (`bind`, `bundle`, similarity) |
| [`test_database.py`](../../tests/test_database.py) | VSA БД: индексация, поиск, gaps |
| [`test_api.py`](../../tests/test_api.py) | HTTP-интеграция FastAPI |
| [`test_nlp.py`](../../tests/test_nlp.py) | NLP extractor (legacy/smoke) |
| [`test_nlp_extractor.py`](../../tests/test_nlp_extractor.py) | Parse/repair LLM JSON |
| [`test_nlp_schemas.py`](../../tests/test_nlp_schemas.py) | Tolerant validation, drop invalid |
| [`test_parser.py`](../../tests/test_parser.py) | Document parser, чанкинг |
| [`test_ingestion.py`](../../tests/test_ingestion.py) | Ingestion pipeline |
| [`test_ingestion_ids.py`](../../tests/test_ingestion_ids.py) | Стабильность experiment id |
| [`test_ingestion_neo4j.py`](../../tests/test_ingestion_neo4j.py) | Dual-write VSA + Neo4j |
| [`test_ingestion_outbox.py`](../../tests/test_ingestion_outbox.py) | Transactional outbox |
| [`test_graph_sync.py`](../../tests/test_graph_sync.py) | Graph sync relay/worker |
| [`test_neo4j_graph.py`](../../tests/test_neo4j_graph.py) | Neo4j repo, kill switch, fallback |
| [`test_corpus_loader.py`](../../tests/test_corpus_loader.py) | Corpus loader CLI |
| [`test_corpus_relabel_loader.py`](../../tests/test_corpus_relabel_loader.py) | Relabel loader |
| [`test_eval.py`](../../tests/test_eval.py) | Eval runners, judges, golden load |
| [`test_query_parse.py`](../../tests/test_query_parse.py) | L0 query parse |
| [`test_llm_config.py`](../../tests/test_llm_config.py) | `resolve_llm_settings` |
| [`test_security.py`](../../tests/test_security.py) | RBAC, sensitive data filtering |
| [`test_yandex_aistudio.py`](../../tests/test_yandex_aistudio.py) | Yandex AI Studio client |

Neo4j без Docker: `USE_NEO4J=false uv run pytest tests/test_neo4j_graph.py -v`
