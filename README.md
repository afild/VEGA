<div align="center">
  <picture>
    <img src="assets/readme/hero.svg" width="100%" alt="VEGA - Vendor & Contract Governance Agent" />
  </picture>
</div>

**An open-source vendor and contract governance agent for SMEs.**

VEGA ingests PDF and DOCX contracts, extracts critical clauses (termination, auto-renewal, liability caps), computes a contract health score, maps financial exposure, and triggers deadline alerts 90, 60, and 30 days before critical dates. The analysis pipeline supports a local offline mode, with an optional and explicitly controlled Claude integration. Each execution has an auditable state and never turns an ingestion failure into a healthy contract.

---

## Why it is different

**Anti-hallucination architecture**
Every clause stored in the database includes the `original_text` field — a contiguous, verbatim slice from the source — plus source offsets and extraction method. Financial values, currencies, dates, renewal state, and notice periods not found unambiguously in the document are stored as `NULL`, never filled with optimistic defaults. Their exact supporting text is retained as field-level evidence. Date extraction is driven via contextual regex, not LLM.

**Reliable, versioned analysis**
Contract lifecycle (`draft`, `active`, `expired`, `terminated`) is separate from analysis state (`queued`, `processing`, `completed`, `needs_review`, `failed`). Reanalysis is single-flight per contract, successful results are replaced transactionally, and a failed reanalysis preserves the last valid clauses, score, dates, alerts, and financial data. Interrupted in-process jobs are marked failed on the next startup instead of remaining silently stuck.

**Local-first document processing**
By default, PDF parsing, clause extraction, and risk scoring happen on your machine. When a Claude key is configured, structured clause data can be used for negotiation narratives and Q&A. Full raw-document excerpts remain blocked unless `ALLOW_LLM_RAW_CONTRACT_TEXT=true` is explicitly configured.

**Zero-server dependency**
Uses SQLite. The full governance pipeline starts simply with `python run.py`.

---

## How it works

<picture>
  <img src="docs/images/layers.png" width="100%" alt="VEGA Three-Layer Architecture" />
</picture>

### 1. Document Ingestion
Parses PDF/DOCX contracts using PyMuPDF and LlamaIndex. Empty, scanned, or truncated documents are routed to `needs_review`. Identifies Termination, Auto-renewal, and Liability Cap clauses and maps financial values together with their source currency and verbatim evidence. When no target clause is found, the score remains unavailable.

### 2. Risk Intelligence
Computes a heuristic contract health score (0–100) based on extracted risk clauses. Value Leakage groups the selected nominal amounts by expiration month and currency; it does not annualize payments, perform FX conversion, or predict actual cash flow. Dollar signs without a currency code use the USD convention. The score and evidence confidence are rule-based indicators, not calibrated probabilities or vendor screening results.

### 3. Agentic Governance
LangGraph orchestrates six analysis agents. The calendar stores deadline alerts and preserves resolved alerts during reanalysis. An optional Slack webhook sends an immediate notification after a successful analysis commit; it is not a scheduled delivery service. Negotiation suggestions and Q&A support Claude and offline templates.

IMAP ingestion, OFAC screening, and collaborative redlining remain prototype modules and are not complete end-to-end integrations. They are not covered by the completed-analysis status.

---

## How to use

VEGA is built for SME owners, operations managers, procurement teams, and legal professionals. **You do not need a legal background to use VEGA.** 

### Quickstart

```bash
git clone https://github.com/afild/vega.git
cd vega
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# PowerShell: Copy-Item .env.example .env
python run.py
```
Open `http://localhost:8005` in your browser.

### AI Modes

VEGA defaults to **Offline Mode** where all scoring and extraction operate locally, and negotiation intelligence uses rule-based templates.

To enable **LLM Mode** (Anthropic Claude):
```bash
export ANTHROPIC_API_KEY=your_key_here   # Linux/macOS
set ANTHROPIC_API_KEY=your_key_here      # Windows
python run.py
```

Raw contract text is **not** sent to the LLM by default. Enabling
`ALLOW_LLM_RAW_CONTRACT_TEXT=true` authorizes the clause extractor and Q&A
assistant to share limited document excerpts with the configured provider.

