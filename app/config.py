from pydantic_settings import BaseSettings
from pathlib import Path
import os

class Settings(BaseSettings):
    # Caminhos base
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    VEGA_DB_PATH: str = "vega_contracts.db"
    CONTRACTS_STORAGE_DIR: str = "VEGA/app/data/storage/contracts"

    # LLM (Claude via LangChain)
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-3-5-sonnet-20241022"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 4000

    # Servidor FastAPI
    HOST: str = "127.0.0.1"
    PORT: int = 8005
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    # Integrações V2
    IMAP_SERVER: str = ""
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    SLACK_WEBHOOK_URL: str = ""
    OFAC_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# Sobrescreve caminhos com base no ambiente de execução se fornecidos pelo SO
if os.environ.get("VEGA_DB_PATH"):
    settings.VEGA_DB_PATH = os.environ.get("VEGA_DB_PATH")
if os.environ.get("PORT"):
    settings.PORT = int(os.environ.get("PORT"))
if os.environ.get("ANTHROPIC_API_KEY"):
    settings.ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
