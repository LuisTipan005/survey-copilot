from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Configuration
    PROJECT_NAME: str = "Survey Copilot API"
    VERSION: str = "0.1.0"
    
    # Ollama Configuration
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    
    # LLM Parameters
    DEFAULT_TEMPERATURE: float = 0.3
    
    class Config:
        env_file = ".env"

settings = Settings()