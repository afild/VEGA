from pathlib import Path
from typing import Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Caminhos base
    BASE_DIR: Path = PROJECT_ROOT
    VEGA_DB_PATH: Path = Path("vega_contracts.db")
    CONTRACTS_STORAGE_DIR: Path = Path("app/data/storage/contracts")

    # Metadados da aplicação
    APP_VERSION: str = "0.3.0"

    # LLM (Claude via LangChain)
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-3-5-sonnet-20241022"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 4000

    # Servidor FastAPI
    HOST: str = "127.0.0.1"
    PORT: int = 8005
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Limites e fronteiras de segurança
    MAX_CONTRACT_FILE_SIZE_MB: int = Field(default=25, ge=1, le=250)
    MAX_DOCX_UNCOMPRESSED_SIZE_MB: int = Field(default=100, ge=1, le=1000)
    MAX_EXTRACTED_TEXT_CHARS: int = Field(default=1_000_000, ge=10_000, le=10_000_000)
    ALLOWED_HOSTS: str = "127.0.0.1,localhost"
    CORS_ALLOWED_ORIGINS: str = ""
    ALLOW_LLM_RAW_CONTRACT_TEXT: bool = False
    
    # Integrações V2
    IMAP_SERVER: str = ""
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    SLACK_WEBHOOK_URL: str = ""
    OFAC_API_KEY: str = ""

    # Integrações legadas/futuras presentes em alguns ambientes locais.
    # Mantidas opcionais para que um .env compartilhado não impeça o startup.
    AFIS_DB_PATH: str = ""
    APEX_DB_PATH: str = ""

settings = Settings()


def resolve_project_path(value: Union[str, Path]) -> Path:
    """Resolve caminhos relativos a partir da raiz real do projeto.

    Versões anteriores usavam o diretório pai como ``BASE_DIR`` e, por isso,
    gravavam caminhos relativos iniciados por ``VEGA/``. O tratamento abaixo
    mantém esses valores legados funcionais sem duplicar ``VEGA/VEGA``.
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()

    base_dir = settings.BASE_DIR.resolve()
    parts = path.parts
    if parts and parts[0].casefold() == base_dir.name.casefold():
        path = Path(*parts[1:]) if len(parts) > 1 else Path()

    return (base_dir / path).resolve()
