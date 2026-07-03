from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Tuple
from backend.core.models import SearchQuery, Entity
from backend.repository.database import db
from backend.routers.dependencies import UserSession, get_user_session
from backend.services.nlp_extractor import NLPExtractor

router = APIRouter(prefix="/api", tags=["Search & Graph"])

async def parse_query_to_entities(query_text: str) -> List[Entity]:
    """Parses natural language query to a list of structured Entity objects using YandexGPT 120B with a local regex fallback."""
    system_prompt = (
        "Вы — научный ассистент по поиску в базе знаний R&D в области горной металлургии. "
        "Ваша задача — разобрать поисковый запрос пользователя на естественном языке на список структурированных сущностей.\n\n"
        "Доступные типы сущностей:\n"
        "- Material: вещества, металлы, растворы, руды (например: никель, медь, сернокислый электролит)\n"
        "- Process: процессы (например: электроэкстракция, выщелачивание)\n"
        "- Equipment: оборудование (например: ванна электроэкстракции)\n"
        "- Property: числовые параметры, условия и диапазоны (например: pH < 2.0, температура: 45°C, плотность тока: 300 А/м2)\n"
        "- Facility: промышленные объекты (например: Кольская ГМК)\n\n"
        "Ответ предоставьте строго в формате JSON (список объектов с ключами type и value), без лишнего текста и разметки. Пример:\n"
        "[\n"
        "  {\"type\": \"Material\", \"value\": \"никель\"},\n"
        "  {\"type\": \"Process\", \"value\": \"электроэкстракция\"},\n"
        "  {\"type\": \"Property\", \"value\": \"pH < 2.0\"}\n"
        "]"
    )

    try:
        extractor = NLPExtractor()
        response = await extractor.client.chat.completions.create(
            model="gpt://your_yandex_folder_id_here/yandexgpt-5.1/latest",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Запрос: {query_text}"}
            ],
            temperature=0.1,
            max_tokens=300
        )
        content = response.choices[0].message.content.strip()
        
        # Robustly extract JSON list block using regex matching [...]
        import re
        import json
        json_match = re.search(r'(\[\s*\{.*\}\s*\])', content, re.DOTALL)
        if json_match:
            content = json_match.group(1).strip()
        else:
            cb_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
            if cb_match:
                content = cb_match.group(1).strip()
            else:
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
        parsed = json.loads(content)
        entities = []
        for item in parsed:
            t = item.get("type")
            v = item.get("value")
            if t and v:
                entities.append(Entity(type=t, value=v))
        if entities:
            return entities
    except Exception as e:
        print(f"Failed to parse query via YandexGPT: {e}")
        
    # Local fallback parsing
    entities = []
    text_lower = query_text.lower()
    
    # Check for materials
    materials = ["никель", "медь", "электролит", "раствор", "руда", "шлак", "кобальт", "шлам"]
    for mat in materials:
        if mat in text_lower:
            entities.append(Entity(type="Material", value=mat.capitalize() if mat not in ["никель", "медь"] else mat))
            
    # Check for processes
    processes = [("электроэкстракция", "Электроэкстракция"), ("выщелачивание", "Кучное выщелачивание")]
    for p_kw, p_val in processes:
        if p_kw in text_lower:
            entities.append(Entity(type="Process", value=p_val))
            
    # Check for facilities
    facilities = [("кольская", "Кольская ГМК"), ("long harbour", "Завод Long Harbour"), ("кайеркан", "рудник Кайерканский")]
    for f_kw, f_val in facilities:
        if f_kw in text_lower:
            entities.append(Entity(type="Facility", value=f_val))
            
    # Check for pH, temperature, current density using regex
    import re
    # Match pH comparisons e.g. "ph < 2.0"
    ph_match = re.search(r'\b(ph\s*[:=<>≤≥]?\s*\d+([.,]\d+)?)\b', text_lower)
    if ph_match:
        entities.append(Entity(type="Property", value=ph_match.group(1).upper()))
    else:
        # Match standalone pH values e.g. "ph 2"
        ph_match2 = re.search(r'\b(ph\s+\d+([.,]\d+)?)\b', text_lower)
        if ph_match2:
            entities.append(Entity(type="Property", value=ph_match2.group(1).upper().replace(" ", ": ")))
            
    # Match temperature e.g. "45°C"
    temp_match = re.search(r'\b(\d+\s*°c)\b', text_lower)
    if temp_match:
        entities.append(Entity(type="Property", value=f"Температура: {temp_match.group(1).upper()}"))
        
    # Match current density e.g. "300 А/м2"
    dens_match = re.search(r'\b(\d+\s*а/м2)\b', text_lower)
    if dens_match:
        entities.append(Entity(type="Property", value=f"плотность тока: {dens_match.group(1).upper()}"))
        
    return entities

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
        
        results = db.search(
            entities, 
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

        # Ingest relations between entities
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
