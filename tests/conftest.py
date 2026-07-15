# tests/conftest.py
import sys
import os
from pathlib import Path
import pytest

# Adiciona o diretório raiz do VEGA ao sys.path
root_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(root_dir))

# Configura variáveis de ambiente exclusivas para a suíte de testes
os.environ["VEGA_DB_PATH"] = "vega_test.db"
os.environ["PORT"] = "8015"
os.environ["DEBUG"] = "true"

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Inicializa o banco de testes do VEGA e remove o arquivo residual no final."""
    db_file = Path("vega_test.db")
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass
            
    # Inicializa o banco do VEGA usando a função oficial
    from app.database.db_manager import init_db
    init_db()
    
    yield
    
    # Limpeza final
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass
