from fastapi import APIRouter, HTTPException, Depends
from backend.core.models import SearchQuery
from backend.repository.database import db
from backend.routers.dependencies import UserSession, get_user_session

router = APIRouter(prefix="/api", tags=["Search & Graph"])

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

@router.post("/search")
async def search_experiments(query: SearchQuery, session: UserSession = Depends(get_user_session)):
    """Performs VSA semantic search with support for metadata filters and pagination."""
    try:
        db.log_action(
            username=session.username,
            role=session.role,
            action="SEARCH",
            details=f"Семантический поиск: {', '.join([e.to_key() for e in query.entities])} (skip={query.skip}, limit={query.limit})"
        )
        exclude_sensitive = (session.role == "External Partner")
        
        results = db.search(
            query.entities, 
            limit=999999,
            year_start=query.year_start,
            year_end=query.year_end,
            geography=query.geography,
            source_type=query.source_type,
            exclude_sensitive=exclude_sensitive
        )
        
        formatted_results = [
            {
                "experiment": exp,
                "similarity": score
            }
            for exp, score in results
        ]
        
        sliced = formatted_results[query.skip : query.skip + query.limit]
        
        if query.paged:
            return {
                "total": len(formatted_results),
                "results": sliced
            }
        return sliced
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/graph")
async def get_graph(session: UserSession = Depends(get_user_session)):
    """Returns a visualizable graph representation (nodes & edges) of the hypergraph."""
    exclude_sensitive = (session.role == "External Partner")
    nodes = []
    edges = []
    node_set = set()
    edge_set = set()
    
    for exp in db.experiments.values():
        if exclude_sensitive and exp.is_sensitive:
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
                
    return {"nodes": nodes, "edges": edges}

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
