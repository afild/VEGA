-- app/database/schema.sql

CREATE TABLE IF NOT EXISTS vendors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    category            TEXT,
    contact_email       TEXT,
    ofac_status         TEXT DEFAULT 'unknown',
    opencorporates_status TEXT DEFAULT 'unknown',
    risk_score          REAL DEFAULT 0.0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id           INTEGER REFERENCES vendors(id),
    title               TEXT NOT NULL,
    file_path           TEXT NOT NULL, -- caminho relativo em VEGA/app/data/storage/contracts/
    status              TEXT DEFAULT 'draft', -- ciclo de vida: draft|active|expired|terminated
    start_date          DATE,
    end_date            DATE,
    auto_renews         INTEGER, -- NULL=nao identificado, 0=false, 1=true
    renewal_notice_days INTEGER, -- NULL quando o documento nao informa
    financial_value     REAL,
    financial_currency  TEXT, -- USD|BRL; NULL quando nenhum valor foi identificado
    payment_frequency   TEXT, -- monthly|annual|one-time|unknown
    health_score        REAL, -- NULL ate uma analise valida ser concluida
    analysis_status     TEXT NOT NULL DEFAULT 'not_started',
    analysis_run_id     TEXT,
    last_successful_run_id TEXT,
    analysis_error_code TEXT,
    analysis_error      TEXT,
    analysis_started_at DATETIME,
    analysis_completed_at DATETIME,
    last_successful_analysis_at DATETIME,
    analysis_revision   INTEGER NOT NULL DEFAULT 0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id                  TEXT PRIMARY KEY,
    contract_id         INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    trigger_source      TEXT NOT NULL, -- upload|manual|system
    status              TEXT NOT NULL, -- queued|processing|completed|needs_review|failed|superseded
    started_at          DATETIME,
    completed_at        DATETIME,
    error_code          TEXT,
    error_message       TEXT,
    warnings_json       TEXT NOT NULL DEFAULT '[]',
    extracted_text_chars INTEGER,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clauses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id         INTEGER REFERENCES contracts(id),
    clause_type         TEXT NOT NULL, -- Ex: 'Indemnification', 'Termination', 'Pricing'
    original_text       TEXT NOT NULL,
    summary             TEXT,
    risk_level          TEXT DEFAULT 'low', -- low|medium|high
    risk_explanation    TEXT,
    analysis_run_id     TEXT REFERENCES analysis_runs(id),
    extraction_method   TEXT,
    source_start        INTEGER,
    source_end          INTEGER,
    extracted_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id         INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    analysis_run_id     TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    field_name          TEXT NOT NULL,
    normalized_value    TEXT,
    source_text         TEXT NOT NULL,
    source_start        INTEGER,
    source_end          INTEGER,
    extraction_method   TEXT NOT NULL,
    confidence          REAL,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id         INTEGER REFERENCES contracts(id),
    alert_type          TEXT NOT NULL, -- renewal_90d|renewal_30d|expiration
    trigger_date        DATE NOT NULL,
    is_resolved         INTEGER DEFAULT 0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS negotiation_intel (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id         INTEGER REFERENCES contracts(id),
    benchmark_type      TEXT NOT NULL,
    market_rate         TEXT,
    suggestion          TEXT NOT NULL,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS playbooks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    clause_type         TEXT NOT NULL,
    desired_language    TEXT NOT NULL,
    fallback_language   TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vendors_name_nocase
    ON vendors(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_contracts_vendor_id
    ON contracts(vendor_id);
CREATE INDEX IF NOT EXISTS idx_contracts_status_created_at
    ON contracts(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contracts_end_date
    ON contracts(end_date);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_contract_created
    ON analysis_runs(contract_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clauses_contract_id
    ON clauses(contract_id);
CREATE INDEX IF NOT EXISTS idx_analysis_evidence_contract_run
    ON analysis_evidence(contract_id, analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_alerts_contract_resolution_date
    ON alerts(contract_id, is_resolved, trigger_date);
CREATE INDEX IF NOT EXISTS idx_negotiation_intel_contract_id
    ON negotiation_intel(contract_id);
