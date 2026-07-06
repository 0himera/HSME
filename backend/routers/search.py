from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Tuple, Dict, Any, Union
import time
import logging
from backend.core.models import SearchQuery, Entity
from backend.repository.database import db
from backend.repository.neo4j_graph import neo4j_graph
from backend.repository.ingestion_outbox import ingestion_outbox
from backend.services.graph_sync import graph_sync_service
from backend.core.config import USE_ASYNC_GRAPH_SYNC
from backend.routers.dependencies import UserSession, get_user_session
from backend.services.nlp_extractor import NLPExtractor
from backend.core.prompts import load_prompt
from backend.services.query_parse import parse_query_to_entities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Search & Graph"])


def _graph_context_has_data(graph_context: dict[str, Any] | None) -> bool:
    if not graph_context:
        return False
    return bool(
        graph_context.get("experts")
        or graph_context.get("publications")
        or graph_context.get("contradictions")
        or graph_context.get("paths")
    )


def _resolve_graph_enrichment_status(
    *,
    neo4j_configured: bool,
    has_results: bool,
    graph_context: dict[str, Any] | None,
    sync_state: dict[str, Any] | None,
) -> tuple[str, bool]:
    if not neo4j_configured or not has_results:
        return "skipped", False
    if graph_context and graph_context.get("neo4j_error"):
        return "error", False
    if sync_state and sync_state.get("has_lag"):
        return "sync_pending", True
    if _graph_context_has_data(graph_context):
        return "ok", False
    return "empty", False

@router.get("/documents")
async def get_documents(session: UserSession = Depends(get_user_session)):
    """Returns list of documents that have evidence in the experiments."""
    db.log_action(
        username=session.username,
        role=session.role,
        action="LIST_DOCUMENTS",
        details="Запрошен список документов-источников"
    )
    exclude_sensitive = (session.role == "External Partner")
    docs = {}
    for exp in db.experiments.values():
        if exclude_sensitive and exp.is_sensitive:
            continue
        for file in exp.evidence:
            if file not in docs:
                docs[file] = {
                    "filename": file,
                    "year": exp.year,
                    "geography": exp.geography,
                    "source_type": exp.source_type,
                    "experiments_count": 0
                }
            docs[file]["experiments_count"] += 1
    return list(docs.values())

