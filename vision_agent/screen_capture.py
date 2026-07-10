"""
Vision Agent — Screen Capture Module

Ultra-fast screen capture using mss (Multiple Screen Shots).
Returns a BGR numpy array suitable for OpenCV processing,
along with monitor offset metadata for coordinate translation.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import mss
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CaptureResult:
    """Result of a screen capture operation."""
    image: np.ndarray        # BGR numpy array (OpenCV-compatible)
    monitor_left: int        # X offset of the monitor in virtual screen space
    monitor_top: int         # Y offset of the monitor in virtual screen space
    monitor_width: int       # Width of the captured region
    monitor_height: int      # Height of the captured region


class ScreenCapture:
    """
    High-performance screen capture using mss.
    
    Captures a specific monitor (default: primary) and returns
    the image as a numpy array with monitor offset metadata
    for translating local pixel coordinates to absolute display coordinates.
    """

    def __init__(self, monitor_index: int | str = 1):
        """
        Args:
            monitor_index: mss monitor index.
                0 = virtual combined screen (all monitors).
                1 = primary monitor.
                2+ = secondary monitors.
                "active" = auto-detect monitor containing mouse cursor.
        """
        self.monitor_index = monitor_index

    def _get_active_monitor_index(self, monitors: list[dict]) -> int:
        """Find the index of the monitor that currently contains the mouse cursor."""
        try:
            import pyautogui
            mx, my = pyautogui.position()
            # Start from index 1 (0 is the virtual combined monitor)
            for i in range(1, len(monitors)):
                m = monitors[i]
                if (m["left"] <= mx < m["left"] + m["width"] and
                        m["top"] <= my < m["top"] + m["height"]):
                    return i
        except Exception as e:
            logger.error(f"Failed to detect active monitor: {e}")
        
        return 1  # Fallback to primary monitor

    def capture(self) -> Optional[CaptureResult]:
        """
        Capture the target monitor's screen content.
        
        Returns:
            CaptureResult with BGR image and monitor offset metadata,
            or None if capture fails.
        """
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                
                if str(self.monitor_index).lower() == "active":
                    target_idx = self._get_active_monitor_index(monitors)
                else:
                    target_idx = int(self.monitor_index)

                if target_idx >= len(monitors):
                    logger.error(
                        f"Monitor index {target_idx} out of range. "
                        f"Available monitors: {len(monitors) - 1} "
                        f"(indices 0–{len(monitors) - 1})"
                    )
                    return None

                monitor = monitors[target_idx]
                logger.info(
                    f"Capturing monitor {target_idx}: "
                    f"{monitor['width']}x{monitor['height']} "
                    f"at offset ({monitor['left']}, {monitor['top']})"
                )

                # Grab the screen — returns an mss.ScreenShot object
                screenshot = sct.grab(monitor)

                # Convert to numpy array: mss returns BGRA, we need BGR for OpenCV
                frame = np.array(screenshot)
                # Drop alpha channel: BGRA → BGR
                frame_bgr = frame[:, :, :3].copy()

                return CaptureResult(
                    image=frame_bgr,
                    monitor_left=monitor["left"],
                    monitor_top=monitor["top"],
                    monitor_width=monitor["width"],
                    monitor_height=monitor["height"],
                )

        except Exception as e:
            logger.error(f"Screen capture failed: {e}")
            return None

    def list_monitors(self) -> list[dict]:
        """List all available monitors and their geometries."""
        with mss.mss() as sct:
            return [
                {
                    "index": i,
                    "left": m["left"],
                    "top": m["top"],
                    "width": m["width"],
                    "height": m["height"],
                }
                for i, m in enumerate(sct.monitors)
            ]
