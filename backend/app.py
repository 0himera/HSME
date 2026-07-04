from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import logging

from backend.routers.experiments import router as experiments_router
from backend.routers.search import router as search_router
from backend.routers.gaps import router as gaps_router
from backend.routers.analytics import router as analytics_router
from backend.routers.audit import router as audit_router
from backend.routers.ingestion import router as ingestion_router
from backend.repository.neo4j_graph import neo4j_graph

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: bootstrap Neo4j indexes if enabled
    if neo4j_graph.is_configured:
        ok = await neo4j_graph.ensure_indexes()
        if ok:
            logger.info("Neo4j graph storage initialized")
        else:
            logger.warning("Neo4j unavailable — running VSA-only fallback")
    yield
    # Shutdown: Gracefully cancels background ingestion task on Uvicorn reload/shutdown to prevent hanging
    import backend.routers.ingestion as ing_mod
    if ing_mod.active_ingestion_task and not ing_mod.active_ingestion_task.done():
        print("Shutting down: Cancelling background ingestion task...")
        ing_mod.active_ingestion_task.cancel()
        try:
            await ing_mod.active_ingestion_task
        except Exception:
            pass
    await neo4j_graph.close()

app = FastAPI(title="HyperGraph Research Memory Engine", lifespan=lifespan)

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(experiments_router)
app.include_router(search_router)
app.include_router(gaps_router)
app.include_router(analytics_router)
app.include_router(audit_router)
app.include_router(ingestion_router)

# Mount static frontend files if directory exists
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "out"))
if not os.path.exists(frontend_path):
    frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

