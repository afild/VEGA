# run.py
import sys
import os
from pathlib import Path
import logging

# Adiciona o diretório atual ao path do Python para permitir importações absolutas de app.
current_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(current_dir))

# Carrega variáveis de ambiente antes de qualquer importação interna
env_file = current_dir / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

def check_dependencies():
    """Valida se as dependências fundamentais do VEGA estão instaladas."""
    required = ["fastapi", "uvicorn", "langchain", "langgraph", "llama_index", "fitz"]
    missing = []
    for pkg in required:
        try:
            if pkg == "fitz":
                __import__("fitz")  # PyMuPDF é importado como fitz
            elif pkg == "llama_index":
                __import__("llama_index")
            else:
                __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)
            
    if missing:
        print(f"❌ Dependências ausentes: {', '.join(missing)}")
        print("   Por favor execute: pip install -r requirements.txt")
        sys.exit(1)

def ensure_directories():
    """Garante que a estrutura de diretórios para uploads de PDFs exista."""
    storage_dir = current_dir / "app" / "data" / "storage" / "contracts"
    storage_dir.mkdir(parents=True, exist_ok=True)
    gitkeep_file = storage_dir / ".gitkeep"
    if not gitkeep_file.exists():
        with open(gitkeep_file, "w") as f:
            f.write("")
    print(f"✅ Diretório de armazenamento de contratos verificado: {storage_dir}")

def initialize_database():
    """Inicializa o banco SQLite do VEGA (vega_contracts.db)."""
    from app.database.db_manager import init_db
    init_db()
    print("✅ Banco de dados SQLite VEGA inicializado com sucesso.")

if __name__ == "__main__":
    check_dependencies()
    ensure_directories()
    initialize_database()

    port = int(os.environ.get("PORT", 8005))
    host = os.environ.get("HOST", "127.0.0.1")
    ai_mode = "LLM (Claude via LangChain)" if os.environ.get("ANTHROPIC_API_KEY") else "Offline Heuristic Fallback"

    print("=" * 65)
    print("   VEGA — Vendor & Contract Governance Agent")
    print("=" * 65)
    print(f"   AI Mode   : {ai_mode}")
    print(f"   Dashboard : http://{host}:{port}/static/index.html")
    print(f"   API Docs  : http://{host}:{port}/docs")
    print("=" * 65)

    import uvicorn
    # reload=False para produção local e consistência na inicialização única do banco
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
