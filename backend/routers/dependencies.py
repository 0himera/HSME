from fastapi import Header, Depends, HTTPException
from typing import List, Optional

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
