# tests/test_ingestion.py
import fitz
import pytest

from app.agents.document_ingestion import DocumentIngestionError, run_document_ingestion
from app.utils.file_storage import get_contracts_storage_dir

def test_document_ingestion_pdf_inside_contract_storage():
    """O agente lê um PDF válido quando ele está no storage autorizado."""
    storage_dir = get_contracts_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    test_file = storage_dir / "test_contract.pdf"
    test_content = "CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE TI\nContratante: PME Software LTDA\nContratado: Cloud Hosting Inc"
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox((72, 72, 520, 760), test_content)
    document.save(test_file)
    document.close()
        
    state = {
        "contract_id": 1,
        "file_path": str(test_file),
        "raw_text": "",
        "completed_steps": [],
        "risk_flags": [],
    }
    
    result_state = run_document_ingestion(state)
    
    assert "document_ingestion" in result_state["completed_steps"]
    assert "CONTRATO DE PRESTAÇÃO DE SERVIÇOS" in result_state["raw_text"]
    assert "Contratante: PME Software" in result_state["raw_text"]


def test_document_ingestion_rejects_file_outside_storage(tmp_path):
    """Um caminho adulterado não pode transformar o agente em leitor arbitrário."""
    outside_file = tmp_path / "sensitive.txt"
    outside_file.write_text("SEGREDO_FORA_DO_STORAGE", encoding="utf-8")

    state = {
        "contract_id": 2,
        "file_path": str(outside_file),
        "raw_text": "",
        "completed_steps": [],
        "risk_flags": [],
    }

    with pytest.raises(DocumentIngestionError) as exc_info:
        run_document_ingestion(state)

    assert exc_info.value.code == "DOCUMENT_PATH_REJECTED"
    assert state["raw_text"] == ""
    assert "document_ingestion" not in state["completed_steps"]

def test_document_ingestion_missing_file():
    """Testa o comportamento do agente quando o arquivo não é encontrado."""
    state = {
        "contract_id": 999,
        "file_path": str(get_contracts_storage_dir() / "non_existent_file.pdf"),
        "raw_text": "",
        "completed_steps": []
    }
    
    with pytest.raises(DocumentIngestionError) as exc_info:
        run_document_ingestion(state)

    assert exc_info.value.code == "DOCUMENT_NOT_FOUND"
    assert "document_ingestion" not in state["completed_steps"]
    assert state["raw_text"] == ""
