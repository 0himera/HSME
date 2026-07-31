"""Legacy entrypoint — use: uv run uvicorn backend.app:app --reload"""

from backend.app import app

__all__ = ["app"]
