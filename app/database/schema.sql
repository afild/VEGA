-- app/database/schema.sql

CREATE TABLE IF NOT EXISTS vendors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    category            TEXT,
    contact_email       TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id           INTEGER REFERENCES vendors(id),
    title               TEXT NOT NULL,
    file_path           TEXT NOT NULL, -- caminho relativo em VEGA/app/data/storage/contracts/
    status              TEXT DEFAULT 'draft', -- draft|active|expired|terminated
    start_date          DATE,
    end_date            DATE,
    auto_renews         INTEGER DEFAULT 0, -- 0=false, 1=true
    renewal_notice_days INTEGER DEFAULT 30, -- dias de aviso prévio
    financial_value     REAL,
    payment_frequency   TEXT, -- monthly|annual|one-time
    health_score        REAL DEFAULT 100.0, -- calculado pelo Risk Detector
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
    extracted_at        DATETIME DEFAULT CURRENT_TIMESTAMP
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
