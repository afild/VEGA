import logging
import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.config import settings

def run_negotiation_intel(state: dict) -> dict:
    """Agente de Inteligência de Negociação.

    Gera recomendações de negociação e contrapropostas para as cláusulas de risco identificadas.
    Salva as sugestões no estado para serem persistidas no banco.

    Args:
        state (dict): Estado atual do LangGraph (VEGAState).

    Returns:
        dict: O estado atualizado com as sugestões de negociação.
    """
    try:
        logging.info(f"[Negotiation Intel] Analisando contrapropostas para o contrato ID: {state.get('contract_id')}")
        
        clauses: List[Dict[str, Any]] = state.get("clauses_found", [])
        state["negotiation_suggestions"] = []
        
        # Se não houver cláusulas, não há o que propor
        if not clauses:
            state["completed_steps"].append("negotiation_intel")
            return state
            
        api_key: str = settings.ANTHROPIC_API_KEY
        
        if api_key:
            try:
                from langchain_anthropic import ChatAnthropic
                from langchain_core.messages import SystemMessage, HumanMessage
                
                chat = ChatAnthropic(
                    anthropic_api_key=api_key,
                    model_name=settings.LLM_MODEL,
                    temperature=settings.LLM_TEMPERATURE,
                    max_tokens=settings.LLM_MAX_TOKENS
                )
                
                # Formata as cláusulas de risco para o LLM
                formatted_clauses: List[Dict[str, str]] = []
                for c in clauses:
                    if c.get("risk_level") in ["medium", "high"]:
                        formatted_clauses.append({
                            "clause_type": c.get("clause_type", ""),
                            "risk_level": c.get("risk_level", ""),
                            "original_text": c.get("original_text", "")
                        })
                        
                if not formatted_clauses:
                    # Se todas forem de baixo risco, usamos heurística simples e finalizamos
                    state["negotiation_suggestions"] = generate_offline_suggestions(clauses)
                    state["completed_steps"].append("negotiation_intel")
                    return state
                    
                system_prompt: str = (
                    "Você é um negociador sênior de contratos corporativos.\n"
                    "Para cada uma das cláusulas de risco médio ou alto fornecidas pelo usuário, gere:\n"
                    "1. 'benchmark_type': O tipo da cláusula analisada.\n"
                    "2. 'market_rate': Qual é a taxa/prazo ou termo padrão aceito pelo mercado.\n"
                    "3. 'suggestion': Uma sugestão exata de redação alternativa ou uma tática de negociação clara para a SME.\n\n"
                    "Retorne EXCLUSIVAMENTE um array JSON contendo objetos com o formato:\n"
                    "[\n"
                    "  {\n"
                    "    \"benchmark_type\": \"Tipo de Cláusula\",\n"
                    "    \"market_rate\": \"Termo comum de mercado\",\n"
                    "    \"suggestion\": \"Redação ou tática proposta\"\n"
                    "  }\n"
                    "]\n"
                    "Não adicione markdown block de código, responda apenas o JSON puro em português brasileiro."
                )
                
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"Aqui estão as cláusulas de risco para as quais gerar sugestões:\n\n{json.dumps(formatted_clauses)}")
                ]
                
                response = chat.invoke(messages)
                response_text: str = response.content.strip()
                
                # Limpa possíveis blocos de código markdown ```json
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()
                
                suggestions: List[Dict[str, Any]] = json.loads(response_text)
                state["negotiation_suggestions"] = suggestions
                logging.info(f"[Negotiation Intel] Claude gerou {len(suggestions)} sugestões de negociação.")
                
            except Exception as e:
                logging.error(f"[Negotiation Intel] Erro na chamada do LLM: {e}. Entrando em fallback heurístico.")
                state["negotiation_suggestions"] = generate_offline_suggestions(clauses)
        else:
            logging.info("[Negotiation Intel] Chave ANTHROPIC_API_KEY ausente. Usando heurísticas offline.")
            state["negotiation_suggestions"] = generate_offline_suggestions(clauses)
            
        state["completed_steps"].append("negotiation_intel")
        return state
        
    except Exception as e:
        logging.error(f"[Negotiation Intel] Erro inesperado e catastrófico no nó: {e}")
        state.setdefault("risk_flags", []).append("NEGOTIATION_INTEL_FAILED")
        return state


