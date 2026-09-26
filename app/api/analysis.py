import json
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.db_manager import get_db
from app.agents.orchestrator import (
    AnalysisAlreadyRunningError,
    analyze_contract_pipeline,
    queue_contract_analysis,
)
from app.utils.file_storage import resolve_contract_file_path

router = APIRouter(prefix="/contracts", tags=["Analysis"])
portfolio_router = APIRouter(prefix="/analysis", tags=["Analysis"])

@router.post("/{id:int}/analyze")
def trigger_analysis(id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Força o reprocessamento manual do pipeline de análise LangGraph para um contrato existente.
    """
    contract = db.execute(
        text("SELECT file_path, title FROM contracts WHERE id = :id"),
        {"id": id}
    ).fetchone()
    
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato não encontrado.")
        
    file_path = contract[0]
    try:
        resolved_file = resolve_contract_file_path(file_path)
    except (TypeError, ValueError) as exc:
        logging.warning(f"Reanálise bloqueada para caminho inválido no contrato ID: {id}")
        raise HTTPException(
            status_code=409,
            detail="O arquivo original do contrato não está disponível para reanálise.",
        ) from exc

    if not resolved_file.is_file():
        raise HTTPException(
            status_code=409,
            detail="O arquivo original do contrato não está disponível para reanálise.",
        )
    
    logging.info(f"Disparando re-análise manual para o contrato ID: {id}")
    try:
        run_id = queue_contract_analysis(db, id, "manual")
        db.commit()
    except AnalysisAlreadyRunningError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Já existe uma análise em andamento para este contrato.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logging.exception("Falha ao enfileirar a reanálise do contrato ID %s.", id)
        raise HTTPException(
            status_code=500,
            detail="Não foi possível iniciar a reanálise.",
        ) from exc

    background_tasks.add_task(analyze_contract_pipeline, id, file_path, run_id)
    
    return {
        "message": "Processamento de re-análise iniciado.",
        "contract_id": id,
        "title": contract[1],
        "status": "processing",
        "analysis_status": "queued",
        "analysis_run_id": run_id,
    }


@router.get("/{id:int}/analysis-runs")
def get_analysis_runs(id: int, db: Session = Depends(get_db)):
    """Retorna o histórico auditável de execuções, da mais nova para a mais antiga."""
    contract_exists = db.execute(
        text("SELECT 1 FROM contracts WHERE id = :id"),
        {"id": id},
    ).scalar()
    if not contract_exists:
        raise HTTPException(status_code=404, detail="Contrato não encontrado.")

    rows = db.execute(
        text("""
            SELECT id, trigger_source, status, started_at, completed_at,
                   error_code, error_message, warnings_json,
                   extracted_text_chars, created_at
            FROM analysis_runs
            WHERE contract_id = :id
            ORDER BY created_at DESC, id DESC
            LIMIT 50
        """),
        {"id": id},
    ).fetchall()

    history = []
    for row in rows:
        try:
            warnings = json.loads(row[7] or "[]")
        except (TypeError, json.JSONDecodeError):
            warnings = []
        history.append({
            "run_id": row[0],
            "trigger_source": row[1],
            "status": row[2],
            "started_at": row[3],
            "completed_at": row[4],
            "error_code": row[5],
            "error_message": row[6],
            "warnings": warnings,
            "extracted_text_chars": row[8],
            "created_at": row[9],
        })
    return history

@router.get("/{id:int}/clauses")
def get_contract_clauses(id: int, db: Session = Depends(get_db)):
    """
    Retorna as cláusulas mapeadas de um contrato específico, ordenadas por nível de risco (high -> medium -> low).
    """
    clauses_res = db.execute(
        text("""
            SELECT id, clause_type, original_text, summary, risk_level,
                   risk_explanation, extraction_method, source_start, source_end
            FROM clauses 
            WHERE contract_id = :id
            ORDER BY 
                CASE risk_level 
                    WHEN 'high' THEN 1 
                    WHEN 'medium' THEN 2 
                    WHEN 'low' THEN 3 
                    ELSE 4 
                END
        """),
        {"id": id}
    ).fetchall()
    
    if not clauses_res:
        # Verifica se o contrato existe
        contract_exists = db.execute(
            text("SELECT 1 FROM contracts WHERE id = :id"),
            {"id": id}
        ).scalar()
        if not contract_exists:
            raise HTTPException(status_code=404, detail="Contrato não encontrado.")
        return []
        
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
        
    return clauses

@portfolio_router.get("/value-leakage")
def get_value_leakage(db: Session = Depends(get_db)):
    """
    Project total financial value of contracts that auto-renew.
    Groups by expiration month.
    """
    query = text("""
        SELECT strftime('%Y-%m', end_date) as exp_month,
               financial_currency,
               SUM(financial_value) as total_leakage
        FROM contracts
        WHERE auto_renews = 1
          AND end_date IS NOT NULL
          AND financial_value IS NOT NULL
          AND financial_currency IS NOT NULL
          AND analysis_revision > 0
          AND status = 'active'
        GROUP BY strftime('%Y-%m', end_date), financial_currency
        ORDER BY exp_month ASC, financial_currency ASC
    """)
    result = db.execute(query).fetchall()
    
    leakage = []
    for r in result:
        leakage.append({
            "month": r[0],
            "currency": r[1],
            "total_value": r[2] or 0.0
        })
        
    return leakage
