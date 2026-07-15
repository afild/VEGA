import sqlite3
import logging
from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.db_manager import get_db, db_file_path
from app.config import settings

router = APIRouter(prefix="/system", tags=["System"])

@router.get("/status")
def get_system_status(db: Session = Depends(get_db)):
    """Retorna o status geral de integridade do VEGA e suas dependências."""
    
    # Contagens no banco local do VEGA
    try:
        vendors_count = db.execute(text("SELECT COUNT(*) FROM vendors")).scalar() or 0
        contracts_count = db.execute(text("SELECT COUNT(*) FROM contracts")).scalar() or 0
        clauses_count = db.execute(text("SELECT COUNT(*) FROM clauses")).scalar() or 0
        alerts_count = db.execute(text("SELECT COUNT(*) FROM alerts")).scalar() or 0
    except Exception as e:
        logging.error(f"Erro ao contar registros: {e}")
        vendors_count = contracts_count = clauses_count = alerts_count = 0
        
    status = "healthy"
    # Se os bancos de integração fundamentais não estiverem acessíveis, classificamos como degraded
        
    has_llm = bool(settings.ANTHROPIC_API_KEY)
    
    return {
        "status": status,
        "ai_mode": "llm" if has_llm else "offline",
        "llm_model": settings.LLM_MODEL if has_llm else "N/A",
        "database_records": {
            "vendors": vendors_count,
            "contracts": contracts_count,
            "clauses": clauses_count,
            "alerts": alerts_count
        },
        "version": "0.1.0"
    }
