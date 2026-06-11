from fastapi import APIRouter
from app.config import settings

router = APIRouter()

@router.get("/")
async def health_check():
    """Simple health check endpoint."""
    return {
        "status": "ok", 
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "ollama_model": settings.OLLAMA_MODEL
    }