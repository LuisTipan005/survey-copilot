"""
Vision Agent — OCR Engine Module

Extracts text from screenshots using Pytesseract and builds a spatial
mapping between detected text labels and interactive form elements.

The spatial heuristic groups text blocks that sit directly above or
to the left of each element's bounding box, treating them as the
question/label context for that form field.
"""

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytesseract

from vision_agent.config import settings
from vision_agent.element_detector import DetectedElement, ElementType

logger = logging.getLogger(__name__)

# Configure Tesseract binary path
pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


# ─── Data Models ──────────────────────────────────────────────────

@dataclass
class OCRWord:
    """A single word extracted by Tesseract with its position."""
    text: str
    left: int
    top: int
    width: int
    height: int
    block_num: int
    par_num: int
    line_num: int
    confidence: float


@dataclass
class FormField:
    """
    A form element paired with its extracted label/question text.
    
    This is the primary data structure passed to the LLM for evaluation.
    """
    index: int                          # Sequential index for LLM reference
    element: DetectedElement            # The detected interactive element
    label_text: str                     # Extracted question/label context
    nearby_option_texts: list[str] = field(default_factory=list)  # For radio/checkbox groups


# ─── OCR Engine Class ────────────────────────────────────────────

class OCREngine:
    """
    Extracts structured text from screenshots and maps labels
    to detected form elements using spatial proximity heuristics.
    """

    def extract_words(self, image: np.ndarray) -> list[OCRWord]:
        """
        Run Tesseract OCR on the image and extract structured word data.
        
        Args:
            image: BGR numpy array.
            
        Returns:
            List of OCRWord instances with position and block metadata.
        """
        # Convert to RGB for Tesseract
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Apply light preprocessing for better OCR accuracy
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Adaptive threshold for varied backgrounds
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        try:
            data = pytesseract.image_to_data(
                processed, output_type=pytesseract.Output.DICT,
                config="--psm 6"  # Assume uniform block of text
            )
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {e}")
            return []

        words: list[OCRWord] = []
        n_items = len(data["text"])

        for i in range(n_items):
            text = str(data["text"][i]).strip()
            conf = int(data["conf"][i])

            # Filter empty text and low-confidence results
            if not text or conf < 30:
                continue

            words.append(OCRWord(
                text=text,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                block_num=int(data["block_num"][i]),
                par_num=int(data["par_num"][i]),
                line_num=int(data["line_num"][i]),
                confidence=float(conf),
            ))

        logger.info(f"OCR extracted {len(words)} words from screenshot")
        return words

    def extract_and_map(
        self,
        image: np.ndarray,
        elements: list[DetectedElement],
    ) -> list[FormField]:
        """
        Extract text from the image and map labels to detected elements.
        
        The spatial heuristic works as follows:
        - For each element, search for text blocks directly ABOVE it
          (within LABEL_SEARCH_ABOVE_PX pixels) or to the LEFT
          (within LABEL_SEARCH_LEFT_PX pixels).
        - Group consecutive words into lines, then lines into label text.
        - For radio/checkbox elements, also gather text to the RIGHT
          as option labels.
        
        Args:
            image: BGR numpy array (same as used for element detection).
            elements: List of DetectedElement from ElementDetector.
            
        Returns:
            List of FormField instances, one per element, with mapped labels.
        """
        words = self.extract_words(image)

        if not words:
            logger.warning("No OCR words extracted — returning elements without labels")
            return [
                FormField(index=i, element=el, label_text="[No text detected]")
                for i, el in enumerate(elements)
            ]

        # Pre-group words into lines: (block, par, line) → sorted words
        lines = self._group_words_into_lines(words)

        form_fields: list[FormField] = []

        for i, element in enumerate(elements):
            # Find label text above or to the left
            label = self._find_label_for_element(element, lines, words)

            # For radio/checkbox: find option text to the right
            option_texts: list[str] = []
            if element.element_type in (ElementType.RADIO, ElementType.CHECKBOX):
                option_texts = self._find_option_text_right(element, words)

            form_fields.append(FormField(
                index=i,
                element=element,
                label_text=label,
                nearby_option_texts=option_texts,
            ))

        logger.info(f"Mapped labels to {len(form_fields)} form fields")
        return form_fields

    # ─── Internal Heuristics ─────────────────────────────────────

    def _group_words_into_lines(
        self, words: list[OCRWord]
    ) -> dict[tuple[int, int, int], list[OCRWord]]:
        """Group OCR words into lines using block/paragraph/line numbers."""
        lines: dict[tuple[int, int, int], list[OCRWord]] = {}
        for w in words:
            key = (w.block_num, w.par_num, w.line_num)
            lines.setdefault(key, []).append(w)
        # Sort words within each line by X position (left to right)
        for key in lines:
            lines[key].sort(key=lambda w: w.left)
        return lines

    def _find_label_for_element(
        self,
        element: DetectedElement,
        lines: dict[tuple[int, int, int], list[OCRWord]],
        all_words: list[OCRWord],
    ) -> str:
        """
        Find the label/question text associated with a form element.
        
        Spatial heuristic:
        1. Collect all OCR lines whose Y-center is ABOVE the element
           (within LABEL_SEARCH_ABOVE_PX) and whose X range overlaps
           with the element's horizontal extent.
        2. Also collect lines to the LEFT (within LABEL_SEARCH_LEFT_PX)
           that are vertically aligned with the element.
        3. Concatenate matching lines into the label string.
        """
        el_top = element.y
        el_left = element.x
        el_right = element.x + element.w
        el_cy = element.cy

        matching_lines: list[tuple[int, str]] = []  # (y_position, text)

        for line_key, line_words in lines.items():
            if not line_words:
                continue

            # Compute line bounding box
            line_left = min(w.left for w in line_words)
            line_right = max(w.left + w.width for w in line_words)
            line_top = min(w.top for w in line_words)
            line_bottom = max(w.top + w.height for w in line_words)
            line_cy = (line_top + line_bottom) // 2

            line_text = " ".join(w.text for w in line_words)

            # Strategy 1: Text ABOVE the element
            vertical_distance = el_top - line_bottom
            horizontal_overlap = (
                min(el_right, line_right) - max(el_left, line_left)
            )
            if (0 <= vertical_distance <= settings.LABEL_SEARCH_ABOVE_PX
                    and horizontal_overlap > 0):
                matching_lines.append((line_top, line_text))
                continue

            # Strategy 2: Text to the LEFT of the element (vertically aligned)
            horizontal_distance = el_left - line_right
            vertical_alignment = abs(line_cy - el_cy)
            if (0 <= horizontal_distance <= settings.LABEL_SEARCH_LEFT_PX
                    and vertical_alignment < element.h):
                matching_lines.append((line_top, line_text))
                continue

        if not matching_lines:
            return "[No label detected]"

        # Sort by Y position (top to bottom) and join
        matching_lines.sort(key=lambda t: t[0])
        return " ".join(text for _, text in matching_lines)

    def _find_option_text_right(
        self,
        element: DetectedElement,
        words: list[OCRWord],
    ) -> list[str]:
        """
        For radio/checkbox elements, find option label text immediately
        to the right of the element.
        
        Looks for words whose left edge is within 150px to the right
        and whose vertical center is aligned with the element.
        """
        el_right = element.x + element.w
        el_cy = element.cy
        max_distance_right = 150

        option_words: list[OCRWord] = []
        for w in words:
            horizontal_distance = w.left - el_right
            vertical_alignment = abs((w.top + w.height // 2) - el_cy)

            if (0 <= horizontal_distance <= max_distance_right
                    and vertical_alignment < element.h * 0.8):
                option_words.append(w)

        if not option_words:
            return []

        option_words.sort(key=lambda w: w.left)
        return [" ".join(w.text for w in option_words)]
