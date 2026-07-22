import re
import logging
from typing import Optional
from openai import AsyncOpenAI
from app.config import settings

# Configure basic logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMService:
    """
    Async LLM client backed by OpenRouter (OpenAI-compatible API).
    
    Replaces the old OllamaService. Uses the `openai` SDK pointed at
    https://openrouter.ai/api/v1 with the required HTTP-Referer and
    X-Title headers.
    """

    def __init__(self):
        self.model = settings.LLM_MODEL
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        """Lazy-initialize the AsyncOpenAI client on first use."""
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.OPENROUTER_API_KEY,
                default_headers={
                    "HTTP-Referer": settings.APP_URL,
                    "X-Title": settings.PROJECT_NAME,
                },
            )
        return self._client

    async def check_health(self) -> bool:
        """
        Validates API connectivity by listing available models.
        Returns True if the OpenRouter API is reachable.
        """
        try:
            # Lightweight call — just fetches the first model to confirm connectivity
            client = self._get_client()
            models = await client.models.list()
            return bool(models.data)
        except Exception as e:
            logger.error(f"Error connecting to OpenRouter: {e}")
            return False

    async def generate_response(
        self,
        prompt: str,
        system_prompt: str,
        temperature: Optional[float] = None,
        require_json: bool = False,
        image_base64: Optional[str] = None,
    ) -> Optional[str]:
        """
        Sends a prompt to OpenRouter via the OpenAI-compatible chat completions API.
        
        Args:
            prompt: The user's input/question.
            system_prompt: The context/persona definition.
            temperature: Creativity level (0.0 to 1.0). Defaults to settings.DEFAULT_TEMPERATURE.
            require_json: If True, passes response_format={"type": "json_object"}
                          to enforce native JSON structured output from OpenRouter.
            image_base64: Optional Base64 data URL (or absolute URL) of an image
                          to include as a vision input. When provided, the request
                          is formatted using the OpenAI multimodal content spec.
                          Falls back silently to text-only if value is empty.
            
        Returns:
            The generated text string, or None if an error occurred.
        """
        # Build the user message content.
        # If a valid image is present, use the multimodal vision array format.
        # Otherwise, fall back to the standard plain-text format.
        user_content: object
        if image_base64 and isinstance(image_base64, str) and len(image_base64) > 10:
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_base64}},
            ]
            logger.info("Multimodal request: image payload included (%d chars).", len(image_base64))
        else:
            # Standard text-only request (no image, or image extraction failed)
            user_content = prompt

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.DEFAULT_TEMPERATURE,
        }

        # Leverage OpenRouter's native structured outputs
        if require_json:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            logger.info(f"Sending request to OpenRouter ({self.model})...")
            client = self._get_client()
            completion = await client.chat.completions.create(**kwargs)
            content = completion.choices[0].message.content
            return self._strip_markdown_fences(content)

        except Exception as e:
            logger.error(f"Error from OpenRouter: {e}")
            return None

    @staticmethod
    def _strip_markdown_fences(text: str | None) -> str | None:
        """
        Remove Markdown code-block wrappers that some models emit even when
        JSON output is explicitly requested.

        Handles all of these variants:
            ```json\n{...}\n```
            ```\n{...}\n```
            ```json{...}```   (no newline after opening fence)

        Returns the stripped text, or None / the original string unchanged
        when there is nothing to strip.
        """
        if not text:
            return text
        # Match an optional opening fence (```json or ```) and its closing fence
        stripped = re.sub(
            r'^```(?:json)?\s*',   # opening fence + optional language tag
            '',
            text.strip(),
            flags=re.IGNORECASE,
        )
        stripped = re.sub(
            r'\s*```$',            # closing fence at the very end
            '',
            stripped,
            flags=re.IGNORECASE,
        )
        cleaned = stripped.strip()
        if cleaned != text.strip():
            logger.debug("_strip_markdown_fences: removed code-fence wrappers from LLM response.")
        return cleaned


# Export a single instance to be used across the services (Singleton-like pattern)
llm_service = LLMService()
