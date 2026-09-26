<div align="center">
  <picture>
    <img src="assets/readme/hero.svg" width="100%" alt="VEGA - Vendor & Contract Governance Agent" />
  </picture>
</div>

**An open-source vendor and contract governance agent for SMEs.**

VEGA ingests PDF and DOCX contracts, extracts critical clauses (termination, auto-renewal, liability caps), computes a contract health score, maps financial exposure, and records deadline alerts for 90-, 60-, and 30-day windows when the required dates are identified. The analysis pipeline supports a local offline mode, with an optional and explicitly controlled Claude integration. Each execution has an auditable state and never turns an ingestion failure into a healthy contract.

---

## Why it is different

**Anti-hallucination architecture**
Every clause stored in the database includes the `original_text` field — a contiguous, verbatim slice from the source — plus source offsets and extraction method. Financial values, currencies, dates, renewal state, and notice periods not found unambiguously in the document are stored as `NULL`, never filled with optimistic defaults. Their exact supporting text is retained as field-level evidence. Date extraction is driven via contextual regex, not LLM.

**Reliable, versioned analysis**
Contract lifecycle (`draft`, `active`, `expired`, `terminated`) is separate from analysis state (`queued`, `processing`, `completed`, `needs_review`, `failed`). Reanalysis is single-flight per contract, successful results are replaced transactionally, and a failed reanalysis preserves the last valid clauses, score, dates, alerts, and financial data. Interrupted in-process jobs are marked failed on the next startup instead of remaining silently stuck.

**Local-first document processing**
By default, PDF parsing, clause extraction, and risk scoring happen on your machine. When a Claude key is configured, negotiation narratives and Q&A can send extracted clauses, including their verbatim `original_text`, to Anthropic. Q&A also sends contract metadata and the user's question. `ALLOW_LLM_RAW_CONTRACT_TEXT=false` blocks additional raw-document context, not the sharing of extracted clause text. See **AI Modes and data sharing** below before enabling Claude.

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
LangGraph orchestrates six analysis agents. The calendar stores deadline alerts and preserves resolved alerts during reanalysis. When future alerts exist, an optional Slack webhook attempts an immediate notification after a successful analysis commit. There is no background scheduler delivering reminders when those dates arrive; consult the dashboard timeline to track them. Negotiation suggestions and Q&A support Claude and offline templates.

IMAP ingestion, OFAC screening, and collaborative redlining remain prototype modules and are not complete end-to-end integrations. They are not covered by the completed-analysis status.

---

## How to use

VEGA is built for SME owners, operations managers, procurement teams, and legal professionals. **You do not need a legal background to use VEGA.** 

### Quickstart

Prerequisites: Git and Python 3.11 or newer, available as `git` and `python` in your terminal. Node.js is only needed for the JavaScript checks below, not to run the application.

Clone the repository, then follow **one** setup block for your shell:

```text
git clone https://github.com/afild/VEGA.git
cd VEGA
```

**Linux/macOS (Bash)**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python run.py
```

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python` for installation and startup; changing the execution policy is not required.

**Windows Command Prompt (CMD)**

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
copy .env.example .env
python run.py
```

These instructions assume a fresh clone. Preserve an existing `.env` instead of copying over it. On systems where Python 3 is named `python3`, use `python3 -m venv .venv`; after activation, use `python` as shown.

Open `http://localhost:8005` in your browser.

### AI Modes and data sharing

VEGA defaults to **Offline Mode** when `ANTHROPIC_API_KEY` is empty or unset: scoring and extraction operate locally, and negotiation intelligence uses rule-based templates.

To enable **LLM Mode** (Anthropic Claude), set the key in the same terminal used to start VEGA. Use the command for your shell, then start or restart the application with `python run.py`:

**Linux/macOS (Bash)**

```bash
export ANTHROPIC_API_KEY="your_key_here"
```

**Windows PowerShell**

```powershell
$env:ANTHROPIC_API_KEY = "your_key_here"
```

**Windows Command Prompt (CMD)**

```bat
set "ANTHROPIC_API_KEY=your_key_here"
```

Alternatively, configure the key in your local `.env`, which must not be committed.

**What is sent to Anthropic when a key is configured:**

- Negotiation suggestions can send the original text, category, and risk level of medium- or high-risk clauses.
- Q&A can send the user's question, contract metadata, and extracted clauses, including original text, summaries, and risk information.
- With `ALLOW_LLM_RAW_CONTRACT_TEXT=false` (the default), clause extraction stays local and Q&A omits additional raw-document context. The two sharing paths above remain enabled.
- With `ALLOW_LLM_RAW_CONTRACT_TEXT=true`, clause extraction and Q&A can additionally send limited excerpts of the raw document.

**The raw-text setting is not a general no-sharing switch.** To disable Claude calls, leave `ANTHROPIC_API_KEY` empty or unset in both your environment and `.env`, then restart VEGA. Optional webhook and other integration settings are separate from the Claude mode.

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

From the repository root, use the Python environment prepared in Quickstart. `requirements.txt` includes the Python test dependencies but does **not** include Ruff; install it separately for lint checks:

```text
python -m pip install ruff
```

Install Node.js separately for the JavaScript checks and confirm that `node --version` works. No npm dependencies are required: these tests use Node's built-in `node:test` runner. The commands below work in Bash, PowerShell, and CMD (use `.\.venv\Scripts\python.exe` instead of `python` on Windows if you skipped activation):

```text
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
| Deadline Tracking | SQLite alert records · optional post-analysis Slack webhook · no scheduled delivery |
| Database | SQLite (zero-server, local-first) · SQLAlchemy |
| Dashboard | HTML + CSS + JavaScript · Chart.js 4.5.1 (SRI pinned) |
| Testing & Checks | pytest · pytest-asyncio · httpx · Ruff (separate install) · Node.js built-in test runner |

`schedule==1.2.2` remains in `requirements.txt`, but the current application does not use it to run a reminder scheduler.

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
