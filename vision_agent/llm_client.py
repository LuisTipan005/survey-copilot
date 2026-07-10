"""
Vision Agent — LLM Client Module

Async OpenRouter integration using the OpenAI SDK syntax.
Evaluates detected form fields by sending structured text prompts
to a cloud LLM and parsing JSON-enforced action responses.
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from openai import AsyncOpenAI

from vision_agent.config import settings
from vision_agent.ocr_engine import FormField
from vision_agent.element_detector import ElementType

logger = logging.getLogger(__name__)


# ─── Action Data Models ──────────────────────────────────────────

class ActionType(str, Enum):
    """Types of automation actions the LLM can request."""
    CLICK = "click"
    WRITE = "write"


@dataclass
class Action:
    """A single automation action to execute on screen."""
    action_type: ActionType
    target_index: int           # Index into the FormField list
    text_payload: str = ""      # Text to type (for WRITE actions)
    target_text_anchor: str = ""  # Human-readable target description
    element_type: str = ""      # The original element type for execution profiling


# ─── LLM Client Class ────────────────────────────────────────────

class VisionLLMClient:
    """
    Async OpenRouter client for evaluating screen-extracted form data.
    
    Uses the OpenAI SDK pointed at https://openrouter.ai/api/v1
    with lazy client initialization and JSON-enforced structured outputs.
    """

    SYSTEM_PROMPT = (
        "You are an intelligent quiz-solving assistant. You will receive a structured "
        "description of a web form extracted from a screen screenshot via OCR. Each form "
        "field has an index, type, label/question text, and available options.\n\n"
        "Your task is to analyze the questions and provide the correct answers.\n\n"
        "CRITICAL RULES:\n"
        "1. Respond ONLY with a valid JSON object. No intro text, no markdown.\n"
        "2. The JSON must have an 'actions' array.\n"
        "3. Each action must have: 'type' ('click' or 'write'), 'target_index' (the field index), "
        "and optionally 'text_payload' (for write actions) or 'target_text_anchor' (human-readable label).\n"
        "4. Include 'element_type' matching the original field type.\n"
        "5. For radio/checkbox questions, use 'click' action type.\n"
        "6. For text input/textarea questions, use 'write' action type with the answer in 'text_payload'.\n"
        "7. Always answer in Spanish unless the question is clearly in English.\n"
        "8. Always select at least one option for choice questions.\n\n"
        "Response schema:\n"
        '{"actions": [{"type": "click", "target_index": 0, "target_text_anchor": "Option B", '
        '"element_type": "radio"}, {"type": "write", "target_index": 2, '
        '"text_payload": "Analytical response text.", "element_type": "input"}]}'
    )

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        """Lazy-initialize the AsyncOpenAI client on first use."""
        if self._client is None:
            if not settings.OPENROUTER_API_KEY:
                raise ValueError(
                    "OPENROUTER_API_KEY is not set. "
                    "Please configure it in the backend/.env file."
                )
            self._client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.OPENROUTER_API_KEY,
                default_headers={
                    "HTTP-Referer": settings.APP_URL,
                    "X-Title": settings.PROJECT_NAME,
                },
            )
        return self._client

    async def evaluate(self, form_fields: list[FormField]) -> list[Action]:
        """
        Send extracted form field data to the LLM and parse the response
        into a list of executable actions.
        
        Args:
            form_fields: List of FormField instances from OCREngine.
            
        Returns:
            List of Action instances to execute on screen.
        """
        if not form_fields:
            logger.warning("No form fields to evaluate")
            return []

        # Build the structured text prompt
        prompt = self._build_prompt(form_fields)
        logger.info(f"Sending {len(form_fields)} form fields to LLM for evaluation")

        try:
            client = self._get_client()
            completion = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=settings.DEFAULT_TEMPERATURE,
                response_format={"type": "json_object"},
            )

            raw_response = completion.choices[0].message.content
            logger.info(f"LLM response received ({len(raw_response)} chars)")

            return self._parse_response(raw_response, form_fields)

        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return []

    def _build_prompt(self, form_fields: list[FormField]) -> str:
        """
        Build a structured text prompt listing all detected form fields.
        
        Format:
            DETECTED FORM FIELDS:
            [0] type=radio | label="What is X?" | options: ["Option A", "Option B"]
            [1] type=input | label="Your name:"
            ...
        """
        lines = ["DETECTED FORM FIELDS:\n"]

        for field in form_fields:
            el = field.element
            line = (
                f"[{field.index}] type={el.element_type.value} | "
                f"label=\"{field.label_text}\""
            )

            if field.nearby_option_texts:
                options_str = ", ".join(f'"{opt}"' for opt in field.nearby_option_texts)
                line += f" | options: [{options_str}]"

            lines.append(line)

        lines.append(
            "\nAnalyze each field and provide the correct answer actions "
            "as a JSON object with an 'actions' array."
        )

        return "\n".join(lines)

    def _parse_response(
        self, raw_response: str, form_fields: list[FormField]
    ) -> list[Action]:
        """
        Parse the LLM's JSON response into a list of Action objects.
        
        Validates target indices against the form field list to prevent
        out-of-bounds references.
        """
        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            logger.error(f"Raw response: {raw_response[:500]}")
            return []

        actions_raw = data.get("actions", [])
        if not isinstance(actions_raw, list):
            logger.error(f"'actions' is not a list: {type(actions_raw)}")
            return []

        actions: list[Action] = []
        for item in actions_raw:
            if not isinstance(item, dict):
                logger.warning(f"Skipping malformed action (not an object): {item}")
                continue

            try:
                action_type = ActionType(item.get("type", "click"))
                target_index = int(item.get("target_index", -1))

                # Validate target index
                if target_index < 0 or target_index >= len(form_fields):
                    logger.warning(
                        f"Skipping action with invalid target_index={target_index} "
                        f"(valid range: 0–{len(form_fields) - 1})"
                    )
                    continue

                actions.append(Action(
                    action_type=action_type,
                    target_index=target_index,
                    text_payload=str(item.get("text_payload", "")),
                    target_text_anchor=str(item.get("target_text_anchor", "")),
                    element_type=str(item.get("element_type", "")),
                ))

            except (ValueError, KeyError, AttributeError) as e:
                logger.warning(f"Skipping malformed action: {item} — {e}")
                continue

        logger.info(f"Parsed {len(actions)} valid actions from LLM response")
        return actions
