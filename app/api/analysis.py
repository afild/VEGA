import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.db_manager import get_db
from app.agents.orchestrator import analyze_contract_pipeline

router = APIRouter(prefix="/contracts", tags=["Analysis"])

@router.post("/{id}/analyze")
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
    
    logging.info(f"Disparando re-análise manual para o contrato ID: {id}")
    
    # Podemos executar de forma síncrona aqui para que a UI receba a confirmação com o resultado completo,
    # ou de forma assíncrona. Para rotas manuais, executar síncrono é prático, mas para arquivos grandes pode travar por 10s.
    # Vamos rodar em background mas retornar que foi iniciado, ou rodar síncrono.
    # Dado que o Claude pode demorar alguns segundos, rodar em background e retornar um status é mais robusto.
    background_tasks.add_task(analyze_contract_pipeline, id, file_path)
    
    return {
        "message": "Processamento de re-análise iniciado.",
        "contract_id": id,
        "title": contract[1],
        "status": "processing"
    }

@router.get("/{id}/clauses")
def get_contract_clauses(id: int, db: Session = Depends(get_db)):
    """
    Retorna as cláusulas mapeadas de um contrato específico, ordenadas por nível de risco (high -> medium -> low).
    """
    clauses_res = db.execute(
        text("""
            SELECT id, clause_type, original_text, summary, risk_level, risk_explanation 
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
            "risk_explanation": cl[5]
        })
        
    return clauses

@router.get("/value-leakage")
def get_value_leakage(db: Session = Depends(get_db)):
    """
    Project total financial value of contracts that auto-renew.
    Groups by expiration month.
    """
    query = text("""
        SELECT strftime('%Y-%m', end_date) as exp_month, SUM(financial_value) as total_leakage
        FROM contracts
        WHERE auto_renews = 1 AND end_date IS NOT NULL AND status IN ('active', 'draft')
        GROUP BY strftime('%Y-%m', end_date)
        ORDER BY exp_month ASC
    """)
    result = db.execute(query).fetchall()
    
    leakage = []
    for r in result:
        leakage.append({
            "month": r[0],
            "total_value": r[1] or 0.0
        })
        
    return leakage
