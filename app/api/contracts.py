import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, UploadFile, File, Form, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.db_manager import get_db
from app.utils.file_storage import save_contract_file
from app.agents.orchestrator import analyze_contract_pipeline

router = APIRouter(prefix="/contracts", tags=["Contracts"])

@router.get("")
def list_contracts(
    status: Optional[str] = None, 
    vendor_id: Optional[int] = None, 
    db: Session = Depends(get_db)
):
    """
    Lista todos os contratos cadastrados.
    Permite filtrar por status (draft|active|expired|terminated) e/ou vendor_id.
    """
    query_str = """
        SELECT c.id, c.vendor_id, c.title, c.file_path, c.status, 
               c.start_date, c.end_date, c.auto_renews, c.renewal_notice_days, 
               c.financial_value, c.payment_frequency, c.health_score, 
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
        
    query_str += " ORDER BY c.created_at DESC"
    
    result = db.execute(text(query_str), params).fetchall()
    
    contracts = []
    for r in result:
        contracts.append({
            "id": r[0],
            "vendor_id": r[1],
            "title": r[2],
            "file_path": r[3],
            "status": r[4],
            "start_date": r[5],
            "end_date": r[6],
            "auto_renews": bool(r[7]),
            "renewal_notice_days": r[8],
            "financial_value": r[9],
            "payment_frequency": r[10],
            "health_score": r[11],
            "vendor_name": r[12] or "Fornecedor Não Identificado"
        })
        
    return contracts

@router.post("/upload")
def upload_contract(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    vendor_name: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Recebe um arquivo PDF de contrato via Multipart/form-data.
    Salva o arquivo localmente, registra no banco de dados SQLite e dispara a análise assíncrona.
    """
    if not file.filename.lower().endswith(('.pdf', '.docx')):
        raise HTTPException(status_code=400, detail="Formato de arquivo inválido. Apenas PDF ou DOCX são aceitos.")

    # 1. Trata o Fornecedor (busca ou cria se informado)
    vendor_id = None
    if vendor_name and vendor_name.strip():
        vendor_name = vendor_name.strip()
        vendor_res = db.execute(
            text("SELECT id FROM vendors WHERE name = :name"), 
            {"name": vendor_name}
        ).fetchone()
        
        if vendor_res:
            vendor_id = vendor_res[0]
        else:
            # Insere novo fornecedor
            ins_res = db.execute(
                text("INSERT INTO vendors (name, category) VALUES (:name, 'General') RETURNING id"),
                {"name": vendor_name}
            )
            vendor_id = ins_res.fetchone()[0]
            db.commit()
            
    # Se não foi passado fornecedor, associamos a um fornecedor padrão temporário
    if not vendor_id:
        default_vendor_name = "Fornecedor Pendente"
        vendor_res = db.execute(
            text("SELECT id FROM vendors WHERE name = :name"), 
            {"name": default_vendor_name}
        ).fetchone()
        
        if vendor_res:
            vendor_id = vendor_res[0]
        else:
            ins_res = db.execute(
                text("INSERT INTO vendors (name, category) VALUES (:name, 'Unassigned') RETURNING id"),
                {"name": default_vendor_name}
            )
            vendor_id = ins_res.fetchone()[0]
            db.commit()

    # 2. Salva o arquivo no disco local
    try:
        saved_relative_path = save_contract_file(file)
    except Exception as e:
        logging.error(f"Erro ao salvar arquivo de contrato: {e}")
        raise HTTPException(status_code=500, detail="Falha ao salvar o arquivo no servidor.")

    # 3. Cria registro inicial do contrato como 'draft'
    contract_title = file.filename.rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ').title()
    
    ins_contract = db.execute(
        text("""
            INSERT INTO contracts (vendor_id, title, file_path, status, health_score) 
            VALUES (:vendor_id, :title, :file_path, 'draft', 100.0) 
            RETURNING id
        """),
        {
            "vendor_id": vendor_id,
            "title": contract_title,
            "file_path": saved_relative_path
        }
    )
    contract_id = ins_contract.fetchone()[0]
    db.commit()

    # 4. Dispara o processamento assíncrono em background
    logging.info(f"Enfileirando pipeline LangGraph para o contrato ID: {contract_id}")
    background_tasks.add_task(analyze_contract_pipeline, contract_id, saved_relative_path)

    return {
        "message": "Upload efetuado com sucesso. Análise contratual iniciada em segundo plano.",
        "contract_id": contract_id,
        "title": contract_title,
        "file_path": saved_relative_path,
        "status": "draft"
    }

@router.get("/{id}")
def get_contract_details(id: int, db: Session = Depends(get_db)):
    """
    Retorna os detalhes de um contrato específico, juntamente com as cláusulas extraídas.
    """
    contract_res = db.execute(
        text("""
            SELECT c.id, c.vendor_id, c.title, c.file_path, c.status, 
                   c.start_date, c.end_date, c.auto_renews, c.renewal_notice_days, 
                   c.financial_value, c.payment_frequency, c.health_score, 
                   v.name as vendor_name 
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
            SELECT id, clause_type, original_text, summary, risk_level, risk_explanation 
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
            "risk_explanation": cl[5]
        })
        
    return {
        "id": contract_res[0],
        "vendor_id": contract_res[1],
        "title": contract_res[2],
        "file_path": contract_res[3],
        "status": contract_res[4],
        "start_date": contract_res[5],
        "end_date": contract_res[6],
        "auto_renews": bool(contract_res[7]),
        "renewal_notice_days": contract_res[8],
        "financial_value": contract_res[9],
        "payment_frequency": contract_res[10],
        "health_score": contract_res[11],
        "vendor_name": contract_res[12] or "Fornecedor Não Identificado",
        "clauses": clauses
    }
