from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models import SurveyAnalyzeRequest, SurveyAnalyzeResponse
from app.services.survey_analyzer import survey_analyzer
import logging
import json

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze", response_model=SurveyAnalyzeResponse)
async def analyze_survey(request: SurveyAnalyzeRequest):
    """
    Standard endpoint (≤ 3 questions).
    Receives a list of detected questions, processes them sequentially via
    the LLM pipeline, and returns the full answer list in one JSON response.
    """
    try:
        logger.info(f"[analyze] Received {len(request.questions)} question(s).")
        response = await survey_analyzer.analyze(request)
        return response
    except Exception as e:
        logger.error(f"Error during survey analysis: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during analysis.")


@router.post("/analyze_batch")
async def analyze_survey_batch(request: SurveyAnalyzeRequest):
    """
    Batch endpoint (> 3 questions).
    Processes all questions concurrently behind asyncio.Semaphore(3) and
    streams each completed answer as an NDJSON line so the Chrome Extension
    can update its progress bar in real time.

    Response format: application/x-ndjson
    Each line is a JSON object representing one GeneratedAnswer.
    """
    logger.info(f"[analyze_batch] Received {len(request.questions)} question(s) for batch processing.")

    async def ndjson_stream():
        try:
            async for answer in survey_analyzer.analyze_batch(request):
                # Serialize each GeneratedAnswer as a single JSON line
                line = json.dumps(answer.model_dump()) + "\n"
                yield line
        except Exception as e:
            logger.error(f"[analyze_batch] Stream error: {e}")
            # Yield an error sentinel so the client knows something went wrong
            yield json.dumps({"error": str(e)}) + "\n"

    return StreamingResponse(
        ndjson_stream(),
        media_type="application/x-ndjson",
        headers={
            # Prevent buffering so lines are flushed immediately
            "X-Accel-Buffering": "no",
            "Cache-Control":     "no-cache",
        },
    )