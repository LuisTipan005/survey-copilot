"""
Vision Agent — Element Detector Module

Detects interactive form elements on screen using two OpenCV pipelines:

1. **Contour Pipeline**: Canny edge detection → findContours → approxPolyDP
   → geometric filtering to classify inputs, textareas, and selectboxes.

2. **Template Matching Pipeline**: matchTemplate with TM_CCOEFF_NORMED
   against synthetic radio/checkbox templates, with Non-Maximum Suppression.

Auto-generates template images at runtime if they don't exist on disk.
"""

import os
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import cv2
import numpy as np

from vision_agent.config import settings

logger = logging.getLogger(__name__)


# ─── Data Models ──────────────────────────────────────────────────

class ElementType(str, Enum):
    """Types of interactive form elements detected on screen."""
    INPUT = "input"
    TEXTAREA = "textarea"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"


@dataclass
class DetectedElement:
    """A single interactive element detected on screen."""
    element_type: ElementType
    x: int              # Top-left X of bounding box (local canvas coords)
    y: int              # Top-left Y of bounding box
    w: int              # Width of bounding box
    h: int              # Height of bounding box
    cx: int = 0         # Center X (computed)
    cy: int = 0         # Center Y (computed)
    confidence: float = 1.0

    def __post_init__(self):
        self.cx = self.x + self.w // 2
        self.cy = self.y + self.h // 2


# ─── Template Generator ──────────────────────────────────────────