### Local security boundary

VEGA binds to `127.0.0.1` by default and is designed for same-origin local use.
Uploads are limited to 25 MB by default and validated by file signature and
document structure, rather than filename alone. DOCX archives also receive
path-traversal and expanded-size checks.

Do not expose the development server directly to a LAN or the public internet.
For remote or multi-user use, place VEGA behind authenticated TLS termination
and explicitly configure `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`.
VEGA does not encrypt contract files or the SQLite database itself; use operating
system access controls and full-disk encryption for sensitive production data.

Run one application process per database (the default in `python run.py`).
Background analysis is in-process, not a durable queue. Startup marks interrupted
jobs as failed; they can be retried manually. Existing databases migrate automatically
and their old results are marked `legacy` until reanalyzed.

### Verification

```bash
python -B -m pytest -q -p no:cacheprovider
python -B -m ruff check app tests run.py
node --check frontend/app.js
node --test tests/frontend.test.cjs
```

Tests use temporary databases and document storage with external integrations disabled.

---

## Details

<details>
<summary><strong>Architecture & Flow</strong></summary>

<picture>
  <img src="docs/images/architecture.png" width="100%" alt="VEGA System Architecture" />
</picture>

</details>

<details>
<summary><strong>REST API Surface</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/contracts` | `GET` | List contracts |
| `/api/contracts/upload` | `POST` | Upload a PDF/DOCX for processing |
| `/api/contracts/{id}` | `GET` | Contract details and extracted clauses |
| `/api/contracts/{id}/file` | `GET` | Open or download the original contract file |
| `/api/contracts/{id}/analyze` | `POST` | Reprocess an existing contract |
| `/api/contracts/{id}/analysis-runs` | `GET` | Analysis history, warnings, errors, and extracted character counts |
| `/api/contracts/{id}/terminate`| `POST` | Generate 1-Click Terminate email draft (`mailto:`) |
| `/api/alerts/upcoming` | `GET` | Active deadline alerts (90/60/30-day windows) |
| `/api/analysis/value-leakage`| `GET` | Aggregated financial leakage chart data |
| `/api/contracts/{id}/negotiation-intel` | `GET` | Negotiation recommendations for a contract |
| `/api/negotiation/ask` | `POST` | Ask a question about a contract |
| `/api/system/status` | `GET` | System status, AI mode (`llm` or `offline`), version |

</details>

<details>
<summary><strong>Tech Stack</strong></summary>

| Component | Technology |
|---|---|
| Backend | FastAPI 0.115 (Python 3.11+) |
| Agent Orchestration | LangGraph 0.2.39 · LangChain 0.3.7 |
| Document Parsing | PyMuPDF 1.24.11 · LlamaIndex 0.11.22 |
| AI Narrative | Anthropic Claude (optional) · offline heuristics |
| Alert Scheduling | schedule 1.2.2 |
| Database | SQLite (zero-server, local-first) · SQLAlchemy |
| Dashboard | HTML + CSS + JavaScript · Chart.js 4.5.1 (SRI pinned) |
| Testing | pytest · pytest-asyncio · httpx |

</details>

<details>
<summary><strong>NIST AI RMF 1.0 Alignment</strong></summary>

| NIST Function | VEGA Implementation |
|---|---|
| **GOVERN** | MIT License · anti-hallucination policy documented · traceable clause extraction |
| **MAP** | Contract governance domain scoped to SME vendor management · documented extraction rules |
| **MEASURE** | pytest suite · contextual regex validation · verbatim field evidence · versioned analysis runs |
| **MANAGE** | Offline fallback · explicit failure/review states · last-good-result preservation · human review before negotiation dispatch |

</details>

---

## Contributing
Areas where contributions are most needed:
- DOCX clause extraction improvements (python-docx integration)
- Multi-language contract support (Spanish, Portuguese)
- Contract comparison across versions (diff analysis)
- Docker Compose setup for zero-dependency deployment

**License:** MIT License — free to use, adapt, and redistribute.
