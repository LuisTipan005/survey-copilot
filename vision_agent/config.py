"""
Vision Agent — Configuration Module

Centralizes all settings for the vision agent pipeline:
API keys, model selection, Tesseract path, CV thresholds, and automation parameters.
Loads from the shared backend .env file.
"""

import os
from pydantic_settings import BaseSettings


class VisionSettings(BaseSettings):
    """Configuration for the Vision Agent standalone module."""

    # ─── OpenRouter LLM Configuration ────────────────────────────
    OPENROUTER_API_KEY: str = ""
    LLM_MODEL: str = "openai/gpt-4o-mini"
    APP_URL: str = "http://localhost:8000"
    PROJECT_NAME: str = "Survey Copilot Vision Agent"

    # ─── Tesseract OCR Configuration ─────────────────────────────
    TESSERACT_CMD: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    # ─── Monitor Selection ───────────────────────────────────────
    # mss monitor index: 0 = virtual combined screen, 1 = primary, 2+ = secondary
    MONITOR_INDEX: int = 1

    # ─── OpenCV Element Detection Thresholds ─────────────────────
    # Contour detection
    CANNY_LOW: int = 50
    CANNY_HIGH: int = 150
    MIN_CONTOUR_AREA: int = 800
    MAX_CONTOUR_AREA: int = 500000
    # Input fields: aspect ratio > this value
    INPUT_ASPECT_RATIO_MIN: float = 3.0
    # Textareas: aspect ratio range + minimum height
    TEXTAREA_ASPECT_RATIO_MIN: float = 1.5
    TEXTAREA_ASPECT_RATIO_MAX: float = 6.0
    TEXTAREA_MIN_HEIGHT: int = 80

    # Template matching
    TEMPLATE_MATCH_THRESHOLD: float = 0.7
    NMS_RADIUS: int = 10

    # ─── OCR Spatial Mapping ─────────────────────────────────────
    # Max pixel distance to associate a text label with a form element
    LABEL_SEARCH_ABOVE_PX: int = 80
    LABEL_SEARCH_LEFT_PX: int = 300

    # ─── PyAutoGUI Automation ────────────────────────────────────
    MOUSE_MOVE_DURATION: float = 1.0
    TYPING_INTERVAL: float = 0.02
    ACTION_PAUSE: float = 0.5

    # ─── DPI Scaling ─────────────────────────────────────────────
    # Windows display scaling correction factor.
    # mss captures at native pixel resolution, but pyautogui uses
    # logical (scaled) coordinates. If Windows is set to 125% scaling,
    # set this to 1.25. At 150%, set to 1.5. At 100%, leave at 1.0.
    # Formula: pyautogui_coord = mss_pixel_coord / DPI_SCALE_FACTOR
    DPI_SCALE_FACTOR: float = 1.0

    # ─── LLM Temperature ────────────────────────────────────────
    DEFAULT_TEMPERATURE: float = 0.1

    class Config:
        # Load from the shared backend .env
        env_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "backend", ".env"
        )


settings = VisionSettings()
