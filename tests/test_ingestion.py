# tests/test_ingestion.py
import pytest
from pathlib import Path
from app.agents.document_ingestion import run_document_ingestion
from app.config import settings

def test_document_ingestion_text_file(tmp_path):
    """Testa se o Document Ingestion Agent lê corretamente arquivos genéricos de texto."""
    # Cria um arquivo de teste temporário dentro do workspace de teste
    test_file = tmp_path / "test_contract.txt"
    test_content = "CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE TI\nContratante: PME Software LTDA\nContratado: Cloud Hosting Inc"
    test_file.write_text(test_content, encoding="utf-8")
    
    # Calcula o caminho relativo à raiz do projeto VEGA para bater com o comportamento esperado
    try:
        relative_path = test_file.relative_to(settings.BASE_DIR)
    except ValueError:
        # Se tmp_path for fora, usamos o caminho absoluto como string
        relative_path = str(test_file)
        
    state = {
        "contract_id": 1,
        "file_path": str(relative_path),
        "raw_text": "",
        "completed_steps": []
    }
    
    result_state = run_document_ingestion(state)
    
    assert "document_ingestion" in result_state["completed_steps"]
    assert "CONTRATO DE PRESTAÇÃO DE SERVIÇOS" in result_state["raw_text"]
    assert "Contratante: PME Software" in result_state["raw_text"]

def test_document_ingestion_missing_file():
    """Testa o comportamento do agente quando o arquivo não é encontrado."""
    state = {
        "contract_id": 999,
        "file_path": "VEGA/app/data/storage/contracts/non_existent_file.pdf",
        "raw_text": "",
        "completed_steps": []
    }
    
    result_state = run_document_ingestion(state)
    
    assert "document_ingestion" in result_state["completed_steps"]
    assert result_state["raw_text"] == ""
