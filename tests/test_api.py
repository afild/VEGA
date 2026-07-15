# tests/test_api.py
import pytest
import io
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.database.db_manager import SessionLocal

client = TestClient(app)

def test_system_status():
    """Valida o endpoint de health check /api/system/status."""
    response = client.get("/api/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database_records" in data
    assert "version" in data

def test_contracts_endpoints():
    """Testa o fluxo de upload, listagem e obtenção de detalhes do contrato."""
    # 1. Cria um PDF falso em memória para simular o upload
    file_content = b"PDF FALSO DE CONTRATO DE TESTE\nThis contract terminates on 2026-12-31 with a 30 days notice."
    file_io = io.BytesIO(file_content)
    
    response = client.post(
        "/api/contracts/upload",
        files={"file": ("contrato_parceiro.pdf", file_io, "application/pdf")},
        data={"vendor_name": "Parceiro Tecnologia LTDA"}
    )
    
    assert response.status_code == 200
    upload_data = response.json()
    assert "contract_id" in upload_data
    assert upload_data["status"] == "draft"
    contract_id = upload_data["contract_id"]
    
    # 2. Testa a listagem de contratos
    list_resp = client.get("/api/contracts")
    assert list_resp.status_code == 200
    contracts = list_resp.json()
    assert len(contracts) >= 1
    
    # 3. Testa a obtenção de detalhes
    detail_resp = client.get(f"/api/contracts/{contract_id}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["title"] == "Contrato Parceiro"
    assert detail_data["vendor_name"] == "Parceiro Tecnologia LTDA"

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

def test_negotiation_ask_endpoint():
    """Testa a rota de perguntas e respostas Q&A (RAG)."""
    db = SessionLocal()
    try:
        # Insere dados de contrato e cláusula para responder a pergunta
        db.execute(text("INSERT INTO vendors (name) VALUES ('Q&A Vendor')"))
        vendor_id = db.execute(text("SELECT id FROM vendors WHERE name = 'Q&A Vendor'")).scalar()
        
        db.execute(text(
            "INSERT INTO contracts (vendor_id, title, file_path, status, renewal_notice_days, auto_renews) "
            "VALUES (:vid, 'Contrato Q&A', 'fake/path_qa.pdf', 'active', 60, 1)"
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