def generate_offline_suggestions(clauses: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Gera sugestões de negociação genéricas baseadas no tipo de cláusula (Offline Fallback).

    Args:
        clauses (List[Dict[str, Any]]): Lista de cláusulas encontradas.

    Returns:
        List[Dict[str, str]]: Lista de sugestões de benchmark e negociação.
    """
    suggestions: List[Dict[str, str]] = []
    
    for c in clauses:
        clause_type: str = c.get("clause_type", "")
        risk_level: str = c.get("risk_level", "low")
        
        if risk_level not in ["medium", "high"]:
            continue
            
        if clause_type == "Termination":
            suggestions.append({
                "benchmark_type": "Rescisão Contratual",
                "market_rate": "Aviso prévio mútuo de 30 a 60 dias sem penalidades financeiras.",
                "suggestion": "Solicitar a redução do prazo de aviso prévio de cancelamento para 30 dias. Exigir reciprocidade: se a contraparte pode rescindir por conveniência, a SME também deve poder, sob as mesmas condições."
            })
        elif clause_type == "Auto-renewal":
            suggestions.append({
                "benchmark_type": "Renovação Automática",
                "market_rate": "Renovação por períodos iguais desde que haja notificação prévia de 30 dias.",
                "suggestion": "Negociar a eliminação da renovação automática, alterando para renovação mediante acordo mútuo por escrito. Caso não seja possível, garantir que a notificação de não-renovação possa ser enviada até 30 dias antes do término."
            })
        elif clause_type == "Liability Cap":
            suggestions.append({
                "benchmark_type": "Limitação de Responsabilidade",
                "market_rate": "Teto de responsabilidade limitado ao valor total pago nos últimos 12 meses, de forma bilateral.",
                "suggestion": "Contrapropor uma limitação de responsabilidade bilateral (mútua). Em contratos críticos, tentar estabelecer o teto em 1x a 2x o valor anual do contrato, em vez de isenção total ou limites irrisórios."
            })
            
    return suggestions


async def answer_contract_question(contract_id: int, question: str, db: Session) -> str:
    """RAG de Q&A sobre o contrato.

    Responde à pergunta do usuário utilizando o raw_text do contrato e as cláusulas extraídas.

    Args:
        contract_id (int): ID do contrato alvo.
        question (str): Pergunta do usuário.
        db (Session): Sessão ativa do SQLAlchemy.

    Returns:
        str: Resposta formatada baseada no contrato.
    """
    try:
        # Recupera o contrato no banco de dados usando SQL puro
        contract_res = db.execute(
            text("SELECT title, file_path, start_date, end_date, renewal_notice_days, auto_renews, financial_value, payment_frequency, health_score FROM contracts WHERE id = :id"),
            {"id": contract_id}
        ).fetchone()
        
        if not contract_res:
            return "Contrato não encontrado no sistema."
            
        # Recupera o texto bruto associado ao contrato
        from pathlib import Path
        file_path: str = contract_res[1] # file_path
        abs_path: Path = Path(settings.BASE_DIR) / file_path
        
        raw_text: str = ""
        if abs_path.exists():
            try:
                import fitz
                if abs_path.suffix.lower() == ".pdf":
                    doc = fitz.open(abs_path)
                    raw_text = "\n".join([page.get_text() for page in doc])
                    doc.close()
                else:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        raw_text = f.read()
            except Exception:
                pass
                
        if not raw_text:
            raw_text = f"Contrato: {contract_res[0]}. Vigência: {contract_res[2]} até {contract_res[3]}. Valor: {contract_res[6]}."

        # Recupera cláusulas salvas no banco
        clauses_res = db.execute(
            text("SELECT clause_type, original_text, summary, risk_level, risk_explanation FROM clauses WHERE contract_id = :id"),
            {"id": contract_id}
        ).fetchall()
        
        clauses_summary: List[str] = []
        for c in clauses_res:
            clauses_summary.append(f"Tipo: {c[0]}\nOriginal: {c[1]}\nResumo: {c[2]}\nRisco: {c[3]} - {c[4]}\n")
            
        clauses_text: str = "\n\n".join(clauses_summary)
        
        # Chama o Claude
        api_key: str = settings.ANTHROPIC_API_KEY
        if api_key:
            try:
                from langchain_anthropic import ChatAnthropic
                from langchain_core.messages import SystemMessage, HumanMessage
                
                chat = ChatAnthropic(
                    anthropic_api_key=api_key,
                    model_name=settings.LLM_MODEL,
                    temperature=settings.LLM_TEMPERATURE,
                    max_tokens=1500
                )
                
                system_prompt: str = (
                    "Você é um assistente virtual jurídico especializado em análise de contratos para PMEs.\n"
                    "Responda à pergunta do usuário de forma clara, objetiva e em português brasileiro.\n"
                    "Use as informações do texto bruto do contrato e o resumo das cláusulas extraídas fornecidas abaixo para fundamentar sua resposta.\n"
                    "Regra de Ouro: Baseie sua resposta APENAS nos dados fornecidos. Se a resposta não estiver no contrato, diga explicitamente que a informação não consta no documento."
                )
                
                context: str = (
                    f"=== METADADOS DO CONTRATO ===\n"
                    f"Título: {contract_res[0]}\n"
                    f"Data de Início: {contract_res[2]}\n"
                    f"Data de Término: {contract_res[3]}\n"
                    f"Renovação Automática: {'Sim' if contract_res[5] == 1 else 'Não'}\n"
                    f"Aviso Prévio (dias): {contract_res[4]}\n"
                    f"Valor Financeiro: {contract_res[6]} ({contract_res[7]})\n"
                    f"Health Score: {contract_res[8]}\n\n"
                    f"=== CLÁUSULAS EXTRAÍDAS ===\n"
                    f"{clauses_text}\n\n"
                    f"=== CONTEXTO DO TEXTO BRUTO (Snippet limitado) ===\n"
                    f"{raw_text[:25000]}"
                )
                
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"Dados do contrato:\n\n{context}\n\nPergunta do usuário: {question}")
                ]
                
                response = chat.invoke(messages)
                return response.content.strip()
                
            except Exception as e:
                logging.error(f"[Negotiation RAG Q&A] Erro ao chamar Claude: {e}")
                return answer_question_offline(question, contract_res, clauses_res)
        else:
            return answer_question_offline(question, contract_res, clauses_res)
            
    except Exception as e:
        logging.error(f"[Negotiation RAG Q&A] Erro grave: {e}")
        return "Desculpe, ocorreu um erro interno ao analisar este contrato."


def answer_question_offline(question: str, contract: Any, clauses: List[Any]) -> str:
    """Responde à pergunta usando heurística local básica (Offline Fallback).

    Args:
        question (str): Pergunta do usuário.
        contract (Any): Metadados do contrato do banco.
        clauses (List[Any]): Cláusulas do contrato do banco.

    Returns:
        str: Resposta heurística em texto.
    """
    q_lower: str = question.lower()
    
    # Resposta sobre Rescisão
    if "rescis" in q_lower or "cancel" in q_lower or "terminat" in q_lower or "sair" in q_lower:
        termination_clause = next((c for c in clauses if c[0] == "Termination"), None)
        if termination_clause:
            return (
                f"Com base na cláusula de rescisão (Termination) encontrada no contrato:\n\n"
                f"Texto Original: \"{termination_clause[1]}\"\n\n"
                f"Resumo: {termination_clause[2]}\n"
                f"Explicação de Risco: {termination_clause[4]}\n\n"
                f"Para rescindir o contrato com segurança, certifique-se de enviar a notificação escrita respeitando "
                f"o prazo de {contract[4]} dias de aviso prévio conforme estipulado."
            )
        else:
            return (
                f"Não encontrei nenhuma cláusula explícita de Rescisão (Termination) estruturada neste contrato. "
                f"O prazo de aviso prévio padrão registrado é de {contract[4]} dias. Recomendamos ler o documento inteiro "
                f"ou consultar as vias legais para evitar multas contratuais."
            )
            
    # Resposta sobre Renovação
    if "renova" in q_lower or "renew" in q_lower or "prorroga" in q_lower:
        renew_clause = next((c for c in clauses if c[0] == "Auto-renewal"), None)
        status_renew = "possui" if contract[5] == 1 else "não possui"
        
        reply = f"Este contrato {status_renew} renovação automática registrada.\n"
        if renew_clause:
            reply += (
                f"\nCláusula de Renovação Identificada:\n"
                f"Texto Original: \"{renew_clause[1]}\"\n"
                f"Resumo: {renew_clause[2]}\n\n"
                f"O prazo de aviso para evitar a renovação automática é de {contract[4]} dias antes do término ({contract[3]})."
            )
        else:
            reply += f"Data de término prevista: {contract[3]}."
            
        return reply
        
    # Resposta sobre Valores/Preço
    if "valor" in q_lower or "preço" in q_lower or "pagar" in q_lower or "pago" in q_lower or "custo" in q_lower or "financeiro" in q_lower:
        val = contract[6]
        freq = contract[7]
        if val:
            return f"O valor financeiro extraído deste contrato é de {val} com frequência de pagamento '{freq}'."
        else:
            return "Não foi identificado um valor financeiro específico ou preço explícito nas cláusulas extraídas deste contrato."
            
    # Resposta geral
    return (
        f"Esta é uma resposta do assistente offline do VEGA para o contrato '{contract[0]}'.\n"
        f"- Vigência: {contract[2]} até {contract[3]}\n"
        f"- Risco Geral (Health Score): {contract[8]}/100.0\n"
        f"- Renova Automaticamente: {'Sim' if contract[5] == 1 else 'Não'}\n\n"
        f"Para respostas mais específicas sobre outros trechos do contrato, certifique-se de configurar a chave "
        f"ANTHROPIC_API_KEY no arquivo .env."
    )
