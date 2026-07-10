"""
Vision Agent — Main Orchestrator

Standalone desktop automation script that ties together all pipeline stages:

1. Screen Capture (mss) → BGR screenshot + monitor offsets
2. Element Detection (OpenCV) → interactive form elements
3. OCR + Label Mapping (Pytesseract) → form fields with question context
4. LLM Evaluation (OpenRouter) → structured action commands
5. Action Execution (PyAutoGUI) → physical mouse/keyboard automation

Usage:
    python -m vision_agent              # Run from project root
    python vision_agent/vision_agent.py # Direct execution

The script is completely standalone — no browser extension dependency.
Move the mouse to any screen corner to abort (PyAutoGUI fail-safe).
"""

import asyncio
import logging
import sys
import time

from vision_agent.config import settings
from vision_agent.screen_capture import ScreenCapture
from vision_agent.element_detector import ElementDetector
from vision_agent.ocr_engine import OCREngine
from vision_agent.llm_client import VisionLLMClient
from vision_agent.action_executor import ActionExecutor

# ─── Logging Configuration ───────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("VisionAgent")


# ─── Main Orchestrator Class ─────────────────────────────────────

class VisionAgent:
    """
    The main pipeline orchestrator for desktop quiz automation.
    
    Coordinates all five stages of the vision-based form-filling pipeline,
    from screen capture through physical action execution.
    """

    def __init__(self):
        self.screen_capture = ScreenCapture(monitor_index=settings.MONITOR_INDEX)
        self.element_detector = ElementDetector()
        self.ocr_engine = OCREngine()
        self.llm_client = VisionLLMClient()
        # ActionExecutor is created after capture (needs monitor offsets)
        self.action_executor = None

    async def run(self):
        """
        Execute the full vision agent pipeline.
        
        Pipeline:
        1. Capture screen → BGR image + offsets
        2. Detect elements → list of interactive form elements
        3. OCR + mapping → form fields with labels
        4. LLM evaluation → action commands
        5. Execute actions → physical automation
        """
        logger.info("=" * 60)
        logger.info("VISION AGENT — Starting Desktop Quiz Automation")
        logger.info(f"Model: {settings.LLM_MODEL}")
        logger.info(f"Monitor: {settings.MONITOR_INDEX}")
        logger.info("Move mouse to screen corner to ABORT (fail-safe)")
        logger.info("=" * 60)

        # Give the user a moment to Alt-Tab if launched via hotkey
        logger.info("⏳ Waiting 2 seconds for you to focus the target window...")
        await asyncio.sleep(2)

        pipeline_start = time.time()

        # ─── Stage 1: Screen Capture ─────────────────────────────
        logger.info("\n[Stage 1/5] Capturing screen...")
        capture_result = self.screen_capture.capture()

        if capture_result is None:
            logger.error("Screen capture failed — aborting pipeline")
            return

        logger.info(
            f"Captured {capture_result.monitor_width}x{capture_result.monitor_height} "
            f"at offset ({capture_result.monitor_left}, {capture_result.monitor_top})"
        )

        # Initialize ActionExecutor with monitor offsets
        self.action_executor = ActionExecutor(
            monitor_left=capture_result.monitor_left,
            monitor_top=capture_result.monitor_top,
        )

        # ─── Stage 2: Element Detection ──────────────────────────
        logger.info("\n[Stage 2/5] Detecting interactive elements...")
        elements = self.element_detector.detect(capture_result.image)

        if not elements:
            logger.warning("No interactive elements detected on screen — aborting")
            return

        for el in elements:
            logger.info(
                f"  → {el.element_type.value:10s} at ({el.x}, {el.y}) "
                f"size {el.w}x{el.h} [confidence: {el.confidence:.2f}]"
            )

        # Generate visual debug image with bounding boxes and crosshairs
        debug_path = self.element_detector.draw_debug_image(
            capture_result.image, elements, "debug_vision.png"
        )
        logger.info(f"📸 Debug image saved to: {debug_path}")
        logger.info(f"   DPI_SCALE_FACTOR = {settings.DPI_SCALE_FACTOR}")

        # ─── Stage 3: OCR + Label Mapping ────────────────────────
        logger.info("\n[Stage 3/5] Extracting text and mapping labels...")
        form_fields = self.ocr_engine.extract_and_map(
            capture_result.image, elements
        )

        if not form_fields:
            logger.warning("No form fields mapped — aborting")
            return

        for field in form_fields:
            options_str = ""
            if field.nearby_option_texts:
                options_str = f" | options: {field.nearby_option_texts}"
            logger.info(
                f"  [{field.index}] {field.element.element_type.value:10s} "
                f"label=\"{field.label_text[:80]}\"{options_str}"
            )

        # ─── Stage 4: LLM Evaluation ────────────────────────────
        logger.info("\n[Stage 4/5] Sending to LLM for evaluation...")
        actions = await self.llm_client.evaluate(form_fields)

        if not actions:
            logger.warning("LLM returned no actions — aborting execution")
            return

        for action in actions:
            logger.info(
                f"  → {action.action_type.value:5s} field[{action.target_index}] "
                f"{'text=' + action.text_payload[:50] if action.text_payload else ''} "
                f"{'anchor=' + action.target_text_anchor if action.target_text_anchor else ''}"
            )

        # ─── Stage 5: Execute Actions ────────────────────────────
        logger.info("\n[Stage 5/5] Executing automation actions...")
        logger.info("⚠️  Move mouse to any corner to ABORT")

        # Brief countdown to give the user time to switch focus
        for i in range(3, 0, -1):
            logger.info(f"  Starting in {i}...")
            await asyncio.sleep(1)

        success_count = self.action_executor.execute(actions, form_fields)

        # ─── Pipeline Complete ───────────────────────────────────
        elapsed = time.time() - pipeline_start
        logger.info("\n" + "=" * 60)
        logger.info(
            f"PIPELINE COMPLETE — {success_count}/{len(actions)} actions executed "
            f"in {elapsed:.1f}s"
        )
        logger.info("=" * 60)


# ─── CLI Entry Point ─────────────────────────────────────────────

def main():
    """Run the vision agent from the command line."""
    try:
        agent = VisionAgent()
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logger.info("\nAborted by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
