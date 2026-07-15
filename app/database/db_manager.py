import sqlite3
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

# Garante o caminho absoluto para o banco SQLite local
db_file_path = Path(settings.VEGA_DB_PATH)
if not db_file_path.is_absolute():
    # Se for relativo, resolvemos a partir do diretório raiz do VEGA
    db_file_path = (settings.BASE_DIR / settings.VEGA_DB_PATH).resolve()

# Conexão SQLAlchemy
engine = create_engine(
    f"sqlite:///{db_file_path}",
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """Inicializa o banco de dados do VEGA executando o schema.sql se necessário."""
    logging.info(f"Conectando ao banco de dados VEGA em: {db_file_path}")
    
    # Certifica-se de que os diretórios pais do arquivo do banco de dados existem
    db_file_path.parent.mkdir(parents=True, exist_ok=True)
    
    schema_path = Path(__file__).parent / "schema.sql"
    if schema_path.exists():
        try:
            with sqlite3.connect(db_file_path) as conn:
                with open(schema_path, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
            logging.info("Tabelas do banco de dados VEGA inicializadas/verificadas com sucesso.")
        except Exception as e:
            logging.error(f"Erro ao inicializar o banco de dados via schema.sql: {e}")
            raise e
    else:
        logging.error(f"schema.sql não encontrado no caminho {schema_path}")
        raise FileNotFoundError(f"schema.sql não encontrado")

def get_db():
    """Dependency para injeção de sessão nos endpoints do FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
