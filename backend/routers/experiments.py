from fastapi import APIRouter, HTTPException, Depends
from typing import List
from backend.core.models import Experiment
from backend.repository.database import db
from backend.routers.dependencies import UserSession, get_user_session, require_roles

router = APIRouter(prefix="/api", tags=["Experiments"])

@app_post := router.post("/ingest")
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

@app_get := router.get("/experiments")
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
