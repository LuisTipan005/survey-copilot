from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Configuration
    PROJECT_NAME: str = "Survey Copilot API"
    VERSION: str = "0.1.0"
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY: str = ""  # Required — set in .env
    LLM_MODEL: str = "meta-llama/llama-3.1-70b-instruct"
    APP_URL: str = "http://localhost:8000"
    
    # LLM Parameters
    DEFAULT_TEMPERATURE: float = 0.1
    
    class Config:
        env_file = ".env"

settings = Settings()