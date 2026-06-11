import logging
import httpx
from typing import Optional, Dict, Any
from app.config import settings

# Configure basic logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OllamaService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        # 60 seconds timeout for generation, 5 seconds for connection 
        self.timeout = httpx.Timeout(60.0, connect=5.0)

    async def check_health(self) -> bool:
        """
        Verifies if the local Ollama server is running and accessible.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except httpx.RequestError as e:
            logger.error(f"Error connecting to Ollama: {e}")
            return False
        
    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        [Fase 2] Genera embeddings vectoriales usando nomic-embed-text.
        """
        url = f"{self.base_url}/api/embed"
        embeddings = []
        try:
            # 120 segundos de timeout, los PDFs grandes toman tiempo
            async with httpx.AsyncClient(timeout=120.0) as client:
                for text in texts:
                    # Usamos nomic-embed-text por defecto para los embeddings
                    payload = {"model": "nomic-embed-text", "input": text}
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Extraer el vector de la respuesta
                    if "embeddings" in data and len(data["embeddings"]) > 0:
                        embeddings.append(data["embeddings"][0])
            return embeddings
        except Exception as e:
            logger.error(f"Error generando embeddings en Ollama: {e}")
            return []

    async def generate_response(
        self, 
        prompt: str, 
        system_prompt: str, 
        temperature: Optional[float] = None,
        format_json: bool = False
    ) -> Optional[str]:
        """
        Sends a prompt to the Ollama /api/chat endpoint.
        
        Args:
            prompt: The user's input/question.
            system_prompt: The context/persona definition.
            temperature: Creativity level (0.0 to 1.0).
            format_json: If True, forces the model to output a valid JSON.
            
        Returns:
            The generated text string, or None if an error occurred.
        """
        url = f"{self.base_url}/api/chat"
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": False,  # Disabled for MVP; can be enabled in Phase 4
            "options": {
                "temperature": temperature if temperature is not None else settings.DEFAULT_TEMPERATURE
            }
        }

        # Crucial for returning predictable structures (like selected checkbox indexes)
        if format_json:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"Sending request to Ollama ({self.model})...")
                response = await client.post(url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                return data.get("message", {}).get("content", "")
                
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Ollama: {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Ollama: {e}")
            return None

# Export a single instance to be used across the routers (Singleton-like pattern)
ollama_service = OllamaService()