async def synthesize_vsa_answer(
    query_text: str,
    experiments_results: list,
    graph_context: Optional[Dict[str, Any]] = None,
    entities: Optional[List[Entity]] = None,
) -> Tuple[str, Optional[float], Optional[float]]:
    """Generates a scientific reasoning answer based on VSA counterfactuals and entropy.

    Returns (answer_text, ttft_s, ttfa_s). TTFT/TTFA are None when LLM is not called.
    """
    if not experiments_results:
        top_results = []
        top_exps = []
        entropy_summary = "Релевантных экспериментов не найдено."
        counterfactuals_summary = "Нет контрфактов."
        exp_context = ""
    else:
        top_results = experiments_results[:2]
        top_exps = [res["experiment"] for res in top_results]
        
        # 1. Knowledge Entropy / Consensus — use VSA similarity (query relevance), not static confidence
        results_summary = []
        for res in top_results:
            exp = res["experiment"]
            sim = res.get("similarity", 0.0)
            outs = ", ".join([f"{e.type}: {e.value}" for e in exp.output_entities])
            results_summary.append(f"Опыт {exp.id}: {outs} (Сходство с запросом: {sim*100:.1f}%)")
            
        entropy_summary = "\n".join(results_summary)
        
        # 2. Counterfactuals for the top experiment
        top_exp = top_exps[0]
        cfs = db.get_counterfactuals(top_exp.id)
        
        cf_details = []
        if cfs:
            for cf in cfs[:2]:
                diff = cf["difference"]
                effects = cf["effects"]
                eff_str = ", ".join([f"свойство '{e['property']}' изменилось с '{e['from']}' на '{e['to']}'" for e in effects])
                cf_details.append(
                    f"- Если изменить '{diff['parameter']}' с '{diff['from']}' на '{diff['to']}', "
                    f"то наблюдается: {eff_str or 'без значительных изменений'}."
                )
                
        counterfactuals_summary = "\n".join(cf_details) if cf_details else "Нет близких контрфактических экспериментов для выявления прямых зависимостей."
        
        exp_context = "\n".join([f"- {e.id}: {e.name} (Источник: {', '.join(e.evidence)})" for e in top_exps])

    relevant_count = sum(1 for res in experiments_results if res.get("similarity", 0.0) > 0.05)
    
    gap_summary = ""
    if relevant_count < 3 and entities:
        valid_types = {"Material", "Process", "Equipment", "Property", "Facility"}
        gap_config = []
        seen_types = set()
        for e in entities:
            if e.type in valid_types and e.type not in seen_types:
                gap_config.append(e)
                seen_types.add(e.type)
                
        if gap_config:
            gap_dims = [e.type for e in gap_config]
            gaps = db.analyze_gaps(gap_dims, min_experiments=3, specific_combinations=[gap_config])
            if gaps:
                gap = gaps[0]
                gap_summary = f"\n\nВЫЯВЛЕНИЕ ПРОБЕЛОВ В ЗНАНИЯХ:\n"
                if gap["gap_type"] == "missing":
                    gap_summary += "- Данная комбинация параметров полностью не изучена (0 экспериментов в базе).\n"
                elif gap["gap_type"] == "weak":
                    gap_summary += f"- Данная область слабо освещена (найдено всего {gap['experiment_count']} экспериментов).\n"
                elif gap["gap_type"] == "foreign_only":
                    gap_summary += "- Эта технология описана только в зарубежной литературе, отечественного опыта не найдено.\n"
                elif gap["gap_type"] == "domestic_only":
                    gap_summary += "- Эта технология описана только в отечественной практике.\n"
                
                if gap["predicted_properties"]:
                    gap_summary += f"- Рекомендации (спрогнозированные значения): {', '.join([p.value for p in gap['predicted_properties']])}\n"

    graph_summary = ""
    if graph_context:
        experts = graph_context.get("experts") or []
        publications = graph_context.get("publications") or []
        contradictions = graph_context.get("contradictions") or []
        paths = graph_context.get("paths") or []
        if experts:
            graph_summary += f"\nСвязанные эксперты (Neo4j): {', '.join(experts[:5])}"
        if publications:
            graph_summary += f"\nСвязанные публикации (Neo4j): {', '.join(publications[:5])}"
        if contradictions:
            graph_summary += f"\nПротиворечия (CONTRADICTS): {', '.join(contradictions[:5])}"
        if paths:
            graph_summary += f"\nГрафовые пути (multi-hop): {len(paths)}"
    
    prompt_config = load_prompt("search_synthesize")
    system_prompt = prompt_config["system"]
    user_prompt = prompt_config["user"].format(
        query_text=query_text,
        exp_context=exp_context,
        entropy_summary=entropy_summary,
        counterfactuals_summary=counterfactuals_summary,
        graph_summary=graph_summary + gap_summary,
    )
    
    try:
        extractor = NLPExtractor()
        llm_start = time.perf_counter()
        stream = await extractor.client.chat.completions.create(
            model=extractor.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
            stream=True,
        )
        ttft_s: Optional[float] = None
        content_parts: List[str] = []
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                if ttft_s is None:
                    ttft_s = time.perf_counter() - llm_start
                content_parts.append(delta)
        ttfa_s = time.perf_counter() - llm_start
        
        ans = "".join(content_parts)
        if gap_summary:
            ans += "\n" + gap_summary
            
        return ans, ttft_s, ttfa_s
    except Exception as e:
        print(f"Failed to synthesize VSA answer: {e}")
        fallback = (
            f"**Синтез ответа недоступен (LLM Error).**\n\n"
            f"*Сырые причинные связи:*\n{counterfactuals_summary}"
        )
        return fallback, None, None

