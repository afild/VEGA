import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from app.config import resolve_project_path, settings

# Garante o caminho absoluto para o banco SQLite local.
# Também aceita o formato legado "VEGA/vega_contracts.db".
db_file_path: Path = resolve_project_path(settings.VEGA_DB_PATH)

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
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


CONTRACT_ANALYSIS_COLUMNS = {
    "financial_currency": "TEXT",
    "analysis_status": "TEXT NOT NULL DEFAULT 'not_started'",
    "analysis_run_id": "TEXT",
    "last_successful_run_id": "TEXT",
    "analysis_error_code": "TEXT",
    "analysis_error": "TEXT",
    "analysis_started_at": "DATETIME",
    "analysis_completed_at": "DATETIME",
    "last_successful_analysis_at": "DATETIME",
    "analysis_revision": "INTEGER NOT NULL DEFAULT 0",
}

CLAUSE_AUDIT_COLUMNS = {
    "analysis_run_id": "TEXT",
    "extraction_method": "TEXT",
    "source_start": "INTEGER",
    "source_end": "INTEGER",
}


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Retorna as colunas existentes sem interpolar entrada externa."""
    if table_name not in {"contracts", "clauses"}:
        raise ValueError("Tabela de migração não autorizada.")
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _apply_schema_migrations(conn: sqlite3.Connection) -> None:
    """Atualiza bancos criados por versões anteriores sem apagar dados."""
    contract_columns = _table_columns(conn, "contracts")
    legacy_upgrade = "analysis_status" not in contract_columns

    for column_name, definition in CONTRACT_ANALYSIS_COLUMNS.items():
        if column_name not in contract_columns:
            conn.execute(
                f"ALTER TABLE contracts ADD COLUMN {column_name} {definition}"
            )

    clause_columns = _table_columns(conn, "clauses")
    for column_name, definition in CLAUSE_AUDIT_COLUMNS.items():
        if column_name not in clause_columns:
            conn.execute(f"ALTER TABLE clauses ADD COLUMN {column_name} {definition}")

    if legacy_upgrade:
        # Não é possível provar que resultados antigos passaram pelo pipeline
        # versionado. Eles permanecem visíveis, mas explicitamente não auditados.
        conn.execute(
            "UPDATE contracts SET analysis_status = 'legacy' "
            "WHERE analysis_status = 'not_started'"
        )

    # Este índice depende de colunas adicionadas acima e, portanto, não pode
    # ficar no schema inicial quando abrimos um banco legado.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contracts_analysis_status "
        "ON contracts(analysis_status, analysis_started_at)"
    )

    conn.execute("PRAGMA user_version = 1")


def _recover_interrupted_analyses(conn: sqlite3.Connection) -> None:
    """Fecha execuções voláteis perdidas em um encerramento do processo."""
    message = "A análise foi interrompida pelo encerramento do aplicativo. Reprocesse o contrato."
    conn.execute(
        """
        UPDATE analysis_runs
        SET status = 'failed',
            completed_at = CURRENT_TIMESTAMP,
            error_code = 'PROCESS_INTERRUPTED',
            error_message = :message
        WHERE status IN ('queued', 'processing')
        """,
        {"message": message},
    )
    recovered = conn.execute(
        """
        UPDATE contracts
        SET analysis_status = 'failed',
            analysis_error_code = 'PROCESS_INTERRUPTED',
            analysis_error = :message,
            analysis_completed_at = CURRENT_TIMESTAMP
        WHERE analysis_status IN ('queued', 'processing')
        """,
        {"message": message},
    ).rowcount
    if recovered:
        logging.warning(
            "Marcadas %s análises interrompidas para reprocessamento manual.",
            recovered,
        )

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
                conn.execute("PRAGMA foreign_keys=ON;")
                conn.execute("PRAGMA busy_timeout=5000;")
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                with open(schema_path, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
                conn.execute("BEGIN IMMEDIATE")
                _apply_schema_migrations(conn)
                _recover_interrupted_analyses(conn)
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
