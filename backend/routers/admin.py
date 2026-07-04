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
            
        return {
            "status": "success", 
            "message": f"Database uploaded successfully and saved to {db.db_filepath}",
            "experiments_count": len(db.experiments)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
