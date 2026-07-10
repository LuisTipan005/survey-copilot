from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import health, survey, rag, config  # <-- Añadimos config aquí

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(survey.router, prefix="/api/survey", tags=["survey"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"]) # <-- Nueva ruta RAG
app.include_router(config.router, prefix="/api/config", tags=["config"]) # <-- Rutas del Dashboard