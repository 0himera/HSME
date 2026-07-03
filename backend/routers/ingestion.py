from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import os
import asyncio
from backend.repository.database import db
from backend.services.ingestion import pipeline
from backend.routers.dependencies import UserSession, get_user_session, require_roles

router = APIRouter(prefix="/api", tags=["Ingestion"])

# Global task state for background indexing
active_ingestion_task: Optional[asyncio.Task] = None
ingestion_status = {
    "status": "idle",
    "files_indexed": 0,
    "total_chunks": 0,
    "error": None
}

async def run_bg_ingestion(data_dir: str):
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

@router.post("/ingest-corpus")
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

@router.get("/ingest-status")
async def get_ingest_status(session: UserSession = Depends(get_user_session)):
    """Returns the current status of background ingestion."""
    return ingestion_status
