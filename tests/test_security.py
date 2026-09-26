import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from sqlalchemy import text
from starlette.datastructures import Headers

from app.agents.negotiation_intel import answer_contract_question
from app.config import settings
from app.database.db_manager import SessionLocal, engine
from app.utils.file_storage import (
    ContractFileValidationError,
    delete_contract_file,
    get_contracts_storage_dir,
    resolve_contract_file_path,
    save_contract_file,
)


DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def make_docx_bytes(*, include_unsafe_path: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<?xml version='1.0'?><Types "
            "xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>",
        )
        archive.writestr(
            "word/document.xml",
            "<?xml version='1.0'?><w:document "
            "xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
        )
        if include_unsafe_path:
            archive.writestr("../payload.txt", "nao extrair")
    return output.getvalue()


def make_upload(filename: str, content: bytes, media_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers=Headers({"content-type": media_type}),
    )


def test_valid_docx_is_stored_inside_contract_directory():
    docx_content = make_docx_bytes()
    upload = make_upload("Contrato Seguro.docx", docx_content, DOCX_MEDIA_TYPE)
    saved_path = save_contract_file(upload)

    try:
        resolved_path = resolve_contract_file_path(saved_path)
        assert resolved_path.parent == get_contracts_storage_dir()
        assert resolved_path.suffix == ".docx"
        assert resolved_path.read_bytes() == docx_content
    finally:
        delete_contract_file(saved_path)


def test_docx_with_path_traversal_is_rejected_without_temporary_residue():
    storage_dir = get_contracts_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    files_before = set(storage_dir.iterdir())
    upload = make_upload(
        "Contrato Inseguro.docx",
        make_docx_bytes(include_unsafe_path=True),
        DOCX_MEDIA_TYPE,
    )

    with pytest.raises(ContractFileValidationError, match="caminho interno inseguro"):
        save_contract_file(upload)

    assert set(storage_dir.iterdir()) == files_before


def test_sqlite_foreign_keys_are_enabled():
    with engine.connect() as connection:
        enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()

    assert enabled == 1


def test_llm_question_does_not_share_raw_document_without_opt_in(
    tmp_path,
    monkeypatch,
):
    secret_marker = "SEGREDO_QUE_NAO_DEVE_SAIR"
    outside_file = tmp_path / "sensitive.pdf"
    outside_file.write_text(secret_marker, encoding="utf-8")

    db = SessionLocal()
    try:
        contract_id = db.execute(
            text(
                "INSERT INTO contracts (title, file_path, status) "
                "VALUES ('Contrato Privado', :path, 'active') RETURNING id"
            ),
            {"path": str(outside_file)},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO clauses "
                "(contract_id, clause_type, original_text, summary, risk_level) "
                "VALUES (:id, 'Termination', 'Aviso de 30 dias.', "
                "'Rescisão com aviso', 'low')"
            ),
            {"id": contract_id},
        )
        db.commit()

        captured_messages = []

        class FakeChatAnthropic:
            def __init__(self, **kwargs):
                pass

            def invoke(self, messages):
                captured_messages.extend(messages)
                return SimpleNamespace(content="Resposta segura")

        import langchain_anthropic

        monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChatAnthropic)
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(settings, "ALLOW_LLM_RAW_CONTRACT_TEXT", False)

        response = answer_contract_question(contract_id, "Como rescindir?", db)
    finally:
        db.close()

    serialized_messages = "\n".join(str(message.content) for message in captured_messages)
    assert response == "Resposta segura"
    assert secret_marker not in serialized_messages
    assert "CLÁUSULAS EXTRAÍDAS" in serialized_messages
