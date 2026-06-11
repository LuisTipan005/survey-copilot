from fastapi import APIRouter, HTTPException
from app.models import SurveyAnalyzeRequest, SurveyAnalyzeResponse
from app.services.survey_analyzer import survey_analyzer
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/analyze", response_model=SurveyAnalyzeResponse)
async def analyze_survey(request: SurveyAnalyzeRequest):
    """
    Receives a list of detected questions, processes them via local LLM, 
    and returns the generated answers.
    """
    try:
        logger.info(f"Received request to analyze {len(request.questions)} questions.")
        response = await survey_analyzer.analyze(request)
        return response
    except Exception as e:
        logger.error(f"Error during survey analysis: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error during analysis.")