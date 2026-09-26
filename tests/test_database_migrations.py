import sqlite3
from pathlib import Path

from app.database.db_manager import _apply_schema_migrations, _recover_interrupted_analyses


def test_legacy_database_gains_analysis_tracking_without_losing_contracts():
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(
            """
            CREATE TABLE contracts (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'draft'
            );
            CREATE TABLE clauses (
                id INTEGER PRIMARY KEY,
                contract_id INTEGER,
                original_text TEXT
            );
            INSERT INTO contracts (id, title, status)
            VALUES (1, 'Contrato legado', 'active');
            """
        )

        _apply_schema_migrations(connection)

        contract_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(contracts)")
        }
        clause_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(clauses)")
        }
        migrated = connection.execute(
            "SELECT title, status, analysis_status, analysis_revision "
            "FROM contracts WHERE id = 1"
        ).fetchone()
    finally:
        connection.close()

    assert {
        "analysis_status",
        "analysis_run_id",
        "last_successful_run_id",
        "analysis_revision",
    }.issubset(contract_columns)
    assert {"analysis_run_id", "extraction_method", "source_start", "source_end"}.issubset(
        clause_columns
    )
    assert migrated == ("Contrato legado", "active", "legacy", 0)


def test_current_schema_script_can_open_a_complete_legacy_database():
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(
            """
            CREATE TABLE vendors (
                id INTEGER PRIMARY KEY, name TEXT, category TEXT,
                contact_email TEXT, ofac_status TEXT,
                opencorporates_status TEXT, risk_score REAL, created_at DATETIME
            );
            CREATE TABLE contracts (
                id INTEGER PRIMARY KEY, vendor_id INTEGER, title TEXT,
                file_path TEXT, status TEXT, start_date DATE, end_date DATE,
                auto_renews INTEGER, renewal_notice_days INTEGER,
                financial_value REAL, payment_frequency TEXT,
                health_score REAL, created_at DATETIME
            );
            CREATE TABLE clauses (
                id INTEGER PRIMARY KEY, contract_id INTEGER, clause_type TEXT,
                original_text TEXT, summary TEXT, risk_level TEXT,
                risk_explanation TEXT, extracted_at DATETIME
            );
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY, contract_id INTEGER, alert_type TEXT,
                trigger_date DATE, is_resolved INTEGER, created_at DATETIME
            );
            CREATE TABLE negotiation_intel (
                id INTEGER PRIMARY KEY, contract_id INTEGER,
                benchmark_type TEXT, market_rate TEXT, suggestion TEXT,
                created_at DATETIME
            );
            CREATE TABLE playbooks (
                id INTEGER PRIMARY KEY, clause_type TEXT,
                desired_language TEXT, fallback_language TEXT,
                created_at DATETIME
            );
            INSERT INTO contracts (
                id, title, file_path, status, health_score
            ) VALUES (7, 'Antes da migração', 'legacy.pdf', 'active', 82);
            """
        )
        schema_path = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        _apply_schema_migrations(connection)

        migrated = connection.execute(
            "SELECT title, health_score, analysis_status FROM contracts WHERE id = 7"
        ).fetchone()
        index_names = {
            row[1] for row in connection.execute("PRAGMA index_list(contracts)")
        }
    finally:
        connection.close()

    assert migrated == ("Antes da migração", 82.0, "legacy")
    assert "idx_contracts_analysis_status" in index_names


def test_startup_recovers_interrupted_runs_without_erasing_valid_data():
    connection = sqlite3.connect(":memory:")
    try:
        schema = Path(__file__).resolve().parents[1] / "app/database/schema.sql"
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO contracts (id, title, file_path, analysis_status, health_score, analysis_revision) "
            "VALUES (1, 'Interrupted', 'test.pdf', 'processing', 75, 1)"
        )
        connection.execute(
            "INSERT INTO analysis_runs (id, contract_id, trigger_source, status) "
            "VALUES ('run-1', 1, 'manual', 'processing')"
        )
        _recover_interrupted_analyses(connection)
        assert connection.execute(
            "SELECT analysis_status, health_score, analysis_revision FROM contracts"
        ).fetchone() == ("failed", 75.0, 1)
        assert connection.execute(
            "SELECT status, error_code FROM analysis_runs"
        ).fetchone() == ("failed", "PROCESS_INTERRUPTED")
    finally:
        connection.close()
