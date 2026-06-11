import os
import shutil
import uuid
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List

from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Asegurarnos de que el directorio de almacenamiento exista
UPLOAD_DIR = "data/documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class DocumentResponse(BaseModel):
    status: str
    message: str
    doc_id: str | None = None

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    [Fase 2] Endpoint para subir e ingestar PDFs en ChromaDB.
    """
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Solo se soportan archivos PDF.")
    
    # Generar un ID único para el documento
    doc_id = str(uuid.uuid4())
    safe_filename = file.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{safe_filename}")
    
    # 1. Guardar el archivo físicamente en el disco
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"Archivo guardado en disco: {file_path}")
    except Exception as e:
        logger.error(f"Error guardando el archivo: {e}")
        raise HTTPException(status_code=500, detail=f"Fallo al guardar el archivo: {e}")
    
    # 2. Procesar el PDF con el RAG Service (PyMuPDF4LLM -> SmartChunker -> ChromaDB)
    success = await rag_service.ingest_document(
        file_path=file_path, 
        doc_id=doc_id, 
        filename=safe_filename
    )
    
    if not success:
        # Limpieza si falla la vectorización
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="Fallo al ingestar el documento en la base de datos vectorial.")
        
    return DocumentResponse(
        status="success",
        message=f"Documento '{safe_filename}' procesado e indexado correctamente.",
        doc_id=doc_id
    )

@router.get("/documents")
async def list_documents():
    """
    [Fase 2] Lista los documentos que han sido guardados físicamente.
    """
    if not os.path.exists(UPLOAD_DIR):
        return {"documents": []}
        
    docs = []
    for filename in os.listdir(UPLOAD_DIR):
        if filename.endswith(".pdf"):
            docs.append({"filename": filename.split('_', 1)[1] if '_' in filename else filename})
            
    return {"documents": docs, "total": len(docs)}

@router.get("/status")
async def rag_status():
    """Verifica si el servicio RAG está en línea."""
    return {"rag_active": rag_service.is_ready}