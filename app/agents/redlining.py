import logging
from typing import List, Dict
from langchain_anthropic import ChatAnthropic
from langchain.prompts import PromptTemplate
from app.config import settings
from app.database.db_manager import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

def generate_redlines(contract_id: int):
    """
    Gera marcações/redlines baseadas nos Playbooks armazenados e utilizando a API do Claude.
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY não configurada. Smart Drafting (Redlining) desativado.")
        return
        
    db: Session = next(get_db())
    
    # Busca cláusulas extraídas do contrato
    clauses = db.execute(
        text("SELECT id, clause_type, original_text FROM clauses WHERE contract_id = :id"),
        {"id": contract_id}
    ).fetchall()
    
    if not clauses:
        return
        
    # Busca playbooks disponíveis
    playbooks = db.execute(
        text("SELECT clause_type, desired_language, fallback_language FROM playbooks")
    ).fetchall()
    
    playbook_dict = {p[0].lower(): p for p in playbooks}
    
    llm = ChatAnthropic(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        api_key=settings.ANTHROPIC_API_KEY
    )
    
    prompt = PromptTemplate(
        input_variables=["original_text", "desired_language"],
        template=(
            "You are an expert contract lawyer representing an SME.\\n"
            "Review the following original clause:\\n"
            "'{original_text}'\\n\\n"
            "Your company's playbook rule is:\\n"
            "'{desired_language}'\\n\\n"
            "Suggest a redline edit (track changes) to make the clause comply with the playbook. "
            "Output only the suggested new text.\\n"
        )
    )
    
    for clause in clauses:
        clause_id, c_type, original_text = clause
        c_type_lower = c_type.lower()
        
        if c_type_lower in playbook_dict:
            pb = playbook_dict[c_type_lower]
            desired = pb[1]
            
            logger.info(f"Processando redline via Claude para cláusula: {c_type}")
            
            try:
                # Gera sugestão via LLM (Claude API)
                response = llm.invoke(prompt.format(original_text=original_text, desired_language=desired))
                suggested_text = response.content
                
                # TODO: Usar python-docx para inserir o comentário fisicamente no documento
                # Aqui iríamos abrir o .docx, achar o original_text, e adicionar um comment/track change.
                # Para fins de arquitetura, salvamos a sugestão no BD.
                
                db.execute(
                    text("""
                        INSERT INTO negotiation_intel (contract_id, benchmark_type, market_rate, suggestion)
                        VALUES (:cid, :btype, :rate, :sugg)
                    """),
                    {
                        "cid": contract_id,
                        "btype": "playbook_redline",
                        "rate": "N/A",
                        "sugg": suggested_text
                    }
                )
                db.commit()
            except Exception as e:
                logger.error(f"Erro ao gerar redline com Claude: {e}")
                
    db.close()
