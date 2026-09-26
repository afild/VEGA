import json
import logging
import mimetypes
import re
import unicodedata
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.db_manager import get_db
from app.utils.file_storage import (
    ContractFileTooLargeError,
    ContractFileValidationError,
    delete_contract_file,
    resolve_contract_file_path,
    save_contract_file,
)
from app.agents.orchestrator import (
    analyze_contract_pipeline,
    queue_contract_analysis,
)

router = APIRouter(prefix="/contracts", tags=["Contracts"])
VALID_CONTRACT_STATUSES = Literal["draft", "active", "expired", "terminated"]
EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,63}$",
    re.IGNORECASE,
)

@router.get("")
def list_contracts(
    status: Optional[VALID_CONTRACT_STATUSES] = None,
    vendor_id: Optional[int] = Query(default=None, gt=0),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Lista todos os contratos cadastrados.
    Permite filtrar por status (draft|active|expired|terminated) e/ou vendor_id.
    """
    query_str = """
        SELECT c.id, c.vendor_id, c.title, c.file_path, c.status, 
               c.start_date, c.end_date, c.auto_renews, c.renewal_notice_days, 
               c.financial_value, c.financial_currency,
               c.payment_frequency, c.health_score,
               c.analysis_status, c.analysis_error_code, c.analysis_error,
               c.analysis_started_at, c.analysis_completed_at,
               c.last_successful_analysis_at, c.analysis_revision,
               v.name as vendor_name
        FROM contracts c 
        LEFT JOIN vendors v ON c.vendor_id = v.id
        WHERE 1=1
    """
    params = {}
    
    if status:
        query_str += " AND c.status = :status"
        params["status"] = status
    if vendor_id:
        query_str += " AND c.vendor_id = :vendor_id"
        params["vendor_id"] = vendor_id
        
    query_str += " ORDER BY c.created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset
    
    result = db.execute(text(query_str), params).fetchall()
    
    contracts = []
    for r in result:
        contracts.append({
            "id": r[0],
            "vendor_id": r[1],
            "title": r[2],
            "status": r[4],
            "start_date": r[5],
            "end_date": r[6],
            "auto_renews": None if r[7] is None else bool(r[7]),
            "renewal_notice_days": r[8],
            "financial_value": r[9],
            "financial_currency": r[10],
            "payment_frequency": r[11],
            "health_score": r[12],
            "analysis_status": r[13],
            "analysis_error_code": r[14],
            "analysis_error": r[15],
            "analysis_started_at": r[16],
            "analysis_completed_at": r[17],
            "last_successful_analysis_at": r[18],
            "analysis_revision": r[19],
            "vendor_name": r[20] or "Fornecedor Não Identificado"
        })
        
    return contracts

@router.post("/upload", status_code=202)
def upload_contract(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    vendor_name: Optional[str] = Form(default=None, max_length=160),
    db: Session = Depends(get_db)
):
    """
    Recebe um arquivo PDF de contrato via Multipart/form-data.
    Salva o arquivo localmente, registra no banco de dados SQLite e dispara a análise assíncrona.
    """
    normalized_vendor_name = _normalize_vendor_name(vendor_name)
    original_filename = file.filename or "contrato"
    contract_title = _derive_contract_title(original_filename)

    # O arquivo é validado integralmente antes de qualquer escrita no banco.
    try:
        saved_relative_path = save_contract_file(file)
    except ContractFileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ContractFileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logging.exception("Erro de I/O ao salvar arquivo de contrato.")
        raise HTTPException(
            status_code=500,
            detail="Falha ao salvar o arquivo no servidor.",
        ) from exc

    try:
        vendor_id = _get_or_create_vendor(db, normalized_vendor_name)
        ins_contract = db.execute(
            text("""
                INSERT INTO contracts (
                    vendor_id, title, file_path, status, health_score, analysis_status,
                    auto_renews, renewal_notice_days
                )
                VALUES (:vendor_id, :title, :file_path, 'draft', NULL, 'not_started', NULL, NULL)
                RETURNING id
            """),
            {
                "vendor_id": vendor_id,
                "title": contract_title,
                "file_path": saved_relative_path,
            }
        )
        contract_id = ins_contract.fetchone()[0]
        run_id = queue_contract_analysis(db, contract_id, "upload")
        db.commit()
    except Exception as exc:
        db.rollback()
        _discard_saved_file(saved_relative_path)
        logging.exception("Falha ao registrar o contrato no banco de dados.")
        raise HTTPException(
            status_code=500,
            detail="Falha ao registrar o contrato no banco de dados.",
        ) from exc

    # 4. Dispara o processamento assíncrono em background
    logging.info(f"Enfileirando pipeline LangGraph para o contrato ID: {contract_id}")
    background_tasks.add_task(
        analyze_contract_pipeline,
        contract_id,
        saved_relative_path,
        run_id,
    )

    return {
        "message": "Upload efetuado com sucesso. Análise contratual iniciada em segundo plano.",
        "contract_id": contract_id,
        "title": contract_title,
        "status": "draft",
        "analysis_status": "queued",
        "analysis_run_id": run_id,
    }

@router.get("/{id:int}")
def get_contract_details(id: int, db: Session = Depends(get_db)):
    """
    Retorna os detalhes de um contrato específico, juntamente com as cláusulas extraídas.
    """
    contract_res = db.execute(
        text("""
            SELECT c.id, c.vendor_id, c.title, c.file_path, c.status, 
                   c.start_date, c.end_date, c.auto_renews, c.renewal_notice_days, 
                   c.financial_value, c.financial_currency,
                   c.payment_frequency, c.health_score,
                   c.analysis_status, c.analysis_run_id,
                   c.last_successful_run_id, c.analysis_error_code,
                   c.analysis_error, c.analysis_started_at,
                   c.analysis_completed_at, c.last_successful_analysis_at,
                   c.analysis_revision, v.name as vendor_name
            FROM contracts c 
            LEFT JOIN vendors v ON c.vendor_id = v.id
            WHERE c.id = :id
        """),
        {"id": id}
    ).fetchone()
    
    if not contract_res:
        raise HTTPException(status_code=404, detail="Contrato não encontrado.")
        
    clauses_res = db.execute(
        text("""
            SELECT id, clause_type, original_text, summary, risk_level,
                   risk_explanation, extraction_method, source_start, source_end
            FROM clauses 
            WHERE contract_id = :id
        """),
        {"id": id}
    ).fetchall()
    
    clauses = []
    for cl in clauses_res:
        clauses.append({
            "id": cl[0],
            "clause_type": cl[1],
            "original_text": cl[2],
            "summary": cl[3],
            "risk_level": cl[4],
            "risk_explanation": cl[5],
            "extraction_method": cl[6],
            "source_start": cl[7],
            "source_end": cl[8],
        })

    evidence_res = db.execute(
        text("""
            SELECT field_name, normalized_value, source_text, source_start,
                   source_end, extraction_method, confidence
            FROM analysis_evidence
            WHERE contract_id = :id
              AND analysis_run_id = :run_id
            ORDER BY id ASC
        """),
        {"id": id, "run_id": contract_res[15]},
    ).fetchall() if contract_res[15] else []
    evidence = [
        {
            "field_name": row[0],
            "normalized_value": row[1],
            "source_text": row[2],
            "source_start": row[3],
            "source_end": row[4],
            "extraction_method": row[5],
            "confidence": row[6],
        }
        for row in evidence_res
    ]

    warnings_json = db.execute(
        text("SELECT warnings_json FROM analysis_runs WHERE id = :run_id"),
        {"run_id": contract_res[14]},
    ).scalar() if contract_res[14] else "[]"
    try:
        analysis_warnings = json.loads(warnings_json or "[]")
    except (TypeError, json.JSONDecodeError):
        analysis_warnings = []
        
    return {
        "id": contract_res[0],
        "vendor_id": contract_res[1],
        "title": contract_res[2],
        "status": contract_res[4],
        "start_date": contract_res[5],
        "end_date": contract_res[6],
        "auto_renews": None if contract_res[7] is None else bool(contract_res[7]),
        "renewal_notice_days": contract_res[8],
        "financial_value": contract_res[9],
        "financial_currency": contract_res[10],
        "payment_frequency": contract_res[11],
        "health_score": contract_res[12],
        "analysis_status": contract_res[13],
        "analysis_error_code": contract_res[16],
        "analysis_error": contract_res[17],
        "analysis_started_at": contract_res[18],
        "analysis_completed_at": contract_res[19],
        "last_successful_analysis_at": contract_res[20],
        "analysis_revision": contract_res[21],
        "vendor_name": contract_res[22] or "Fornecedor Não Identificado",
        "analysis_warnings": analysis_warnings,
        "analysis_evidence": evidence,
        "clauses": clauses,
    }


@router.get("/{id:int}/file", response_class=FileResponse)
def get_contract_file(id: int, db: Session = Depends(get_db)):
    """Entrega o arquivo original de um contrato cadastrado."""
    contract = db.execute(
        text("SELECT file_path FROM contracts WHERE id = :id"),
        {"id": id}
    ).fetchone()

    if not contract:
        raise HTTPException(status_code=404, detail="Contrato não encontrado.")

    try:
        file_path = resolve_contract_file_path(contract[0])
    except (TypeError, ValueError):
        logging.warning(f"Caminho inválido armazenado para o contrato ID {id}.")
        raise HTTPException(status_code=404, detail="Arquivo do contrato não encontrado.")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo do contrato não encontrado.")

    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    disposition = "inline" if file_path.suffix.lower() == ".pdf" else "attachment"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
        content_disposition_type=disposition,
    )

@router.post("/{id:int}/terminate")
def generate_termination_email(id: int, db: Session = Depends(get_db)):
    """
    Gera um link mailto para cancelamento com base nos dados do contrato.
    """
    contract_res = db.execute(
        text("""
            SELECT c.title, c.end_date, v.name as vendor_name, v.contact_email
            FROM contracts c 
            LEFT JOIN vendors v ON c.vendor_id = v.id
            WHERE c.id = :id
        """),
        {"id": id}
    ).fetchone()
    
    if not contract_res:
        raise HTTPException(status_code=404, detail="Contrato não encontrado.")
        
    title = contract_res[0]
    end_date = contract_res[1]
    vendor_name = contract_res[2] or "Vendor"
    contact_email = contract_res[3] or ""
    
    subject = f"Notice of Non-Renewal: {title}"
    body = f"Dear {vendor_name} team,\n\nPlease accept this email as formal notice that we will not be renewing the {title}. "
    if end_date:
        body += f"The contract will terminate on {end_date}."
    else:
        body += "The contract will terminate at the end of the current term."
        
    body += "\n\nThank you for your services.\n\nSincerely,"
    
    safe_contact_email = (
        contact_email.strip()
        if EMAIL_PATTERN.fullmatch(contact_email.strip())
        else ""
    )
    encoded_address = quote(safe_contact_email, safe="@._+-")
    encoded_query = urlencode({"subject": subject, "body": body}, quote_via=quote)

    return {
        "mailto": f"mailto:{encoded_address}?{encoded_query}",
        "subject": subject,
        "body": body
    }


def _normalize_vendor_name(vendor_name: Optional[str]) -> str:
    if not vendor_name:
        return "Fornecedor Pendente"

    normalized = unicodedata.normalize("NFKC", vendor_name)
    normalized = "".join(
        " " if unicodedata.category(char).startswith("C") else char
        for char in normalized
    )
    normalized = " ".join(normalized.split())
    return normalized or "Fornecedor Pendente"


def _derive_contract_title(filename: str) -> str:
    normalized = unicodedata.normalize("NFKC", filename.replace("\\", "/"))
    stem = Path(normalized).stem
    stem = "".join(
        " " if unicodedata.category(char).startswith("C") else char for char in stem
    )
    title = " ".join(stem.replace("_", " ").replace("-", " ").split())
    return (title or "Contrato")[:200].title()


def _get_or_create_vendor(db: Session, vendor_name: str) -> int:
    vendor = db.execute(
        text("SELECT id FROM vendors WHERE name = :name COLLATE NOCASE"),
        {"name": vendor_name},
    ).fetchone()
    if vendor:
        return vendor[0]

    category = "Unassigned" if vendor_name == "Fornecedor Pendente" else "General"
    inserted = db.execute(
        text(
            "INSERT INTO vendors (name, category) "
            "VALUES (:name, :category) RETURNING id"
        ),
        {"name": vendor_name, "category": category},
    )
    return inserted.fetchone()[0]


def _discard_saved_file(file_path: str) -> None:
    try:
        delete_contract_file(file_path)
    except OSError:
        logging.exception("Não foi possível remover um upload após rollback do banco.")
