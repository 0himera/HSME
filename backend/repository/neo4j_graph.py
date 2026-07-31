"""Neo4j graph repository — dual storage companion to VSA (Map ID pattern)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from neo4j import AsyncGraphDatabase, Query

from backend.core.config import (
    NEO4J_CONNECTION_TIMEOUT,
    NEO4J_DATABASE,
    NEO4J_DRY_RUN,
    NEO4J_EXPAND_LIMIT_PER_EXP,
    NEO4J_INDEX_AWAIT_TIMEOUT,
    NEO4J_INTERACTIVE_TIMEOUT,
    NEO4J_PASSWORD,
    NEO4J_QUERY_TIMEOUT,
    NEO4J_URI,
    NEO4J_USER,
    USE_NEO4J,
)
from backend.core.models import Entity, Experiment

logger = logging.getLogger(__name__)

ENTITY_LABELS = (
    "Material",
    "Process",
    "Equipment",
    "Property",
    "Publication",
    "Expert",
    "Facility",
)

RELATION_TYPE_MAP: Dict[str, str] = {
    "uses_material": "USES_MATERIAL",
    "operates_at_condition": "OPERATES_AT_CONDITION",
    "produces_output": "PRODUCES_OUTPUT",
    "described_in": "DESCRIBED_IN",
    "validated_by": "VALIDATED_BY",
    "contradicts": "CONTRADICTS",
    "located_at": "LOCATED_AT",
}

HYPEREDGE_RELATIONS = {
    "input": "HAS_INPUT",
    "process": "HAS_PROCESS",
    "output": "HAS_OUTPUT",
}


def _entity_id(entity: Entity) -> str:
    """Map ID: same key as VSA codebook, no vectors stored in Neo4j."""
    return entity.to_key()


def _normalize_rel_type(rel_type: str) -> str:
    mapped = RELATION_TYPE_MAP.get(rel_type.lower(), rel_type.upper())
    return mapped.replace(" ", "_")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Neo4jGraphRepository:
    """Async Neo4j layer with kill switch, index bootstrap, and batch queries."""

    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str = NEO4J_PASSWORD,
        database: str = NEO4J_DATABASE,
        enabled: bool = USE_NEO4J,
        dry_run: bool = NEO4J_DRY_RUN,
        connection_timeout: float = NEO4J_CONNECTION_TIMEOUT,
        query_timeout: float = NEO4J_QUERY_TIMEOUT,
        interactive_timeout: float = NEO4J_INTERACTIVE_TIMEOUT,
        expand_limit_per_exp: int = NEO4J_EXPAND_LIMIT_PER_EXP,
        index_await_timeout: int = NEO4J_INDEX_AWAIT_TIMEOUT,
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.enabled = enabled
        self.dry_run = dry_run
        self.connection_timeout = connection_timeout
        self.query_timeout = query_timeout
        self.interactive_timeout = interactive_timeout
        self.expand_limit_per_exp = max(1, expand_limit_per_exp)
        self.index_await_timeout = index_await_timeout
        self._driver = None
        self._indexes_ready = False

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.uri and self.user and self.password)

    def _get_driver(self):
        if not self.is_configured:
            return None
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                connection_timeout=self.connection_timeout,
            )
        return self._driver

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def verify_connectivity(self) -> bool:
        driver = self._get_driver()
        if driver is None:
            return False
        try:
            await driver.verify_connectivity()
            return True
        except Exception as exc:
            logger.warning("Neo4j connectivity check failed: %s", exc.__class__.__name__)
            return False

    async def ensure_indexes(self) -> bool:
        """Create constraints/indexes and wait until POPULATING completes."""
        if not self.is_configured:
            logger.info("Neo4j disabled or missing credentials — skipping index bootstrap")
            return False
        if self.dry_run:
            logger.info("Neo4j dry-run: would ensure indexes/constraints")
            return True

        driver = self._get_driver()
        if driver is None:
            return False

        ddl_statements = [
            "CREATE CONSTRAINT experiment_entity_id IF NOT EXISTS "
            "FOR (e:Experiment) REQUIRE e.entity_id IS UNIQUE",
        ]
        for label in ENTITY_LABELS:
            ddl_statements.append(
                f"CREATE CONSTRAINT {label.lower()}_entity_id IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.entity_id IS UNIQUE"
            )
            ddl_statements.append(
                f"CREATE INDEX {label.lower()}_name IF NOT EXISTS "
                f"FOR (n:{label}) ON (n.name)"
            )

        try:
            async with driver.session(database=self.database) as session:
                for stmt in ddl_statements:
                    await session.run(stmt)
                await session.run(
                    "CALL db.awaitIndexes($timeout)",
                    timeout=self.index_await_timeout,
                )
            self._indexes_ready = True
            logger.info("Neo4j indexes/constraints ready")
            return True
        except Exception as exc:
            logger.warning(
                "Neo4j index bootstrap timed out or failed (continuing): %s",
                exc.__class__.__name__,
            )
            return False

    async def clear_all_async(self) -> dict[str, Any]:
        """Delete all nodes and relationships from the configured database."""
        result: dict[str, Any] = {
            "skipped": False,
            "dry_run": False,
            "nodes_deleted": 0,
            "relationships_deleted": 0,
        }
        if not self.is_configured:
            logger.warning("Neo4j clear skipped: repository not configured")
            result["skipped"] = True
            return result
        if self.dry_run:
            logger.info("Neo4j dry-run: would clear all nodes and relationships")
            result["dry_run"] = True
            return result

        driver = self._get_driver()
        if driver is None:
            result["skipped"] = True
            return result

        try:
            async with driver.session(database=self.database) as session:
                count_result = await session.run(
                    "MATCH (n) OPTIONAL MATCH (n)-[r]-() "
                    "RETURN count(DISTINCT n) AS nodes, count(r) AS rels"
                )
                record = await count_result.single()
                nodes_before = int(record["nodes"]) if record else 0
                rels_before = int(record["rels"]) if record else 0
                await session.run("MATCH (n) DETACH DELETE n")

            result["nodes_deleted"] = nodes_before
            result["relationships_deleted"] = rels_before
            logger.warning(
                "Neo4j graph cleared: nodes=%d relationships=%d",
                nodes_before,
                rels_before,
            )
            return result
        except Exception as exc:
            logger.error("Neo4j clear failed: %s", exc.__class__.__name__, exc_info=True)
            raise

    def _build_insert_params(self, experiment: Experiment) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "updated_at": _utc_now_iso(),
            "entities": [],
            "hyperedges": [],
            "semantic_rels": [],
            "evidence_files": experiment.evidence or [],
        }

        seen_entities: Set[str] = set()

        def add_entity(entity: Entity, role: str) -> None:
            eid = _entity_id(entity)
            if eid in seen_entities:
                params["hyperedges"].append(
                    {"exp_id": experiment.id, "entity_id": eid, "rel": HYPEREDGE_RELATIONS[role]}
                )
                return
            seen_entities.add(eid)
            params["entities"].append(
                {"entity_id": eid, "label": entity.type, "name": entity.value}
            )
            params["hyperedges"].append(
                {"exp_id": experiment.id, "entity_id": eid, "rel": HYPEREDGE_RELATIONS[role]}
            )

        for ent in experiment.input_entities:
            add_entity(ent, "input")
        for ent in experiment.process_entities:
            add_entity(ent, "process")
        for ent in experiment.output_entities:
            add_entity(ent, "output")

        entity_by_value: Dict[str, Entity] = {}
        for ent in experiment.get_all_entities():
            entity_by_value[ent.value.strip().lower()] = ent

        for rel in getattr(experiment, "relations", []) or []:
            source_ent = entity_by_value.get(rel.source.strip().lower())
            target_ent = entity_by_value.get(rel.target.strip().lower())
            if not source_ent or not target_ent:
                continue
            params["semantic_rels"].append(
                {
                    "source_id": _entity_id(source_ent),
                    "target_id": _entity_id(target_ent),
                    "rel_type": _normalize_rel_type(rel.type),
                    "source_label": source_ent.type,
                    "target_label": target_ent.type,
                    "source_name": source_ent.value,
                    "target_name": target_ent.value,
                }
            )

        return params

    async def insert_experiment_async(self, experiment: Experiment) -> bool:
        """Dual-write target: MERGE experiment node, entities, hyperedges, semantic relations."""
        if not self.is_configured:
            logger.debug("Neo4j kill switch active — skip insert for %s", experiment.id)
            return False

        start = time.perf_counter()
        params = self._build_insert_params(experiment)

        if self.dry_run:
            logger.info(
                "Neo4j dry-run insert %s: entities=%d relations=%d evidence=%d",
                experiment.id,
                len(params["entities"]),
                len(params["semantic_rels"]),
                len(params["evidence_files"]),
            )
            return True

        driver = self._get_driver()
        if driver is None:
            return False

        try:
            async with driver.session(database=self.database) as session:
                await session.execute_write(
                    self._write_experiment_tx,
                    experiment,
                    params,
                )
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Neo4j ingest ok experiment=%s latency_ms=%.1f entities=%d",
                experiment.id,
                elapsed_ms,
                len(params["entities"]),
            )
            return True
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "Neo4j ingest failed experiment=%s latency_ms=%.1f error=%s details=%s",
                experiment.id,
                elapsed_ms,
                exc.__class__.__name__,
                str(exc),
                exc_info=True
            )
            return False

    async def insert_ontology_entities_async(self, entities: List[Entity]) -> int:
        """MERGE ontological landmark nodes in the graph (no experiment hyperedges)."""
        if not self.is_configured:
            logger.debug("Neo4j kill switch active — skip ontology insert")
            return 0

        if self.dry_run:
            logger.info("Neo4j dry-run ontology insert entities=%d", len(entities))
            return len(entities)

        driver = self._get_driver()
        if driver is None:
            return 0

        written = 0
        try:
            async with driver.session(database=self.database) as session:
                for entity in entities:
                    if entity.type not in ENTITY_LABELS:
                        continue
                    entity_id = _entity_id(entity)
                    await session.run(
                        f"""
                        MERGE (n:{entity.type} {{entity_id: $entity_id}})
                        ON CREATE SET n.name = $name, n.updated_at = $updated_at
                        ON MATCH SET n.name = $name, n.updated_at = $updated_at
                        """,
                        entity_id=entity_id,
                        name=entity.value,
                        updated_at=_utc_now_iso(),
                    )
                    written += 1
            return written
        except Exception as exc:
            logger.warning(
                "Neo4j ontology insert failed entities=%d error=%s",
                len(entities),
                exc.__class__.__name__,
            )
            raise

    @staticmethod
    async def _write_experiment_tx(tx, experiment: Experiment, params: Dict[str, Any]):
        await tx.run(
            """
            MERGE (exp:Experiment {entity_id: $exp_id})
            SET exp.name = $exp_name,
                exp.confidence = $confidence,
                exp.year = $year,
                exp.geography = $geography,
                exp.source_type = $source_type,
                exp.is_sensitive = $is_sensitive,
                exp.updated_at = $updated_at
            """,
            exp_id=experiment.id,
            exp_name=experiment.name,
            confidence=experiment.confidence,
            year=experiment.year,
            geography=experiment.geography,
            source_type=experiment.source_type,
            is_sensitive=experiment.is_sensitive,
            updated_at=params["updated_at"],
        )

        for row in params["entities"]:
            label = row["label"]
            await tx.run(
                f"""
                MERGE (n:{label} {{entity_id: $entity_id}})
                SET n.name = $name, n.updated_at = $updated_at
                """,
                entity_id=row["entity_id"],
                name=row["name"],
                updated_at=params["updated_at"],
            )

        for edge in params["hyperedges"]:
            rel_type = edge["rel"]
            await tx.run(
                f"""
                MATCH (exp:Experiment {{entity_id: $exp_id}})
                MATCH (ent {{entity_id: $entity_id}})
                MERGE (exp)-[:{rel_type}]->(ent)
                """,
                exp_id=edge["exp_id"],
                entity_id=edge["entity_id"],
            )

        for rel in params["semantic_rels"]:
            rel_type = rel["rel_type"]
            await tx.run(
                f"""
                MERGE (s:{rel['source_label']} {{entity_id: $source_id}})
                SET s.name = $source_name, s.updated_at = $updated_at
                MERGE (t:{rel['target_label']} {{entity_id: $target_id}})
                SET t.name = $target_name, t.updated_at = $updated_at
                MERGE (s)-[:{rel_type}]->(t)
                """,
                source_id=rel["source_id"],
                target_id=rel["target_id"],
                source_name=rel["source_name"],
                target_name=rel["target_name"],
                updated_at=params["updated_at"],
            )

        for doc in params["evidence_files"]:
            doc_id = f"Publication:{doc}"
            await tx.run(
                """
                MATCH (exp:Experiment {entity_id: $exp_id})
                MERGE (pub:Publication {entity_id: $doc_id})
                SET pub.name = $doc_name, pub.updated_at = $updated_at
                MERGE (exp)-[:EVIDENCE_FROM]->(pub)
                """,
                exp_id=experiment.id,
                doc_id=doc_id,
                doc_name=doc,
                updated_at=params["updated_at"],
            )

    async def get_subgraph_for_experiments(
        self, experiment_ids: List[str], debug_list: List[str] = None
    ) -> Dict[str, Any]:
        """Batch fetch nodes/edges for visualization — N+1 safe single query."""
        if not self.is_configured or not experiment_ids:
            return {"nodes": [], "edges": [], "neo4j_latency_ms": 0.0}

        if self.dry_run:
            logger.info("Neo4j dry-run batch subgraph for %d experiment ids", len(experiment_ids))
            return {"nodes": [], "edges": [], "neo4j_latency_ms": 0.0}

        driver = self._get_driver()
        if driver is None:
            return {"nodes": [], "edges": [], "neo4j_latency_ms": 0.0}

        start = time.perf_counter()
        cypher = """
        MATCH (exp:Experiment)
        WHERE exp.entity_id IN $ids
        OPTIONAL MATCH (exp)-[r1]->(ent)
        OPTIONAL MATCH (ent)-[r2]->(other)
        WHERE other IS NULL OR other <> exp
        RETURN exp, r1, ent, r2, other
        """

        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        edge_keys: Set[Tuple[str, str, str]] = set()

        def add_node(node) -> Optional[str]:
            if node is None:
                return None
            labels = list(node.labels)
            label = labels[0] if labels else "Entity"
            node_id = node.get("entity_id") or node.element_id
            
            # Align with frontend Vis.js expectations
            if label == "Experiment":
                node_id = f"exp_{node_id}"
                
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "label": node.get("name") if label != "Experiment" else (node.get("entity_id") or node_id.replace("exp_", "")),
                    "group": label,
                    "title": f"Тип: {label}",
                }
            return node_id

        def add_edge(src_id: str, tgt_id: str, rel_type: str) -> None:
            key = (src_id, tgt_id, rel_type)
            if key in edge_keys:
                return
            edge_keys.add(key)
            edges.append(
                {
                    "from": src_id,
                    "to": tgt_id,
                    "label": rel_type,
                    "arrows": "to",
                }
            )

        try:
            async with driver.session(database=self.database) as session:
                result = await session.run(
                    Query(cypher, timeout=self.query_timeout),
                    ids=experiment_ids,
                )
                async for record in result:
                    exp_node = record["exp"]
                    exp_id = add_node(exp_node)
                    ent = record["ent"]
                    ent_id = add_node(ent)
                    other = record["other"]
                    other_id = add_node(other)

                    r1 = record["r1"]
                    if r1 is not None and exp_id and ent_id:
                         add_edge(exp_id, ent_id, r1.type)
                    r2 = record["r2"]
                    if r2 is not None and ent_id and other_id:
                         add_edge(ent_id, other_id, r2.type)

                    if debug_list is not None:
                        debug_list.append(
                            f"exp_id={exp_id}, ent_id={ent_id}, other_id={other_id}, "
                            f"r1_exists={r1 is not None}, r1_type={r1.type if r1 else None}, "
                            f"r2_exists={r2 is not None}, r2_type={r2.type if r2 else None}, "
                            f"len_edges={len(edges)}"
                        )

            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Neo4j batch subgraph ids=%d nodes=%d edges=%d latency_ms=%.1f",
                len(experiment_ids),
                len(nodes),
                len(edges),
                elapsed_ms,
            )
            return {
                "nodes": list(nodes.values()),
                "edges": edges,
                "neo4j_latency_ms": elapsed_ms,
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "Neo4j batch subgraph failed ids=%d latency_ms=%.1f error=%s",
                len(experiment_ids),
                elapsed_ms,
                exc.__class__.__name__,
            )
            return {"nodes": [], "edges": [], "neo4j_latency_ms": elapsed_ms}

    async def expand_graph_context(
        self, experiment_ids: List[str], max_hops: int = 2
    ) -> Dict[str, Any]:
        """Bounded Event-anchor context for search enrichment (no unbounded multi-hop).

        Soft-fails on TransientError / timeout / network: returns empty context with
        ``neo4j_error=True`` so callers can degrade to VSA-only.
        """
        empty = {
            "paths": [],
            "experts": [],
            "publications": [],
            "contradictions": [],
            "neo4j_latency_ms": 0.0,
        }
        if not self.is_configured or not experiment_ids:
            return empty

        if self.dry_run:
            return empty

        driver = self._get_driver()
        if driver is None:
            return empty

        start = time.perf_counter()
        # max_hops kept for API compat; expand is fixed to typed 1–2 hop patterns.
        _ = max(1, min(max_hops, 2))
        limit = self.expand_limit_per_exp

        # Typed edges only — no variable-length [*] that explode on dense nodes.
        cypher = """
        MATCH (exp:Experiment)
        WHERE exp.entity_id IN $ids
        OPTIONAL MATCH (exp)-[:EVIDENCE_FROM]->(pub:Publication)
        OPTIONAL MATCH (exp)-[:HAS_INPUT|HAS_PROCESS|HAS_OUTPUT]->(anchor)
        WHERE anchor IS NULL OR any(
            lbl IN labels(anchor) WHERE lbl IN
            ['Material','Process','Equipment','Property','Expert','Facility','Publication']
        )
        OPTIONAL MATCH (exp)-[:HAS_INPUT|HAS_PROCESS|HAS_OUTPUT]->()-[:VALIDATED_BY]->(expert:Expert)
        OPTIONAL MATCH (exp)-[:VALIDATED_BY]->(expert_direct:Expert)
        OPTIONAL MATCH (exp)-[:HAS_INPUT|HAS_PROCESS|HAS_OUTPUT]->()-[:CONTRADICTS]-(contradicted)
        OPTIONAL MATCH (exp)-[:CONTRADICTS]-(contradicted_direct)
        RETURN exp.entity_id AS exp_id,
               collect(DISTINCT pub) AS pubs,
               collect(DISTINCT expert) + collect(DISTINCT expert_direct) AS experts,
               collect(DISTINCT contradicted) + collect(DISTINCT contradicted_direct)
                   AS contradicted_nodes,
               collect(DISTINCT anchor) AS anchors
        """

        paths_out: List[Dict[str, Any]] = []
        experts: Set[str] = set()
        publications: Set[str] = set()
        contradictions: Set[str] = set()

        try:
            async with driver.session(database=self.database) as session:
                result = await session.run(
                    Query(cypher, timeout=self.interactive_timeout),
                    ids=experiment_ids,
                )
                async for record in result:
                    exp_id = record["exp_id"]
                    pubs = [n for n in (record["pubs"] or []) if n is not None][:limit]
                    expert_nodes = [n for n in (record["experts"] or []) if n is not None][:limit]
                    contradicted_nodes = [
                        n for n in (record["contradicted_nodes"] or []) if n is not None
                    ][:limit]
                    anchors = [n for n in (record["anchors"] or []) if n is not None][:limit]

                    for pub in pubs:
                        name = pub.get("name") or pub.get("entity_id")
                        if name:
                            publications.add(name)
                        paths_out.append(
                            {
                                "experiment_id": exp_id,
                                "nodes": [
                                    {"name": name, "type": "Publication"},
                                ],
                                "relations": ["EVIDENCE_FROM"],
                            }
                        )

                    for expert in expert_nodes:
                        name = expert.get("name") or expert.get("entity_id")
                        if name:
                            experts.add(name)

                    for other in contradicted_nodes:
                        name = other.get("name") or other.get("entity_id")
                        if name:
                            contradictions.add(name)

                    if anchors:
                        node_names = []
                        for anchor in anchors:
                            name = anchor.get("name") or anchor.get("entity_id")
                            labels = list(anchor.labels) if hasattr(anchor, "labels") else []
                            label = labels[0] if labels else "Entity"
                            node_names.append({"name": name, "type": label})
                            if label == "Expert" and name:
                                experts.add(name)
                            if label == "Publication" and name:
                                publications.add(name)
                        paths_out.append(
                            {
                                "experiment_id": exp_id,
                                "nodes": node_names,
                                "relations": ["HAS_INPUT", "HAS_PROCESS", "HAS_OUTPUT"],
                            }
                        )

            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Neo4j bounded expand ids=%d paths=%d latency_ms=%.1f batch_size=%d",
                len(experiment_ids),
                len(paths_out),
                elapsed_ms,
                len(experiment_ids),
            )
            return {
                "paths": paths_out[: limit * max(1, len(experiment_ids))],
                "experts": sorted(experts)[: limit * max(1, len(experiment_ids))],
                "publications": sorted(publications)[: limit * max(1, len(experiment_ids))],
                "contradictions": sorted(contradictions)[: limit * max(1, len(experiment_ids))],
                "neo4j_latency_ms": elapsed_ms,
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "Neo4j bounded expand failed batch_size=%d latency_ms=%.1f error=%s",
                len(experiment_ids),
                elapsed_ms,
                exc.__class__.__name__,
            )
            return {**empty, "neo4j_error": True, "neo4j_latency_ms": elapsed_ms}

    def describe_insert_plan(self, experiment: Experiment) -> Dict[str, Any]:
        """Dry-run helper: counts nodes/edges that would be written."""
        params = self._build_insert_params(experiment)
        return {
            "experiment_id": experiment.id,
            "entity_count": len(params["entities"]),
            "hyperedge_count": len(params["hyperedges"]),
            "semantic_relation_count": len(params["semantic_rels"]),
            "evidence_count": len(params["evidence_files"]),
        }


neo4j_graph = Neo4jGraphRepository()
