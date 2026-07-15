import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from app.config import settings

# Garante o caminho absoluto para o banco SQLite local
db_file_path: Path = Path(settings.VEGA_DB_PATH)
if not db_file_path.is_absolute():
    # Se for relativo, resolvemos a partir do diretório raiz do VEGA
    db_file_path = (settings.BASE_DIR / settings.VEGA_DB_PATH).resolve()

# Conexão SQLAlchemy
engine = create_engine(
    f"sqlite:///{db_file_path}",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry) -> None:
    """Configura PRAGMAs do SQLite na conexão para melhorar concorrência.

    Args:
        dbapi_connection (DBAPIConnection): Conexão DBAPI crua do SQLite.
        connection_record (ConnectionPoolEntry): Registro do pool de conexões.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db() -> None:
    """Inicializa o banco de dados do VEGA executando o schema.sql se necessário.

    Cria as tabelas e a estrutura caso o arquivo .sql exista no mesmo diretório.

    Raises:
        FileNotFoundError: Se o arquivo schema.sql não for encontrado.
        sqlite3.Error: Em caso de falha na execução do script SQL.
    """
    logging.info(f"Conectando ao banco de dados VEGA em: {db_file_path}")
    
    # Certifica-se de que os diretórios pais do arquivo do banco de dados existem
    db_file_path.parent.mkdir(parents=True, exist_ok=True)
    
    schema_path: Path = Path(__file__).parent / "schema.sql"
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
        raise FileNotFoundError("schema.sql não encontrado")

def get_db() -> Generator[Session, None, None]:
    """Dependency Provider para injeção de sessão nos endpoints do FastAPI.

    Yields:
        Session: Sessão ativa do SQLAlchemy.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context Manager seguro para gerenciar sessões do banco de dados fora do FastAPI.

    Garante o fechamento apropriado da conexão para evitar vazamento de sessões (session leaks).

    Yields:
        Session: Sessão ativa do SQLAlchemy.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
