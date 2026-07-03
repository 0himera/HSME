from fastapi import APIRouter, Depends
from typing import List
from backend.core.models import AuditEntry
from backend.repository.database import db
from backend.routers.dependencies import UserSession, require_roles

router = APIRouter(prefix="/api", tags=["Audit"])

@router.get("/audit-logs", response_model=List[AuditEntry])
async def get_audit_logs(session: UserSession = Depends(require_roles(["Administrator"]))):
    """Returns log of user actions for compliance and security audit."""
    db.log_action(
        username=session.username,
        role=session.role,
        action="VIEW_AUDIT_LOGS",
        details="Просмотр журналов аудита действий"
    )
    return db.audit_logs
