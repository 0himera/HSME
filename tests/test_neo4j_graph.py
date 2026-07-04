"""Tests for Neo4j graph repository — happy path, kill switch, timeout, N+1."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.models import Entity, Experiment, Relation
from backend.repository.neo4j_graph import Neo4jGraphRepository, _entity_id


def _sample_experiment() -> Experiment:
    return Experiment(
        id="EXP-TEST-01",
        name="Test nickel electrowinning",
        input_entities=[
            Entity(type="Material", value="Nickel electrolyte"),
            Entity(type="Property", value="pH: 2.0"),
        ],
        process_entities=[
            Entity(type="Process", value="Electrowinning"),
            Entity(type="Equipment", value="EW cell"),
        ],
        output_entities=[
            Entity(type="Material", value="Cathode"),
        ],
        relations=[
            Relation(
                source="Electrowinning",
                type="uses_material",
                target="Nickel electrolyte",
            ),
            Relation(
                source="Electrowinning",
                type="produces_output",
                target="Cathode",
            ),
        ],
        evidence=["doc-001.pdf"],
        confidence=0.9,
        year=2024,
        geography="RU",
        source_type="Article",
    )


def test_map_id_pattern_no_vectors_in_params():
    """Map ID: entity keys match VSA codebook; no vector fields in insert plan."""
    repo = Neo4jGraphRepository(enabled=True, dry_run=True)
    exp = _sample_experiment()
    plan = repo.describe_insert_plan(exp)

    assert plan["entity_count"] == 5
    assert plan["semantic_relation_count"] == 2
    assert plan["evidence_count"] == 1

    params = repo._build_insert_params(exp)
    for entity in params["entities"]:
        assert "vector" not in entity
        assert entity["entity_id"] == _entity_id(
            Entity(type=entity["label"], value=entity["name"])
        )


def test_no_credentials_kill_switch():
    """Kill switch: empty password disables Neo4j without raising."""
    repo = Neo4jGraphRepository(enabled=True, password="", dry_run=False)
    assert repo.is_configured is False

    async def _run():
        return await repo.insert_experiment_async(_sample_experiment())

    assert asyncio.run(_run()) is False


def test_kill_switch_disabled_flag():
    repo = Neo4jGraphRepository(enabled=False, dry_run=False)
    assert repo.is_configured is False

    async def _run():
        return await repo.insert_experiment_async(_sample_experiment())

    assert asyncio.run(_run()) is False


def test_dry_run_insert_logs_plan():
    repo = Neo4jGraphRepository(enabled=True, dry_run=True)

    async def _run():
        return await repo.insert_experiment_async(_sample_experiment())

    assert asyncio.run(_run()) is True


@pytest.mark.asyncio
async def test_timeout_handling():
    """Connection timeout to bad port must not crash caller."""
    repo = Neo4jGraphRepository(
        enabled=True,
        uri="bolt://127.0.0.1:59999",
        user="neo4j",
        password="test",
        connection_timeout=1.0,
        dry_run=False,
    )
    ok = await repo.insert_experiment_async(_sample_experiment())
    assert ok is False
    await repo.close()


@pytest.mark.asyncio
async def test_n_plus_one_protection_single_batch_query():
    """Batch subgraph must issue exactly one Cypher run for all experiment IDs."""
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.__aiter__ = lambda self: self
    mock_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

    run_mock = AsyncMock(return_value=mock_result)
    mock_session.run = run_mock
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    repo._driver = mock_driver

    ids = ["EXP-A", "EXP-B", "EXP-C"]
    result = await repo.get_subgraph_for_experiments(ids)

    assert run_mock.call_count == 1
    call_kwargs = run_mock.call_args
    assert call_kwargs[1]["ids"] == ids
    assert result["nodes"] == []
    assert result["edges"] == []


@pytest.mark.asyncio
async def test_insert_happy_path_mocked():
    """Happy path: transaction write invoked once with experiment payload."""
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)
    exp = _sample_experiment()

    mock_session = AsyncMock()
    mock_session.execute_write = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    repo._driver = mock_driver

    ok = await repo.insert_experiment_async(exp)
    assert ok is True
    mock_session.execute_write.assert_called_once()
    args = mock_session.execute_write.call_args[0]
    assert args[1] == exp


@pytest.mark.asyncio
async def test_expand_graph_context_batch():
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.__aiter__ = lambda self: self
    mock_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

    run_mock = AsyncMock(return_value=mock_result)
    mock_session.run = run_mock
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    repo._driver = mock_driver

    ids = ["EXP-1", "EXP-2"]
    ctx = await repo.expand_graph_context(ids)

    assert run_mock.call_count == 1
    assert run_mock.call_args[1]["ids"] == ids
    assert ctx["experts"] == []
    assert ctx["publications"] == []


def test_build_insert_params_bad_payload_or_dangling_relations():
    """Bad payload: dangling relations are skipped without breaking insert plan."""
    repo = Neo4jGraphRepository(enabled=True, dry_run=True)
    exp = Experiment(
        id="EXP-BAD-01",
        name="Orphan relations test",
        input_entities=[Entity(type="Material", value="Nickel")],
        process_entities=[],
        output_entities=[],
        relations=[
            Relation(source="Missing", type="uses_material", target="AlsoMissing"),
        ],
        evidence=[],
    )
    params = repo._build_insert_params(exp)
    assert params["semantic_rels"] == []
    assert len(params["entities"]) == 1

    async def _run():
        return await repo.insert_experiment_async(exp)

    assert asyncio.run(_run()) is True


@pytest.mark.asyncio
async def test_ensure_indexes_failure_continues():
    """Index bootstrap failure must not crash startup path."""
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)
    mock_session = AsyncMock()

    async def run_side_effect(query, **kwargs):
        if "awaitIndexes" in str(query):
            raise TimeoutError("index bootstrap timed out")
        return AsyncMock()

    mock_session.run = AsyncMock(side_effect=run_side_effect)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    repo._driver = mock_driver

    ok = await repo.ensure_indexes()
    assert ok is False


@pytest.mark.asyncio
async def test_get_subgraph_failure_returns_empty_fallback():
    """Read-path failure returns empty graph payload for VSA fallback."""
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(side_effect=ConnectionError("neo4j down"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    repo._driver = mock_driver

    result = await repo.get_subgraph_for_experiments(["EXP-1"])
    assert result["nodes"] == []
    assert result["edges"] == []
    assert "neo4j_latency_ms" in result


@pytest.mark.asyncio
async def test_expand_graph_context_failure_returns_empty():
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(side_effect=ConnectionError("neo4j down"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    repo._driver = mock_driver

    ctx = await repo.expand_graph_context(["EXP-1"])
    assert ctx["paths"] == []
    assert ctx["experts"] == []
    assert ctx["publications"] == []
    assert ctx["contradictions"] == []


@pytest.mark.asyncio
async def test_expand_graph_context_parses_multi_hop_path():
    """Multi-hop happy path: Material -> Process -> Equipment path is parsed."""
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)

    def make_node(name: str, label: str):
        node = MagicMock()
        node.get = lambda key, default=None, n=name: n if key in ("name", "entity_id") else default
        node.labels = [label]
        return node

    def make_rel(rel_type: str):
        rel = MagicMock()
        rel.type = rel_type
        return rel

    path = MagicMock()
    path.nodes = [
        make_node("Nickel electrolyte", "Material"),
        make_node("Electrowinning", "Process"),
        make_node("EW cell", "Equipment"),
    ]
    path.relationships = [make_rel("USES_MATERIAL"), make_rel("OPERATES_AT")]

    record = {
        "exp_id": "EXP-TEST-01",
        "paths": [path],
        "contradictions": [],
    }

    async def record_iter():
        yield record

    mock_result = MagicMock()
    mock_result.__aiter__ = lambda self: record_iter()

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    repo._driver = mock_driver

    ctx = await repo.expand_graph_context(["EXP-TEST-01"])
    assert len(ctx["paths"]) == 1
    assert ctx["paths"][0]["experiment_id"] == "EXP-TEST-01"
    assert [n["type"] for n in ctx["paths"][0]["nodes"]] == [
        "Material",
        "Process",
        "Equipment",
    ]
    assert ctx["paths"][0]["relations"] == ["USES_MATERIAL", "OPERATES_AT"]
