# tests/test_api.py
import io
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import fitz
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.config import settings
from app.main import app
from app.database.db_manager import SessionLocal
from app.utils.file_storage import get_contracts_storage_dir

client = TestClient(app)


def make_pdf_bytes(text_content: str = "Contrato de teste") -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text_content)
    content = document.tobytes()
    document.close()
    return content

def test_system_status():
    """Valida o endpoint de health check /api/system/status."""
    response = client.get("/api/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database_records" in data
    assert "version" in data
    assert data["version"] == "0.3.0"
    assert data["raw_contract_text_sharing"] is False
    assert data["max_upload_size_mb"] == settings.MAX_CONTRACT_FILE_SIZE_MB

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_static_dashboard_and_root_redirect():
    """Valida que o frontend estático está montado a partir da raiz correta."""
    root_response = client.get("/", follow_redirects=False)
    assert root_response.status_code in (307, 308)
    assert root_response.headers["location"] == "/static/index.html"

    dashboard_response = client.get("/static/index.html")
    assert dashboard_response.status_code == 200
    assert "Vendor & Contract Governance Agent" in dashboard_response.text
    assert "chart.js@4.5.1" in dashboard_response.text
    assert "integrity=\"sha384-" in dashboard_response.text
    assert dashboard_response.headers["x-frame-options"] == "DENY"

    script_response = client.get("/static/app.js")
    assert script_response.status_code == 200
    for escaped_field in (
        "escapeHtml(c.title)",
        "escapeHtml(c.vendor_name)",
        "escapeHtml(cl.original_text)",
        "escapeHtml(s.suggestion)",
        "escapeHtml(a.contract_title)",
    ):
        assert escaped_field in script_response.text

def test_contracts_endpoints():
    """Testa o fluxo de upload, listagem e obtenção de detalhes do contrato."""
    # 1. Cria um PDF real em memória para simular o upload
    file_content = make_pdf_bytes(
        "This contract terminates on 2026-12-31 with a 30 days notice."
    )
    file_io = io.BytesIO(file_content)
    
    response = client.post(
        "/api/contracts/upload",
        files={"file": ("contrato_parceiro.pdf", file_io, "application/pdf")},
        data={"vendor_name": "Parceiro Tecnologia LTDA"}
    )
    
    assert response.status_code == 202
    upload_data = response.json()
    assert "contract_id" in upload_data
    assert upload_data["status"] == "draft"
    assert upload_data["analysis_status"] == "queued"
    assert "file_path" not in upload_data
    contract_id = upload_data["contract_id"]
    
    # 2. Testa a listagem de contratos
    list_resp = client.get("/api/contracts")
    assert list_resp.status_code == 200
    contracts = list_resp.json()
    assert len(contracts) >= 1
    assert all("file_path" not in contract for contract in contracts)
    
    # 3. Testa a obtenção de detalhes
    detail_resp = client.get(f"/api/contracts/{contract_id}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["title"] == "Contrato Parceiro"
    assert detail_data["vendor_name"] == "Parceiro Tecnologia LTDA"
    assert "file_path" not in detail_data

    # 4. O arquivo original deve ser acessível pela rota canônica do contrato
    file_resp = client.get(f"/api/contracts/{contract_id}/file")
    assert file_resp.status_code == 200
    assert file_resp.content == file_content
    assert file_resp.headers["content-type"].startswith("application/pdf")


def test_upload_rejects_spoofed_pdf_without_residue():
    """Uma extensão .pdf não basta e falhas não deixam arquivo nem fornecedor."""
    storage_dir = get_contracts_storage_dir()
    files_before = set(storage_dir.glob("*")) if storage_dir.exists() else set()

    response = client.post(
        "/api/contracts/upload",
        files={
            "file": (
                "contrato_falso.pdf",
                io.BytesIO(b"isto nao e um pdf"),
                "application/pdf",
            )
        },
        data={"vendor_name": "Fornecedor Upload Rejeitado"},
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    files_after = set(storage_dir.glob("*")) if storage_dir.exists() else set()
    assert files_after == files_before

    db = SessionLocal()
    try:
        vendor_count = db.execute(
            text("SELECT COUNT(*) FROM vendors WHERE name = :name"),
            {"name": "Fornecedor Upload Rejeitado"},
        ).scalar()
    finally:
        db.close()
    assert vendor_count == 0


def test_upload_rejects_mime_mismatch():
    response = client.post(
        "/api/contracts/upload",
        files={
            "file": (
                "contrato.pdf",
                io.BytesIO(make_pdf_bytes()),
                "text/plain",
            )
        },
    )

    assert response.status_code == 400
    assert "tipo de conteúdo" in response.json()["detail"]


def test_upload_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONTRACT_FILE_SIZE_MB", 1)
    oversized_content = b"%PDF-1.7\n" + (b"0" * (1024 * 1024))

    response = client.post(
        "/api/contracts/upload",
        files={
            "file": (
                "contrato_grande.pdf",
                io.BytesIO(oversized_content),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]


def test_upload_sanitizes_filename():
    response = client.post(
        "/api/contracts/upload",
        files={
            "file": (
                "../../CON?.pdf",
                io.BytesIO(make_pdf_bytes("Safe filename")),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 202
    contract_id = response.json()["contract_id"]

    db = SessionLocal()
    try:
        saved_path = db.execute(
            text("SELECT file_path FROM contracts WHERE id = :id"),
            {"id": contract_id},
        ).scalar_one()
    finally:
        db.close()

    resolved_path = Path(saved_path).resolve() if Path(saved_path).is_absolute() else (
        settings.BASE_DIR / saved_path
    ).resolve()
    assert resolved_path.parent == get_contracts_storage_dir()
    assert "?" not in resolved_path.name
    assert resolved_path.suffix == ".pdf"


def test_upload_rolls_back_file_when_database_registration_fails(monkeypatch):
    import app.api.contracts as contracts_api

    storage_dir = get_contracts_storage_dir()
    files_before = set(storage_dir.iterdir())

    def fail_vendor_registration(*args, **kwargs):
        raise RuntimeError("database failure simulation")

    monkeypatch.setattr(
        contracts_api,
        "_get_or_create_vendor",
        fail_vendor_registration,
    )

    response = client.post(
        "/api/contracts/upload",
        files={
            "file": (
                "rollback.pdf",
                io.BytesIO(make_pdf_bytes("Rollback test")),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Falha ao registrar o contrato no banco de dados."
    assert set(storage_dir.iterdir()) == files_before


def test_contract_file_rejects_path_outside_storage():
    """Impede que um caminho adulterado no banco exponha arquivos arbitrários."""
    db = SessionLocal()
    try:
        row = db.execute(text(
            "INSERT INTO contracts (title, file_path, status) "
            "VALUES ('Contrato Fora do Storage', '../README.md', 'draft') RETURNING id"
        )).fetchone()
        db.commit()
        contract_id = row[0]
    finally:
        db.close()

    response = client.get(f"/api/contracts/{contract_id}/file")
    assert response.status_code == 404

    reanalysis_response = client.post(f"/api/contracts/{contract_id}/analyze")
    assert reanalysis_response.status_code == 409


def test_local_security_boundaries():
    """Bloqueia host não confiável e mutações iniciadas por outro site."""
    untrusted_host = client.get(
        "/api/system/status",
        headers={"host": "malicious.example"},
    )
    assert untrusted_host.status_code == 400

    cross_origin_read = client.get(
        "/api/system/status",
        headers={"origin": "https://malicious.example"},
    )
    assert cross_origin_read.status_code == 200
    assert "access-control-allow-origin" not in cross_origin_read.headers

    cross_origin_write = client.post(
        "/api/negotiation/ask",
        headers={"origin": "https://malicious.example"},
        json={"contract_id": 1, "question": "teste"},
    )
    assert cross_origin_write.status_code == 403
    assert cross_origin_write.json()["detail"] == "Origem não permitida para esta operação."

    same_origin_write = client.post(
        "/api/negotiation/ask",
        headers={"origin": "http://testserver"},
        json={"contract_id": 999999, "question": "teste"},
    )
    assert same_origin_write.status_code == 404


def test_contract_list_validates_filters_and_pagination():
    assert client.get("/api/contracts?status=invalid").status_code == 422
    assert client.get("/api/contracts?vendor_id=0").status_code == 422
    assert client.get("/api/contracts?limit=501").status_code == 422


def test_value_leakage_endpoint():
    """Valida a rota pública usada pelo dashboard para Value Leakage."""
    db = SessionLocal()
    try:
        db.execute(text(
            "INSERT INTO contracts "
            "(title, file_path, status, end_date, auto_renews, financial_value, "
            "financial_currency, "
            "analysis_status, analysis_revision) "
            "VALUES ('Contrato Leakage', 'app/data/storage/contracts/leakage.pdf', "
            "'active', '2027-01-31', 1, 1200.0, 'USD', 'completed', 1)"
        ))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/analysis/value-leakage")
    assert response.status_code == 200
    assert {
        "month": "2027-01",
        "currency": "USD",
        "total_value": 1200.0,
    } in response.json()

    # A rota antiga não deve ser capturada silenciosamente como um ID de contrato.
    legacy_response = client.get("/api/contracts/value-leakage")
    assert legacy_response.status_code == 404

def test_alerts_endpoints():
    """Testa a listagem e resolução de prazos/alertas contratuais."""
    db = SessionLocal()
    try:
        # Insere um contrato e um alerta fake para testar os endpoints
        db.execute(text("INSERT INTO vendors (name) VALUES ('Fornecedor Alerta')"))
        vendor_id = db.execute(text("SELECT id FROM vendors WHERE name = 'Fornecedor Alerta'")).scalar()
        
        db.execute(text(
            "INSERT INTO contracts (vendor_id, title, file_path, status, end_date) "
            "VALUES (:vid, 'Contrato Alerta', 'fake/path.pdf', 'active', '2026-12-31')"
        ), {"vid": vendor_id})
        contract_id = db.execute(text("SELECT id FROM contracts WHERE title = 'Contrato Alerta'")).scalar()
        
        db.execute(text(
            "INSERT INTO alerts (contract_id, alert_type, trigger_date, is_resolved) "
            "VALUES (:cid, 'renewal_30d', '2026-11-30', 0)"
        ), {"cid": contract_id})
        alert_id = db.execute(text("SELECT id FROM alerts WHERE contract_id = :cid"), {"cid": contract_id}).scalar()
        db.commit()
    finally:
        db.close()
        
    # Testa listagem de alertas futuros
    upcoming_resp = client.get("/api/alerts/upcoming")
    assert upcoming_resp.status_code == 200
    alerts = upcoming_resp.json()
    assert len(alerts) >= 1
    
    # Testa resolução do alerta
    resolve_resp = client.patch(f"/api/alerts/{alert_id}/resolve")
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["alert_id"] == alert_id
    
    # Valida que foi de fato resolvido no banco
    db = SessionLocal()
    try:
        resolved = db.execute(text("SELECT is_resolved FROM alerts WHERE id = :id"), {"id": alert_id}).scalar()
        assert resolved == 1
    finally:
        db.close()


def test_termination_mailto_encodes_untrusted_database_text():
    db = SessionLocal()
    try:
        vendor_id = db.execute(
            text(
                "INSERT INTO vendors (name, contact_email) "
                "VALUES (:name, :email) RETURNING id"
            ),
            {"name": "Vendor & Partners", "email": "legal@example.com"},
        ).scalar_one()
        contract_id = db.execute(
            text(
                "INSERT INTO contracts (vendor_id, title, file_path, status) "
                "VALUES (:vendor_id, :title, :path, 'active') RETURNING id"
            ),
            {
                "vendor_id": vendor_id,
                "title": "Master &body=INJETADO?x=1",
                "path": "app/data/storage/contracts/mailto.pdf",
            },
        ).scalar_one()
        db.commit()
    finally:
        db.close()

    response = client.post(f"/api/contracts/{contract_id}/terminate")
    assert response.status_code == 200

    parsed = urlsplit(response.json()["mailto"])
    query = parse_qs(parsed.query)
    assert parsed.scheme == "mailto"
    assert parsed.path == "legal@example.com"
    assert set(query) == {"subject", "body"}
    assert query["subject"] == ["Notice of Non-Renewal: Master &body=INJETADO?x=1"]
    assert query["body"][0].startswith("Dear Vendor & Partners team")

def test_negotiation_ask_endpoint():
    """Testa a rota de perguntas e respostas Q&A (RAG)."""
    db = SessionLocal()
    try:
        # Insere dados de contrato e cláusula para responder a pergunta
        db.execute(text("INSERT INTO vendors (name) VALUES ('Q&A Vendor')"))
        vendor_id = db.execute(text("SELECT id FROM vendors WHERE name = 'Q&A Vendor'")).scalar()
        
        db.execute(text(
            "INSERT INTO contracts ("
            "vendor_id, title, file_path, status, renewal_notice_days, auto_renews, "
            "analysis_status, analysis_revision"
            ") VALUES ("
            ":vid, 'Contrato Q&A', 'app/data/storage/contracts/path_qa.pdf', "
            "'active', 60, 1, 'completed', 1"
            ")"
        ), {"vid": vendor_id})
        contract_id = db.execute(text("SELECT id FROM contracts WHERE title = 'Contrato Q&A'")).scalar()
        
        db.execute(text(
            "INSERT INTO clauses (contract_id, clause_type, original_text, summary, risk_level) "
            "VALUES (:cid, 'Auto-renewal', 'Contrato renova automaticamente em 12 meses.', 'Renova automático', 'high')"
        ), {"cid": contract_id})
        db.commit()
    finally:
        db.close()

    # Roda pergunta no endpoint de chat
    payload = {
        "contract_id": contract_id,
        "question": "Este contrato possui renovação automática?"
    }
    
    response = client.post("/api/negotiation/ask", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    # O fallback offline ou Claude deve responder mencionando renovação automática
    assert "renova" in data["response"].lower() or "automática" in data["response"].lower()


def test_negotiation_question_validation():
    empty_question = client.post(
        "/api/negotiation/ask",
        json={"contract_id": 1, "question": "   "},
    )
    assert empty_question.status_code == 422

    long_question = client.post(
        "/api/negotiation/ask",
        json={"contract_id": 1, "question": "x" * 2001},
    )
    assert long_question.status_code == 422

    missing_contract = client.post(
        "/api/negotiation/ask",
        json={"contract_id": 999999, "question": "Qual é o prazo?"},
    )
    assert missing_contract.status_code == 404


def test_negotiation_requires_a_completed_analysis():
    db = SessionLocal()
    try:
        contract_id = db.execute(
            text(
                "INSERT INTO contracts (title, file_path, status, analysis_status) "
                "VALUES ('Contrato Pendente Q&A', 'pending.pdf', 'draft', 'needs_review') "
                "RETURNING id"
            )
        ).scalar_one()
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/negotiation/ask",
        json={"contract_id": contract_id, "question": "Qual é o prazo?"},
    )

    assert response.status_code == 409
    assert "análise concluída" in response.json()["detail"]