@router.post("/search")
async def search_experiments(query: SearchQuery, session: UserSession = Depends(get_user_session)):
    """Performs VSA semantic search with support for metadata filters and pagination."""
    try:
        entities = query.entities
        if query.query and not entities:
            entities = await parse_query_to_entities(query.query)
            
        if not entities:
            return {
                "total": 0,
                "results": []
            } if query.paged else []

        db.log_action(
            username=session.username,
            role=session.role,
            action="SEARCH",
            details=f"Семантический поиск: {', '.join([e.to_key() for e in entities])} (сырой запрос: '{query.query or ''}') (skip={query.skip}, limit={query.limit})"
        )
        exclude_sensitive = (session.role == "External Partner")
        
        vsa_start = time.perf_counter()
        results = db.search(
            entities, 
            limit=999999,
            year_start=query.year_start,
            year_end=query.year_end,
            geography=query.geography,
            source_type=query.source_type,
            exclude_sensitive=exclude_sensitive
        )
        vsa_latency_ms = (time.perf_counter() - vsa_start) * 1000
        
        formatted_results = [
            {
                "experiment": exp,
                "similarity": score
            }
            for exp, score in results
        ]
        
        sliced = formatted_results[query.skip : query.skip + query.limit]

        graph_context = None
        neo4j_latency_ms = 0.0
        sync_state = None
        if neo4j_graph.is_configured and sliced:
            exp_ids = [item["experiment"].id for item in sliced]
            graph_context = await neo4j_graph.expand_graph_context(exp_ids)
            neo4j_latency_ms = graph_context.get("neo4j_latency_ms", 0.0)
            if USE_ASYNC_GRAPH_SYNC and graph_sync_service.is_async_enabled:
                graph_sync_service.ensure_schema()
                sync_state = ingestion_outbox.get_sync_state(exp_ids)
            enrichment_status, lag_hint = _resolve_graph_enrichment_status(
                neo4j_configured=True,
                has_results=True,
                graph_context=graph_context,
                sync_state=sync_state,
            )
            logger.info(
                "Hybrid search vsa_latency_ms=%.1f neo4j_latency_ms=%.1f batch_size=%d "
                "graph_status=%s lag_hint=%s graph_context_present=%s",
                vsa_latency_ms,
                neo4j_latency_ms,
                len(exp_ids),
                enrichment_status,
                lag_hint,
                _graph_context_has_data(graph_context),
            )
        
        if query.paged:
            result_dict = {
                "total": len(formatted_results),
                "results": sliced,
                "vsa_latency_ms": round(vsa_latency_ms, 2),
                "neo4j_latency_ms": round(neo4j_latency_ms, 2),
            }
            enrichment_status, lag_hint = _resolve_graph_enrichment_status(
                neo4j_configured=neo4j_graph.is_configured,
                has_results=bool(sliced),
                graph_context=graph_context,
                sync_state=sync_state,
            )
            result_dict["graph_enrichment_status"] = enrichment_status
            result_dict["graph_sync_lag_hint"] = lag_hint
            if graph_context:
                result_dict["graph_context"] = {
                    "experts": graph_context.get("experts", []),
                    "publications": graph_context.get("publications", []),
                    "contradictions": graph_context.get("contradictions", []),
                }
            if query.query and session.role in ["Administrator", "Analyst"]:
                rag_ans, llm_ttft_s, llm_ttfa_s = await synthesize_vsa_answer(
                    query.query, sliced, graph_context, entities=entities
                )
                result_dict["rag_explanation"] = rag_ans
                if llm_ttft_s is not None:
                    result_dict["llm_ttft_s"] = round(llm_ttft_s, 4)
                if llm_ttfa_s is not None:
                    result_dict["llm_ttfa_s"] = round(llm_ttfa_s, 4)
            elif query.query:
                result_dict["rag_explanation"] = "Ваша роль не позволяет использовать модуль авто-синтеза ответов (LLM Reasoner)."
            
            return result_dict
            
        return sliced
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/graph")
async def get_graph(session: UserSession = Depends(get_user_session)):
    """Returns a visualizable graph representation (nodes & edges) of the hypergraph."""
    exclude_sensitive = (session.role == "External Partner")

    experiment_ids = [
        exp.id
        for exp in db.experiments.values()
        if not (exclude_sensitive and exp.is_sensitive)
    ][:50]

    if neo4j_graph.is_configured and experiment_ids:
        neo_subgraph = await neo4j_graph.get_subgraph_for_experiments(experiment_ids)
        if neo_subgraph.get("nodes"):
            return {
                "nodes": neo_subgraph["nodes"],
                "edges": neo_subgraph["edges"],
                "source": "neo4j",
                "neo4j_latency_ms": neo_subgraph.get("neo4j_latency_ms", 0.0),
            }

    # VSA fallback when Neo4j disabled or empty
    nodes = []
    edges = []
    node_set = set()
    edge_set = set()
    
    for exp_id in experiment_ids:
        exp = db.experiments.get(exp_id)
        if not exp:
            continue
            
        exp_node_id = f"exp_{exp.id}"
        if exp_node_id not in node_set:
            nodes.append({
                "id": exp_node_id,
                "label": exp.id,
                "group": "Experiment",
                "title": exp.name
            })
            node_set.add(exp_node_id)
            
        for ent in exp.get_all_entities():
            ent_node_id = ent.to_key()
            if ent_node_id not in node_set:
                nodes.append({
                    "id": ent_node_id,
                    "label": ent.value,
                    "group": ent.type,
                    "title": f"Тип: {ent.type}"
                })
                node_set.add(ent_node_id)
                
            edge_key = (exp_node_id, ent_node_id)
            if edge_key not in edge_set:
                edges.append({
                    "from": exp_node_id,
                    "to": ent_node_id,
                    "label": "связан"
                })
                edge_set.add(edge_key)

        for rel in getattr(exp, "relations", []):
            source_ent = db.get_entity_by_value(exp, rel.source)
            target_ent = db.get_entity_by_value(exp, rel.target)
            if source_ent and target_ent:
                src_key = source_ent.to_key()
                tgt_key = target_ent.to_key()
                
                edge_key = (src_key, tgt_key, rel.type)
                if edge_key not in edge_set:
                    edges.append({
                        "from": src_key,
                        "to": tgt_key,
                        "label": rel.type,
                        "arrows": "to",
                        "color": {"color": "#ff5722", "highlight": "#ff5722"}
                    })
                    edge_set.add(edge_key)
                
    return {"nodes": nodes, "edges": edges, "source": "vsa"}

@router.get("/statistics")
async def get_statistics(session: UserSession = Depends(get_user_session)):
    """Returns coverage and index statistics."""
    db.log_action(
        username=session.username,
        role=session.role,
        action="GET_STATISTICS",
        details="Запрошена статистика покрытия графа R&D"
    )
    exclude_sensitive = (session.role == "External Partner")
    filtered_experiments = [
        exp for exp in db.experiments.values()
        if not (exclude_sensitive and exp.is_sensitive)
    ]
    total_experiments = len(filtered_experiments)
    
    entity_counts = {}
    for exp in filtered_experiments:
        for ent in exp.get_all_entities():
            entity_counts[ent.type] = entity_counts.get(ent.type, 0) + 1
            
    distinct_counts = {}
    for role in db.roles:
        vals = set()
        for exp in filtered_experiments:
            for ent in exp.get_all_entities():
                if ent.type == role:
                    vals.add(ent.value)
        distinct_counts[role] = len(vals)
        
    return {
        "total_experiments": total_experiments,
        "entity_counts": entity_counts,
        "distinct_counts": distinct_counts
    }
