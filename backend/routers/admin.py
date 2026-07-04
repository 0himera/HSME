from fastapi import APIRouter, File, UploadFile, HTTPException, status
import shutil
import os
from backend.repository.database import db

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "super-secret-default")

def verify_admin(secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin secret")
    return True

@admin_router.post("/upload-db")
async def upload_db(secret: str, file: UploadFile = File(...)):
    """
    Uploads a new db_state.pkl to overwrite the existing one and reloads it into memory.
    Requires an admin secret token.
    """
    verify_admin(secret)
    
    try:
        # Save the uploaded file to the active database path
        with open(db.db_filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Reload the database state into memory
        success = db.load_from_disk(db.db_filepath)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to load database into memory after upload.")
            
        # Try to sync all experiments to Neo4j if it is configured
        from backend.repository.neo4j_graph import neo4j_graph
        synced_to_neo4j = 0
        neo4j_status = "disabled"
        if neo4j_graph.is_configured:
            neo4j_status = "connected"
            try:
                await neo4j_graph.ensure_indexes()
                for exp in db.experiments.values():
                    await neo4j_graph.insert_experiment_async(exp)
                    synced_to_neo4j += 1
            except Exception as neo_err:
                neo4j_status = f"failed: {neo_err}"
                print(f"Failed to sync experiments to Neo4j: {neo_err}")
            
        return {
            "status": "success", 
            "message": f"Database uploaded successfully and saved to {db.db_filepath}",
            "experiments_count": len(db.experiments),
            "neo4j_sync_status": neo4j_status,
            "neo4j_synced_count": synced_to_neo4j
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.get("/debug-neo4j")
async def debug_neo4j(secret: str):
    verify_admin(secret)
    from backend.repository.neo4j_graph import neo4j_graph
    if not neo4j_graph.is_configured:
        return {"status": "error", "message": "Neo4j is not configured"}
        
    driver = neo4j_graph._get_driver()
    if driver is None:
        return {"status": "error", "message": "Failed to get Neo4j driver"}
        
    try:
        async with driver.session(database=neo4j_graph.database) as session:
            # Nodes count
            res = await session.run("MATCH (n) RETURN labels(n) as lbls, count(n) as cnt")
            nodes = []
            async for r in res:
                nodes.append({"labels": list(r["lbls"]), "count": r["cnt"]})
                
            # Relationships count
            res = await session.run("MATCH ()-[r]->() RETURN type(r) as t, count(r) as cnt")
            relationships = []
            async for r in res:
                relationships.append({"type": r["t"], "count": r["cnt"]})
                
            # Sample relationships
            res = await session.run("MATCH (n)-[r]->(m) RETURN labels(n) as l1, n.entity_id as id1, type(r) as t, labels(m) as l2, m.entity_id as id2 LIMIT 5")
            samples = []
            async for r in res:
                samples.append({
                    "source": {"labels": list(r["l1"]), "id": r["id1"]},
                    "type": r["t"],
                    "target": {"labels": list(r["l2"]), "id": r["id2"]}
                })
                
            # Run a test of the actual subgraph query for EXP-RAW-01
            sub_res = await session.run(
                "MATCH (exp:Experiment) WHERE exp.entity_id IN $ids OPTIONAL MATCH (exp)-[r1]->(ent) OPTIONAL MATCH (ent)-[r2]->(other) WHERE other IS NULL OR other <> exp RETURN exp.entity_id as exp_id, r1, ent, r2, other LIMIT 5",
                ids=["EXP-RAW-01"]
            )
            subgraph_samples = []
            async for r in sub_res:
                subgraph_samples.append({
                    "exp_id": r["exp_id"],
                    "r1": r["r1"].type if r["r1"] else None,
                    "ent": r["ent"].get("entity_id") if r["ent"] else None,
                    "r2": r["r2"].type if r["r2"] else None,
                    "other": r["other"].get("entity_id") if r["other"] else None
                })
                
            return {
                "status": "success",
                "nodes": nodes,
                "relationships": relationships,
                "samples": samples,
                "subgraph_samples": subgraph_samples
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}
