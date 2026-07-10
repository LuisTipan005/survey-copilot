import os
import re
import shutil
import uuid
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = "data/documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)
ENV_FILE = ".env"

class ModelUpdateRequest(BaseModel):
    model: str

class ModelResponse(BaseModel):
    model: str

class DocumentResponse(BaseModel):
    status: str
    message: str
    doc_id: str | None = None

@router.get("/model", response_model=ModelResponse)
async def get_model():
    return ModelResponse(model=settings.LLM_MODEL)

@router.post("/model", response_model=ModelResponse)
async def update_model(req: ModelUpdateRequest):
    # Update in-memory settings
    settings.LLM_MODEL = req.model
    logger.info(f"Model updated in memory to {req.model}")

    # Update .env file
    try:
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, "r") as f:
                lines = f.readlines()
            
            with open(ENV_FILE, "w") as f:
                updated = False
                for line in lines:
                    if line.startswith("LLM_MODEL="):
                        f.write(f"LLM_MODEL={req.model}\n")
                        updated = True
                    else:
                        f.write(line)
                
                # If LLM_MODEL wasn't found, append it
                if not updated:
                    if not lines[-1].endswith("\n"):
                        f.write("\n")
                    f.write(f"LLM_MODEL={req.model}\n")
            logger.info(f"Model updated in .env to {req.model}")
    except Exception as e:
        logger.error(f"Error updating .env file: {e}")
        # Even if writing to .env fails, we still updated in memory

    return ModelResponse(model=settings.LLM_MODEL)


@router.post("/upload-pdf", response_model=DocumentResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """
    Accepts PDF files, saves them to data/documents/ and triggers RAG ingestion.
    """
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    doc_id = str(uuid.uuid4())
    safe_filename = file.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{safe_filename}")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"PDF saved physically: {file_path}")
    except Exception as e:
        logger.error(f"Error saving PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    
    success = await rag_service.ingest_document(
        file_path=file_path, 
        doc_id=doc_id, 
        filename=safe_filename
    )
    
    if not success:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="Failed to ingest document into vector DB.")
        
    return DocumentResponse(
        status="success",
        message=f"Document '{safe_filename}' successfully indexed.",
        doc_id=doc_id
    )

@router.get("/documents")
async def list_documents():
    """Lists currently indexed PDFs."""
    if not os.path.exists(UPLOAD_DIR):
        return {"documents": []}
        
    docs = []
    for filename in os.listdir(UPLOAD_DIR):
        if filename.endswith(".pdf"):
            # Ensure we remove the UUID prefix if it exists
            # We expect format: uuid_filename.pdf
            parts = filename.split('_', 1)
            display_name = parts[1] if len(parts) > 1 else filename
            docs.append({"filename": display_name, "raw_name": filename})
            
    return {"documents": docs, "total": len(docs)}

@router.delete("/documents/{filename}")
async def delete_document(filename: str):
    """Deletes a PDF from index and disk."""
    success = await rag_service.delete_document(filename)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to remove vectors from database.")
    
    # Try to find and delete the physical file
    deleted_physical = False
    if os.path.exists(UPLOAD_DIR):
        for f in os.listdir(UPLOAD_DIR):
            if f.endswith(filename):
                file_path = os.path.join(UPLOAD_DIR, f)
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted physical file: {file_path}")
                    deleted_physical = True
                except Exception as e:
                    logger.error(f"Failed to delete physical file {f}: {e}")
    
    return {"status": "success", "message": "Document removed"}
