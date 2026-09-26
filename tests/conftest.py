# tests/conftest.py
import sys
import os
import shutil
import tempfile
from pathlib import Path
import pytest

# Adiciona o diretório raiz do VEGA ao sys.path
root_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(root_dir))

# Configura variáveis de ambiente exclusivas para a suíte de testes
test_runtime_dir = Path(tempfile.mkdtemp(prefix="vega-tests-")).resolve()
os.environ["BASE_DIR"] = str(root_dir)
os.environ["VEGA_DB_PATH"] = str(test_runtime_dir / "vega_test.db")
os.environ["CONTRACTS_STORAGE_DIR"] = str(test_runtime_dir / "contracts")
os.environ["PORT"] = "8015"
os.environ["DEBUG"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["SLACK_WEBHOOK_URL"] = ""
os.environ["IMAP_SERVER"] = ""
os.environ["IMAP_USER"] = ""
os.environ["IMAP_PASSWORD"] = ""
os.environ["ALLOW_LLM_RAW_CONTRACT_TEXT"] = "false"
os.environ["CORS_ALLOWED_ORIGINS"] = ""
os.environ["ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Inicializa o banco de testes do VEGA e remove o arquivo residual no final."""
    # Inicializa o banco do VEGA usando a função oficial
    from app.database.db_manager import engine, init_db
    init_db()
    
    yield

    # Libera os handles do SQLite no Windows antes de remover o runtime isolado.
    engine.dispose()
    shutil.rmtree(test_runtime_dir, ignore_errors=True)