class TemplateGenerator:
    """
    Generates synthetic grayscale template images for radio buttons
    and checkboxes. Creates minimal 20×20 px reference images using
    OpenCV drawing primitives, so no external assets are needed.
    """

    TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

    @classmethod
    def ensure_templates(cls) -> tuple[str, str]:
        """
        Generate template files if they don't exist.
        
        Returns:
            Tuple of (radio_template_path, checkbox_template_path)
        """
        os.makedirs(cls.TEMPLATE_DIR, exist_ok=True)

        radio_path = os.path.join(cls.TEMPLATE_DIR, "template_radio.png")
        checkbox_path = os.path.join(cls.TEMPLATE_DIR, "template_checkbox.png")

        if not os.path.exists(radio_path):
            cls._generate_radio(radio_path)
            logger.info(f"Generated synthetic radio template: {radio_path}")

        if not os.path.exists(checkbox_path):
            cls._generate_checkbox(checkbox_path)
            logger.info(f"Generated synthetic checkbox template: {checkbox_path}")

        return radio_path, checkbox_path

    @classmethod
    def _generate_radio(cls, path: str, size: int = 20):
        """Generate a synthetic radio button: dark circle outline on white bg."""
        img = np.ones((size, size), dtype=np.uint8) * 255
        center = (size // 2, size // 2)
        radius = size // 2 - 2
        cv2.circle(img, center, radius, 60, thickness=2)
        # Use imencode/tofile to support Unicode paths on Windows
        cv2.imencode('.png', img)[1].tofile(path)

    @classmethod
    def _generate_checkbox(cls, path: str, size: int = 20):
        """Generate a synthetic checkbox: dark square outline on white bg."""
        img = np.ones((size, size), dtype=np.uint8) * 255
        margin = 2
        cv2.rectangle(img, (margin, margin), (size - margin - 1, size - margin - 1), 60, thickness=2)
        # Use imencode/tofile to support Unicode paths on Windows
        cv2.imencode('.png', img)[1].tofile(path)


# ─── Non-Maximum Suppression ─────────────────────────────────────

def non_maximum_suppression(
    detections: list[tuple[int, int, int, int, float]],
    radius: int = 10,
) -> list[tuple[int, int, int, int, float]]:
    """
    Simple distance-based NMS to filter overlapping template matches.
    
    For each detection, suppresses neighbors whose center is within
    `radius` pixels, keeping only the highest-confidence detection.
    
    Args:
        detections: List of (x, y, w, h, confidence) tuples.
        radius: Minimum distance (pixels) between detection centers.
        
    Returns:
        Filtered list of non-overlapping detections.
    """
    if not detections:
        return []

    # Sort by confidence descending
    sorted_dets = sorted(detections, key=lambda d: d[4], reverse=True)
    kept = []

    for det in sorted_dets:
        cx, cy = det[0] + det[2] // 2, det[1] + det[3] // 2
        is_suppressed = False

        for kept_det in kept:
            kcx = kept_det[0] + kept_det[2] // 2
            kcy = kept_det[1] + kept_det[3] // 2
            distance = ((cx - kcx) ** 2 + (cy - kcy) ** 2) ** 0.5
            if distance < radius:
                is_suppressed = True
                break

        if not is_suppressed:
            kept.append(det)

    return kept


# ─── Main Detector Class ─────────────────────────────────────────

class ElementDetector:
    """
    Detects interactive form elements on a screenshot using OpenCV.
    
    Two detection pipelines run in sequence:
    1. Contour-based detection for inputs, textareas, and selectboxes.
    2. Template matching for radio buttons and checkboxes.
    """

    def __init__(self):
        # Ensure template images exist (auto-generated if missing)
        self.radio_template_path, self.checkbox_template_path = (
            TemplateGenerator.ensure_templates()
        )

    def detect(self, image: np.ndarray) -> list[DetectedElement]:
        """
        Run the full detection pipeline on a BGR screenshot.
        
        Args:
            image: BGR numpy array from screen capture.
            
        Returns:
            List of DetectedElement instances found on screen.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        elements: list[DetectedElement] = []

        # Pipeline 1: Contour-based detection (inputs, textareas, selects)
        contour_elements = self._detect_contour_elements(gray)
        elements.extend(contour_elements)
        logger.info(f"Contour pipeline detected {len(contour_elements)} elements")

        # Pipeline 2: Template matching (radio buttons, checkboxes)
        radio_elements = self._detect_template_elements(
            gray, self.radio_template_path, ElementType.RADIO
        )
        checkbox_elements = self._detect_template_elements(
            gray, self.checkbox_template_path, ElementType.CHECKBOX
        )
        elements.extend(radio_elements)
        elements.extend(checkbox_elements)
        logger.info(
            f"Template pipeline detected {len(radio_elements)} radios, "
            f"{len(checkbox_elements)} checkboxes"
        )

        # Sort top-to-bottom, left-to-right for natural reading order
        elements.sort(key=lambda e: (e.y, e.x))

        logger.info(f"Total elements detected: {len(elements)}")
        return elements

    @staticmethod
    def draw_debug_image(
        image: np.ndarray,
        elements: list['DetectedElement'],
        output_path: str = "debug_vision.png",
    ) -> str:
        """
        Generate a visual debug image with annotated bounding boxes and
        center-point crosshairs for every detected element.
        
        Color coding:
        - RED    (0,0,255):   input / textarea / select (contour pipeline)
        - GREEN  (0,255,0):   radio / checkbox (template pipeline)
        - YELLOW (0,255,255): unknown / fallback
        
        Each element also gets:
        - A filled circle at (cx, cy) — the exact click target
        - A crosshair (±15px) at (cx, cy) for precise calibration
        - A label tag showing type + index
        
        Args:
            image: Original BGR screenshot.
            elements: List of DetectedElement instances.
            output_path: Where to save the annotated image.
            
        Returns:
            The absolute path of the saved debug image.
        """
        # Work on a copy so we don't mutate the original
        debug_img = image.copy()

        COLOR_MAP = {
            ElementType.INPUT: (0, 0, 255),       # Red
            ElementType.TEXTAREA: (0, 0, 255),     # Red
            ElementType.SELECT: (0, 0, 255),       # Red
            ElementType.RADIO: (0, 255, 0),        # Green
            ElementType.CHECKBOX: (0, 255, 0),     # Green
        }
        CROSSHAIR_SIZE = 15

        for i, el in enumerate(elements):
            color = COLOR_MAP.get(el.element_type, (0, 255, 255))

            # Bounding box
            cv2.rectangle(
                debug_img,
                (el.x, el.y),
                (el.x + el.w, el.y + el.h),
                color, 2
            )

            # Center dot (filled circle)
            cv2.circle(debug_img, (el.cx, el.cy), 5, color, -1)

            # Crosshair lines through center
            cv2.line(
                debug_img,
                (el.cx - CROSSHAIR_SIZE, el.cy),
                (el.cx + CROSSHAIR_SIZE, el.cy),
                color, 1
            )
            cv2.line(
                debug_img,
                (el.cx, el.cy - CROSSHAIR_SIZE),
                (el.cx, el.cy + CROSSHAIR_SIZE),
                color, 1
            )

            # Label tag: "[idx] type"
            label = f"[{i}] {el.element_type.value}"
            # Background rectangle for label readability
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(
                debug_img,
                (el.x, el.y - th - 8),
                (el.x + tw + 4, el.y),
                color, -1
            )
            cv2.putText(
                debug_img, label,
                (el.x + 2, el.y - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
                cv2.LINE_AA
            )

        # Save the debug image
        abs_path = os.path.abspath(output_path)
        cv2.imwrite(abs_path, debug_img)
        logger.info(f"Debug image saved: {abs_path}")
        return abs_path

    # ─── Pipeline 1: Contour Detection ───────────────────────────

    def _detect_contour_elements(self, gray: np.ndarray) -> list[DetectedElement]:
        """
        Detect rectangular form elements via edge detection + contour analysis.
        
        Steps:
        1. Gaussian blur to reduce noise
        2. Canny edge detection
        3. Find external contours
        4. Approximate polygons (approxPolyDP)
        5. Filter by vertex count (4 = rectangle), area, and aspect ratio
        6. Classify based on geometric properties
        """
        # Preprocessing
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, settings.CANNY_LOW, settings.CANNY_HIGH)

        # Dilate to close small gaps in edges
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dilated = cv2.dilate(edges, kernel, iterations=1)

        # Find contours
        contours, _ = cv2.findContours(
            dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        elements = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < settings.MIN_CONTOUR_AREA or area > settings.MAX_CONTOUR_AREA:
                continue

            # Approximate the polygon
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)

            # We want rectangles (4 vertices)
            if len(approx) != 4:
                continue

            x, y, w, h = cv2.boundingRect(approx)
            if h == 0:
                continue

            aspect_ratio = w / h

            # Classify based on geometric properties
            element_type = self._classify_rectangle(w, h, aspect_ratio)
            if element_type is not None:
                elements.append(DetectedElement(
                    element_type=element_type,
                    x=x, y=y, w=w, h=h,
                    confidence=0.85,
                ))

        return elements

    def _classify_rectangle(
        self, w: int, h: int, aspect_ratio: float
    ) -> Optional[ElementType]:
        """
        Classify a detected rectangle into a form element type
        based on its dimensions and aspect ratio.
        
        Returns:
            ElementType or None if the rectangle doesn't match any known form element.
        """
        # Textarea: medium aspect ratio + tall height
        if (settings.TEXTAREA_ASPECT_RATIO_MIN <= aspect_ratio <= settings.TEXTAREA_ASPECT_RATIO_MAX
                and h >= settings.TEXTAREA_MIN_HEIGHT):
            return ElementType.TEXTAREA

        # Input / Select: wide horizontal rectangle
        if aspect_ratio >= settings.INPUT_ASPECT_RATIO_MIN:
            # Dropdowns tend to be narrower/shorter than text inputs
            if h < 40 and w < 300:
                return ElementType.SELECT
            return ElementType.INPUT

        return None

    # ─── Pipeline 2: Template Matching ───────────────────────────

    def _detect_template_elements(
        self,
        gray: np.ndarray,
        template_path: str,
        element_type: ElementType,
    ) -> list[DetectedElement]:
        """
        Detect small UI elements (radio buttons, checkboxes) via template matching.
        
        Steps:
        1. Load grayscale template image
        2. Multi-scale template matching at 3 scales (0.8x, 1.0x, 1.2x)
        3. Threshold at configurable confidence level
        4. Non-Maximum Suppression to eliminate duplicate detections
        """
        if not os.path.exists(template_path):
            logger.warning(f"Template not found: {template_path}")
            return []

        # Use fromfile/imdecode to support Unicode paths on Windows
        img_array = np.fromfile(template_path, dtype=np.uint8)
        template = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
        if template is None:
            logger.warning(f"Failed to load template: {template_path}")
            return []

        th, tw = template.shape[:2]
        all_detections: list[tuple[int, int, int, int, float]] = []

        # Multi-scale matching for robustness across different zoom levels
        for scale in [0.8, 1.0, 1.2, 1.5]:
            scaled_w = max(1, int(tw * scale))
            scaled_h = max(1, int(th * scale))
            scaled_template = cv2.resize(template, (scaled_w, scaled_h))

            # Ensure the template is smaller than the image
            if scaled_h > gray.shape[0] or scaled_w > gray.shape[1]:
                continue

            result = cv2.matchTemplate(
                gray, scaled_template, cv2.TM_CCOEFF_NORMED
            )

            # Find locations above threshold
            locations = np.where(result >= settings.TEMPLATE_MATCH_THRESHOLD)
            for pt_y, pt_x in zip(*locations):
                confidence = float(result[pt_y, pt_x])
                all_detections.append((
                    int(pt_x), int(pt_y),
                    scaled_w, scaled_h,
                    confidence,
                ))

        # Apply Non-Maximum Suppression
        filtered = non_maximum_suppression(
            all_detections, radius=settings.NMS_RADIUS
        )

        return [
            DetectedElement(
                element_type=element_type,
                x=d[0], y=d[1], w=d[2], h=d[3],
                confidence=d[4],
            )
            for d in filtered
        ]
