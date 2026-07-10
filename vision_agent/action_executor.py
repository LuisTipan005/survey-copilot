"""
Vision Agent — Action Executor Module

Translates LLM-generated actions into physical mouse/keyboard events
using PyAutoGUI with human-like easing curves, fail-safes, and
coordinate translation from local canvas space to absolute display space.
"""

import logging
import time

import pyautogui

from vision_agent.config import settings
from vision_agent.llm_client import Action, ActionType
from vision_agent.ocr_engine import FormField
from vision_agent.element_detector import ElementType

logger = logging.getLogger(__name__)

# ─── PyAutoGUI Global Configuration ──────────────────────────────

# CRITICAL: Moving mouse to any screen corner aborts execution
pyautogui.FAILSAFE = True

# Global pause between every PyAutoGUI call (seconds)
pyautogui.PAUSE = settings.ACTION_PAUSE


class ActionExecutor:
    """
    Executes automation actions on the physical screen.
    
    Translates local canvas coordinates (from the screenshot) into
    real display coordinates using the monitor offsets from mss,
    then performs human-like mouse movements and keyboard input.
    
    Actuation profiles:
    - Text Fields: smooth slide → click to focus → type with interval
    - Radio/Checkbox: smooth slide → single click
    - Dropdowns: smooth slide → click to open OS rendering
    """

    def __init__(self, monitor_left: int = 0, monitor_top: int = 0):
        """
        Args:
            monitor_left: X offset of the captured monitor in virtual screen space.
            monitor_top: Y offset of the captured monitor in virtual screen space.
        """
        self.monitor_left = monitor_left
        self.monitor_top = monitor_top

    def execute(
        self,
        actions: list[Action],
        form_fields: list[FormField],
    ) -> int:
        """
        Execute a list of actions on the physical screen.
        
        Args:
            actions: List of Action objects from VisionLLMClient.
            form_fields: List of FormField objects (for coordinate lookup).
            
        Returns:
            Number of actions successfully executed.
        """
        if not actions:
            logger.info("No actions to execute")
            return 0

        success_count = 0

        for i, action in enumerate(actions):
            try:
                logger.info(
                    f"Executing action {i + 1}/{len(actions)}: "
                    f"{action.action_type.value} on field [{action.target_index}]"
                )

                # Resolve target coordinates
                field = form_fields[action.target_index]
                abs_x, abs_y = self._to_absolute(field.element.cx, field.element.cy)

                # Dispatch based on action type and element type
                if action.action_type == ActionType.CLICK:
                    self._execute_click(abs_x, abs_y, field.element.element_type)
                elif action.action_type == ActionType.WRITE:
                    self._execute_write(
                        abs_x, abs_y,
                        action.text_payload,
                        field.element.element_type,
                    )

                success_count += 1
                logger.info(f"Action {i + 1} completed successfully")

                # Brief pause between actions for stability
                time.sleep(0.3)

            except pyautogui.FailSafeException:
                logger.critical(
                    "FAIL-SAFE TRIGGERED — Mouse moved to screen corner. "
                    "Aborting all remaining actions."
                )
                raise
            except Exception as e:
                logger.error(
                    f"Action {i + 1} failed: {e} "
                    f"(type={action.action_type.value}, "
                    f"target={action.target_index})"
                )
                continue

        logger.info(f"Execution complete: {success_count}/{len(actions)} actions succeeded")
        return success_count

    # ─── Coordinate Translation ──────────────────────────────────

    def _to_absolute(self, canvas_x: int, canvas_y: int) -> tuple[int, int]:
        """
        Translate local canvas coordinates to absolute display coordinates,
        applying DPI scaling correction.
        
        mss captures at native pixel resolution (e.g., 2400x1350 on a
        1920x1080 display at 125% scaling). pyautogui operates in logical
        coordinates. We divide by DPI_SCALE_FACTOR to convert.
        """
        dpi = settings.DPI_SCALE_FACTOR
        abs_x = int((canvas_x + self.monitor_left) / dpi)
        abs_y = int((canvas_y + self.monitor_top) / dpi)
        logger.debug(
            f"Coord translate: canvas({canvas_x},{canvas_y}) "
            f"+ offset({self.monitor_left},{self.monitor_top}) "
            f"/ DPI({dpi}) = absolute({abs_x},{abs_y})"
        )
        return (abs_x, abs_y)

    # ─── Actuation Profiles ──────────────────────────────────────

    def _smooth_move(self, x: int, y: int):
        """
        Move the cursor smoothly to the target position using
        easeInOutQuad tween for human-like motion.
        """
        pyautogui.moveTo(
            x, y,
            duration=settings.MOUSE_MOVE_DURATION,
            tween=pyautogui.easeInOutQuad,
        )

    def _execute_click(self, x: int, y: int, element_type: ElementType):
        """
        Click profile for radio buttons, checkboxes, and dropdowns.
        
        1. Smooth cursor movement to target center
        2. Single click to activate/toggle the element
        """
        logger.debug(f"Click at ({x}, {y}) for {element_type.value}")
        self._smooth_move(x, y)
        pyautogui.click()

    def _execute_write(
        self, x: int, y: int, text: str, element_type: ElementType
    ):
        """
        Write profile for text inputs and textareas.
        
        1. Smooth cursor movement to target center
        2. Click to focus the input field
        3. Select all existing content (Ctrl+A) to replace it
        4. Type the text with human-like character interval
        """
        if not text:
            logger.warning("Write action has empty text_payload — skipping")
            return

        logger.debug(f"Write at ({x}, {y}): '{text[:50]}...' for {element_type.value}")

        # Step 1: Move smoothly to the field
        self._smooth_move(x, y)

        # Step 2: Click to focus
        pyautogui.click()
        time.sleep(0.2)

        # Step 3: Select all existing content (in case the field has a default value)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)

        # Step 4: Type the text with human-like interval
        pyautogui.write(text, interval=settings.TYPING_INTERVAL)
