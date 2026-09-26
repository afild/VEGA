# run.py
import sys
from pathlib import Path
from importlib.util import find_spec

# Adiciona o diretório atual ao path do Python para permitir importações absolutas de app.
current_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(current_dir))

def check_dependencies():
    """Valida se as dependências fundamentais do VEGA estão instaladas."""
    required = {
        "fastapi": "FastAPI",
        "uvicorn": "Uvicorn",
        "sqlalchemy": "SQLAlchemy",
        "pydantic": "Pydantic",
        "pydantic_settings": "pydantic-settings",
        "langchain": "LangChain",
        "langchain_anthropic": "langchain-anthropic",
        "langgraph": "LangGraph",
        "llama_index": "LlamaIndex",
        "fitz": "PyMuPDF",
        "multipart": "python-multipart",
    }
    missing = [label for module, label in required.items() if find_spec(module) is None]
            
    if missing:
        print(f"❌ Dependências ausentes: {', '.join(missing)}")
        print("   Por favor execute: pip install -r requirements.txt")
        sys.exit(1)

def ensure_directories() -> Path:
    """Garante que a estrutura de diretórios para uploads de PDFs exista."""
    from app.utils.file_storage import ensure_contracts_storage_dir

    storage_dir = ensure_contracts_storage_dir()
    print(f"✅ Diretório de armazenamento de contratos verificado: {storage_dir}")
    return storage_dir

if __name__ == "__main__":
    check_dependencies()
    ensure_directories()

    from app.config import settings

    port = settings.PORT
    host = settings.HOST
    ai_mode = "LLM (Claude via LangChain)" if settings.ANTHROPIC_API_KEY else "Offline Heuristic Fallback"

    print("=" * 65)
    print("   VEGA — Vendor & Contract Governance Agent")
    print("=" * 65)
    print(f"   AI Mode   : {ai_mode}")
    print(f"   Dashboard : http://{host}:{port}/static/index.html")
    print(f"   API Docs  : http://{host}:{port}/docs")
    print("=" * 65)

    import uvicorn
    # O lifespan do FastAPI inicializa o banco uma única vez.
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
