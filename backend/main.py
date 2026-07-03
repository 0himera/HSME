from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Any, Optional
import os
import asyncio

from backend.models import Entity, Experiment, SearchQuery, GapQuery, AuditEntry
from backend.database import HSMEVectorDatabase, seed_database
from backend.ingestion_pipeline import IngestionPipeline
from backend.nlp_extractor import NLPExtractor

app = FastAPI(title="HyperGraph Research Memory Engine")

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database with disk persistence and self-healing for format changes
db = HSMEVectorDatabase(dim=10000)
if not db.load_from_disk(db.db_filepath) or not any(exp.is_sensitive for exp in db.experiments.values() if exp.id.startswith("EXP-NI")):
    print(f"No persisted database found or old data format. Seeding mock experiments to {db.db_filepath}...")
    db.experiments.clear()
    db.vector_store.clear()
    seed_database(db)
    db.save_to_disk(db.db_filepath)
else:
    print(f"Loaded database state successfully from disk ({db.db_filepath}).")

# Security Dependency injection for users and roles
class UserSession:
    def __init__(self, username: str = "admin", role: str = "Administrator"):
        self.username = username
        self.role = role

def get_user_session(
    x_user_name: Optional[str] = Header(None, alias="X-User-Name"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role")
) -> UserSession:
    username = x_user_name or "admin"
    role = x_user_role or "Administrator"
    
    valid_roles = ["Administrator", "Analyst", "Researcher", "External Partner"]
    if role not in valid_roles:
        role = "Administrator"
        
    return UserSession(username=username, role=role)

def require_roles(allowed_roles: List[str]):
    def dependency(session: UserSession = Depends(get_user_session)):
        if session.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Доступ запрещен для роли {session.role}. Требуется одна из: {', '.join(allowed_roles)}"
            )
        return session
    return dependency

# Pipeline reference
pipeline = IngestionPipeline(db, concurrency_limit=6)

# Global status and task reference for background ingestion
ingestion_status = {
    "status": "idle",
    "files_indexed": 0,
    "total_chunks": 0,
    "error": None
}
active_ingestion_task: Optional[asyncio.Task] = None

async def run_bg_ingestion(data_dir: str):
    global ingestion_status
    ingestion_status["status"] = "running"
    ingestion_status["files_indexed"] = 0
    ingestion_status["total_chunks"] = 0
    ingestion_status["error"] = None
    
    def on_progress(file_path, chunks_count):
        ingestion_status["files_indexed"] += 1
        ingestion_status["total_chunks"] += chunks_count

    try:
        res = await pipeline.ingest_directory(data_dir, max_files=15, progress_callback=on_progress)
        ingestion_status["status"] = "completed"
        ingestion_status["files_indexed"] = res["files_indexed_count"]
        ingestion_status["total_chunks"] = res["total_chunks_indexed"]
    except asyncio.CancelledError:
        ingestion_status["status"] = "failed"
        ingestion_status["error"] = "Импорт отменен сервером (перезапуск)."
        raise
    except Exception as e:
        ingestion_status["status"] = "failed"
        ingestion_status["error"] = str(e)

@app.post("/api/ingest-corpus")
async def start_ingest_corpus(session: UserSession = Depends(require_roles(["Administrator"]))):
    """Starts background ingestion of targeted documents from data directory."""
    global active_ingestion_task
    if ingestion_status["status"] == "running":
        return {"status": "already_running", "message": "Ingestion is already in progress."}
        
    data_dir = "data/"
    if not os.path.exists(data_dir):
        raise HTTPException(status_code=400, detail="Data directory not found in workspace.")
        
    db.log_action(
        username=session.username,
        role=session.role,
        action="INGEST_CORPUS",
        details="Запуск фонового импорта корпуса документов"
    )
    active_ingestion_task = asyncio.create_task(run_bg_ingestion(data_dir))
    return {"status": "started", "message": "Ingestion process started in the background."}

