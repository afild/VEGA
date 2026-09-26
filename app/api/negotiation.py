import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field, field_validator
from app.database.db_manager import get_db
from app.agents.negotiation_intel import answer_contract_question

router = APIRouter(tags=["Negotiation"])

class AskQuestionRequest(BaseModel):
    contract_id: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A pergunta não pode estar vazia.")
        return normalized

@router.get("/contracts/{id:int}/negotiation-intel")
def get_negotiation_intel(id: int, db: Session = Depends(get_db)):
    """
    Retorna a inteligência de negociação e sugestões de contrapropostas geradas para o contrato específico.
    """
    # Verifica se o contrato existe
    contract_exists = db.execute(
        text("SELECT 1 FROM contracts WHERE id = :id"),
        {"id": id}
    ).scalar()
    
    if not contract_exists:
        raise HTTPException(status_code=404, detail="Contrato não encontrado.")
        
    intel_res = db.execute(
        text("SELECT id, benchmark_type, market_rate, suggestion FROM negotiation_intel WHERE contract_id = :id"),
        {"id": id}
    ).fetchall()
    
    intel_list = []
    for intel in intel_res:
        intel_list.append({
            "id": intel[0],
            "benchmark_type": intel[1],
            "market_rate": intel[2],
            "suggestion": intel[3]
        })
        
    return intel_list

@router.post("/negotiation/ask")
def ask_contract_question(payload: AskQuestionRequest, db: Session = Depends(get_db)):
    """
    Endpoint RAG de perguntas e respostas. Permite que o usuário faça perguntas livres em linguagem natural
    sobre o conteúdo do contrato carregado e analisado.
    """
    contract_state = db.execute(
        text(
            "SELECT analysis_revision, analysis_status "
            "FROM contracts WHERE id = :id"
        ),
        {"id": payload.contract_id},
    ).fetchone()
    if not contract_state:
        raise HTTPException(status_code=404, detail="Contrato não encontrado.")
    if contract_state[0] < 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "O contrato ainda não possui uma análise concluída. "
                f"Estado atual: {contract_state[1]}."
            ),
        )

    try:
        response_text = answer_contract_question(payload.contract_id, payload.question, db)
        return {
            "contract_id": payload.contract_id,
            "question": payload.question,
            "response": response_text
        }
    except Exception as exc:
        logging.exception("Erro interno ao responder pergunta sobre contrato.")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao responder pergunta sobre contrato.",
        ) from exc
