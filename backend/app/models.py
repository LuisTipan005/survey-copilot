from enum import Enum
from pydantic import BaseModel
from typing import List, Optional
from dataclasses import dataclass

class QuestionType(str, Enum):
    TEXT = "text"
    SINGLE_CHOICE = "single"
    MULTIPLE_CHOICE = "multi"
    SCALE = "scale"
    DROPDOWN = "dropdown"
    CLOZE = "cloze"   # Multi-gap fill-in-the-blank

class DetectedQuestion(BaseModel):
    element_id: Optional[str] = None
    element_ids: Optional[List[str]] = None   # Used for cloze gaps & radio groups
    question_text: str
    question_type: QuestionType
    options: Optional[List[str]] = None
    context: Optional[str] = None
    gap_count: Optional[int] = None           # Number of [GAP n] placeholders (cloze only)
    # Multimodal Vision: a Base64 data URL or absolute URL of an image
    # embedded in the question (e.g. "Analyze the following diagram").
    image_base64: Optional[str] = None

from typing import List, Optional, Union

class GeneratedAnswer(BaseModel):
    question_text: str
    answer: str
    confidence: float
    reasoning: Optional[str] = None
    selected_options: Optional[List[Union[int, str]]] = None
    # Nuevos campos para Fase 2
    context_used: bool = False
    context_sources: Optional[List[str]] = None

class SurveyAnalyzeRequest(BaseModel):
    questions: List[DetectedQuestion]
    survey_context: Optional[str] = None
    user_profile: Optional[str] = None

class SurveyAnalyzeResponse(BaseModel):
    answers: List[GeneratedAnswer]
    model_used: str
    processing_time_ms: float

# --- NUEVOS MODELOS FASE 2 ---

@dataclass
class DocumentSection:
    """Una sección semánticamente significativa de un documento."""
    heading: str             
    content: str             
    level: int               
    page_numbers: list[int]  
    doc_type: str            

@dataclass
class RetrievedChunk:
    """Un fragmento recuperado de la base de datos vectorial con un score de relevancia."""
    text: str
    metadata: dict
    score: float        
    source: str