@app.get("/api/ingest-status")
async def get_ingest_status(session: UserSession = Depends(get_user_session)):
    """Returns the current status of background ingestion."""
    return ingestion_status

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully cancels the background task on Uvicorn reload/shutdown to prevent hanging."""
    global active_ingestion_task
    if active_ingestion_task and not active_ingestion_task.done():
        print("Shutting down: Cancelling background ingestion task...")
        active_ingestion_task.cancel()
        try:
            await active_ingestion_task
        except asyncio.CancelledError:
            print("Background ingestion task successfully cancelled.")

@app.post("/api/ingest")
async def ingest_experiment(experiment: Experiment, session: UserSession = Depends(require_roles(["Administrator"]))):
    """Ingests a single experiment, generates its VSA hypervector, and indexes it."""
    try:
        db.log_action(
            username=session.username,
            role=session.role,
            action="INGEST_EXPERIMENT",
            details=f"Ручной импорт эксперимента {experiment.id}"
        )
        db.insert_experiment(experiment)
        return {"status": "success", "message": f"Experiment {experiment.id} ingested successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/experiments")
async def get_all_experiments(
    skip: int = 0, 
    limit: int = 100, 
    paged: bool = False,
    session: UserSession = Depends(get_user_session)
):
    """Returns stored experiments, supporting pagination and privacy filtering."""
    db.log_action(
        username=session.username,
        role=session.role,
        action="LIST_EXPERIMENTS",
        details=f"Запрошен список экспериментов (skip={skip}, limit={limit}, paged={paged})"
    )
    
    exclude_sensitive = (session.role == "External Partner")
    filtered = [
        exp for exp in db.experiments.values()
        if not (exclude_sensitive and exp.is_sensitive)
    ]
    
    if paged:
        sliced = filtered[skip:skip + limit]
        return {
            "total": len(filtered),
            "experiments": sliced
        }
    return filtered

@app.get("/api/audit-logs", response_model=List[AuditEntry])
async def get_audit_logs(session: UserSession = Depends(require_roles(["Administrator"]))):
    """Returns log of user actions for compliance and security audit."""
    db.log_action(
        username=session.username,
        role=session.role,
        action="VIEW_AUDIT_LOGS",
        details="Просмотр журналов аудита действий"
    )
    return db.audit_logs

@app.get("/api/documents")
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

@app.post("/api/search")
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
        
        # Get all results to allow pagination on our side
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

@app.get("/api/graph")
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
            
        # Node for the experiment
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
                
            # Connect experiment to entity
            edge_key = (exp_node_id, ent_node_id)
            if edge_key not in edge_set:
                edges.append({
                    "from": exp_node_id,
                    "to": ent_node_id,
                    "label": "связан"
                })
                edge_set.add(edge_key)
                
    return {"nodes": nodes, "edges": edges}

@app.get("/api/counterfactuals/{experiment_id}")
async def get_counterfactuals(
    experiment_id: str, 
    session: UserSession = Depends(require_roles(["Administrator", "Analyst", "Researcher"]))
):
    """Retrieves counterfactual experiments differing by exactly one parameter."""
    if experiment_id not in db.experiments:
        raise HTTPException(status_code=404, detail="Experiment not found")
        
    db.log_action(
        username=session.username,
        role=session.role,
        action="COUNTERFACTUALS",
        details=f"Запрос контрфактов для {experiment_id}"
    )
    return db.get_counterfactuals(experiment_id)

@app.get("/api/reason/{experiment_id}")
async def reason_causality(
    experiment_id: str,
    session: UserSession = Depends(require_roles(["Administrator", "Analyst"]))
):
    """Generates a causal explanation based on counterfactual analysis using Qwen 3.6 35B."""
    if experiment_id not in db.experiments:
        raise HTTPException(status_code=404, detail="Experiment not found")
        
    db.log_action(
        username=session.username,
        role=session.role,
        action="AI_REASON",
        details=f"Запуск причинно-следственного ИИ-анализа для {experiment_id}"
    )
    exp = db.experiments[experiment_id]
    cfs = db.get_counterfactuals(experiment_id)
    
    if not cfs:
        return {
            "experiment_id": experiment_id,
            "has_explanation": False,
            "explanation": f"В текущей базе данных не найдены контрфактические эксперименты для {experiment_id}. Попробуйте проиндексировать больше документов для нахождения связей."
        }
        
    cf_details = []
    for cf in cfs:
        cf_exp = cf["experiment"]
        diff = cf["difference"]
        effects = cf["effects"]
        
        eff_str = ", ".join([f"свойство '{e['property']}' изменилось с '{e['from']}' на '{e['to']}'" for e in effects])
        cf_details.append(
            f"- Сравнение с опытом {cf_exp.id} ('{cf_exp.name}'):\n"
            f"  Изменен параметр '{diff['parameter']}' с '{diff['from']}' на '{diff['to']}'.\n"
            f"  Наблюдаемые эффекты: {eff_str or 'без значительных изменений'}."
        )
        
    prompt = (
        f"Вы — ведущий научный аналитик в области горной металлургии. Проанализируйте следующие экспериментальные данные и составьте краткий научный отчет (2-3 абзаца) на русском языке о причинно-следственной связи между измененным параметром и свойствами продукта.\n\n"
        f"Исходный эксперимент: {exp.id} ('{exp.name}')\n"
        f"Контрфактические данные:\n"
        + "\n".join(cf_details) +
        f"\n\nОтчет должен объяснить физико-химический смысл наблюдаемого эффекта (почему изменение параметра приводит к такому изменению свойств) и сделать однозначный научный вывод."
    )
    
    try:
        extractor = NLPExtractor()
        response = await extractor.client.chat.completions.create(
            model="gpt://your_yandex_folder_id_here/yandexgpt-5.1/latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000
        )
        report = response.choices[0].message.content
        return {
            "experiment_id": experiment_id,
            "has_explanation": True,
            "explanation": report
        }
    except Exception as e:
        print(f"Causal reasoning LLM call failed: {e}")
        # Fallback to local rule-based summary
        explanations = []
        for cf in cfs[:2]:
            cf_exp = cf["experiment"]
            diff = cf["difference"]
            effects = cf["effects"]
            
            eff_summary = "\n".join([f"• свойство '{e['property']}' изменилось с {e['from']} на {e['to']}" for e in effects])
            explanation = (
                f"Сравнение {exp.id} с {cf_exp.id}:\n"
                f"  - Параметр '{diff['parameter']}' изменен с {diff['from']} на {diff['to']}.\n"
                f"  - Эффекты:\n{eff_summary or '• без изменений'}\n"
            )
            explanations.append(explanation)
            
        fallback_text = (
            f"### Научный отчет причинно-следственного анализа (Локальная копия)\n\n" +
            "\n".join(explanations) +
            f"\n**Вывод**: Изменение '{cfs[0]['difference']['parameter']}' оказывает влияние на "
            f"'{cfs[0]['effects'][0]['property'] if cfs[0]['effects'] else 'выходные параметры'}' со степенью достоверности {exp.confidence:.2f}."
        )
        return {
            "experiment_id": experiment_id,
            "has_explanation": True,
            "explanation": fallback_text
        }

@app.post("/api/gaps")
async def find_gaps(
    query: GapQuery,
    session: UserSession = Depends(require_roles(["Administrator", "Analyst", "Researcher"]))
):
    """Analyzes missing combinations (gaps) in research dimensions."""
    try:
        db.log_action(
            username=session.username,
            role=session.role,
            action="GAP_ANALYSIS",
            details=f"Поиск пробелов по измерениям: {query.dimensions}"
        )
        gaps = db.analyze_gaps(query.dimensions)
        return gaps
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/enrich-gap")
async def enrich_gap(
    gap_config: List[Entity],
    session: UserSession = Depends(require_roles(["Administrator", "Analyst"]))
):
    """Extrapolates property values and generates a hypothesis for a missing configuration using Qwen 3.6 35B."""
    db.log_action(
        username=session.username,
        role=session.role,
        action="GAP_ENRICHMENT",
        details=f"Синтез гипотезы для пробела: {', '.join([f'{e.type}:{e.value}' for e in gap_config])}"
    )
    config_desc = ", ".join([f"{e.type}: {e.value}" for e in gap_config])
    
    dimensions = [e.type for e in gap_config]
    all_gaps = db.analyze_gaps(dimensions)
    
    matching_gap = None
    for gap in all_gaps:
        gap_map = {e.type: e.value for e in gap["configuration"]}
        if all(gap_map.get(e.type) == e.value for e in gap_config):
            matching_gap = gap
            break
            
    if not matching_gap:
        return {
            "configuration": gap_config,
            "hypothesis": f"Конфигурация [{config_desc}] не является пробелом (уже исследована)."
        }
        
    predicted_props = matching_gap["predicted_properties"]
    prop_desc = ", ".join([f"{p.type} ~ {p.value}" for p in predicted_props]) if predicted_props else "Неизвестно"
    
    similar_ids = matching_gap["similar_experiments"]
    sim_details = []
    for sid in similar_ids:
        sexp = db.experiments[sid]
        inputs = ", ".join([f"{e.value}" for e in sexp.input_entities if e.type in dimensions])
        outputs = ", ".join([f"{e.type}={e.value}" for e in sexp.output_entities])
        sim_details.append(f"  * {sexp.id} ({inputs}) -> {outputs}")
        
    sim_context = "\n".join(sim_details) if sim_details else "  * Нет близких базовых экспериментов."
    
    prompt = (
        f"Вы — ведущий научный аналитик в области горной металлургии. Сформулируйте научную гипотезу (2-3 абзаца) "
        f"для неисследованной конфигурации параметров с обоснованием на основе топологически близких экспериментов.\n\n"
        f"Целевая конфигурация: {config_desc}\n"
        f"Экстраполированные свойства: {prop_desc}\n"
        f"Близкие базовые опыты:\n{sim_context}\n\n"
        f"Гипотеза должна объяснить ожидаемые свойства, физико-химические процессы, которые будут протекать, "
        f"и дать рекомендацию по проведению опытной проверки."
    )
    
    try:
        extractor = NLPExtractor()
        response = await extractor.client.chat.completions.create(
            model="gpt://your_yandex_folder_id_here/yandexgpt-5.1/latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000
        )
        hypothesis = response.choices[0].message.content
        return {
            "configuration": gap_config,
            "predicted_properties": predicted_props,
            "hypothesis": hypothesis
        }
    except Exception as e:
        print(f"Gap enrichment LLM call failed: {e}")
        fallback_hyp = (
            f"### Научная гипотеза для: [{config_desc}]\n\n"
            f"**Прогнозируемые свойства**:\n- {prop_desc}\n\n"
            f"**Обоснование**:\n"
            f"На основе VSA топологического анализа выявлены близкие к пробелу опыты:\n{sim_context}\n\n"
            f"Рекомендуется провести физический эксперимент при данных условиях для подтверждения стабильности manifold-структуры."
        )
        return {
            "configuration": gap_config,
            "predicted_properties": predicted_props,
            "hypothesis": fallback_hyp
        }

@app.get("/api/statistics")
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
    
    # Counts by entity types
    entity_counts = {}
    for exp in filtered_experiments:
        for ent in exp.get_all_entities():
            entity_counts[ent.type] = entity_counts.get(ent.type, 0) + 1
            
    # Count of distinct values per type
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

# Mount static frontend files if directory exists
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
