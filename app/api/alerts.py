from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.db_manager import get_db

router = APIRouter(prefix="/alerts", tags=["Alerts"])

@router.get("/upcoming")
def list_upcoming_alerts(db: Session = Depends(get_db)):
    """
    Lista todos os alertas de renovação/expiração de contratos futuros pendentes de resolução.
    Traz dados associados do contrato e fornecedor para a renderização da timeline.
    """
    query_str = """
        SELECT a.id, a.contract_id, a.alert_type, a.trigger_date, a.is_resolved,
               c.title as contract_title, v.name as vendor_name, c.end_date 
        FROM alerts a
        JOIN contracts c ON a.contract_id = c.id
        LEFT JOIN vendors v ON c.vendor_id = v.id
        WHERE a.is_resolved = 0
        ORDER BY a.trigger_date ASC
    """
    
    result = db.execute(text(query_str)).fetchall()
    
    alerts = []
    for r in result:
        alerts.append({
            "id": r[0],
            "contract_id": r[1],
            "alert_type": r[2],
            "trigger_date": r[3],
            "is_resolved": bool(r[4]),
            "contract_title": r[5],
            "vendor_name": r[6] or "Fornecedor Não Identificado",
            "end_date": r[7]
        })
        
    return alerts

@router.patch("/{id:int}/resolve")
def resolve_alert(id: int, db: Session = Depends(get_db)):
    """
    Marca um alerta contratual específico como resolvido.
    """
    # Verifica se o alerta existe
    alert_exists = db.execute(
        text("SELECT 1 FROM alerts WHERE id = :id"),
        {"id": id}
    ).scalar()
    
    if not alert_exists:
        raise HTTPException(status_code=404, detail="Alerta não encontrado.")
        
    db.execute(
        text("UPDATE alerts SET is_resolved = 1 WHERE id = :id"),
        {"id": id}
    )
    db.commit()
    
    return {
        "message": "Alerta resolvido com sucesso.",
        "alert_id": id
    }
