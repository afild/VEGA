import re
import logging

def run_risk_detector(state: dict) -> dict:
    """
    Agente Detector de Risco.
    Avalia o nível de risco de cada cláusula extraída e calcula o Health Score global do contrato.
    Regras estritas:
    - Se aviso prévio for > 60 dias nas cláusulas de rescisão/renovação, o risco é 'high'.
    - Se a limitação de responsabilidade for excessivamente unilateral ou desfavorável, o risco é 'high'.
    """
    logging.info(f"[Risk Detector] Analisando riscos do contrato ID: {state.get('contract_id')}")
    
    clauses = state.get("clauses_found", [])
    health_score = 100.0
    risk_flags = []
    
    # Padrão regex para extrair dias de notificação (ex: "60 days", "90 dias", "120-day")
    days_pattern = re.compile(r"(\d{2,3})\s*(?:days|dias|day|dia)", re.IGNORECASE)
    
    for clause in clauses:
        clause_type = clause.get("clause_type")
        original_text = clause.get("original_text", "")
        
        # Padrão inicial do nível de risco é low
        risk_level = "low"
        explanation = clause.get("risk_explanation", "") or ""
        
        if clause_type == "Termination":
            # Procura por números de aviso prévio
            match = days_pattern.search(original_text)
            if match:
                days = int(match.group(1))
                if days > 60:
                    risk_level = "high"
                    explanation = f"Alerta de alto risco: Aviso prévio de rescisão é de {days} dias (superior ao limite aceitável de 60 dias)."
                    risk_flags.append(f"Termination notice period of {days} days is too long")
                elif days > 30:
                    risk_level = "medium"
                    explanation = f"Aviso prévio de rescisão de {days} dias requer atenção."
                    risk_flags.append(f"Termination notice period of {days} days is medium risk")
            
            # Procura por multas ou termos desfavoráveis
            if re.search(r"(penalty|penalty fee|fine|multa|indenização|perda do sinal|liquidated damages)", original_text, re.IGNORECASE):
                if risk_level != "high":
                    risk_level = "medium"
                    explanation += " Contrato prevê multas ou penalidades financeiras em caso de rescisão."
                    risk_flags.append("Termination penalty fees detected")
                    
        elif clause_type == "Auto-renewal":
            # Procura por números de aviso de não-renovação
            match = days_pattern.search(original_text)
            if match:
                days = int(match.group(1))
                if days > 60:
                    risk_level = "high"
                    explanation = f"Alerta de alto risco: Renovação automática requer aviso prévio de cancelamento de {days} dias."
                    risk_flags.append(f"Auto-renewal notice period of {days} days is too long")
                elif days > 30:
                    risk_level = "medium"
                    explanation = f"Renovação automática requer aviso de cancelamento de {days} dias."
                    risk_flags.append(f"Auto-renewal notice period of {days} days is medium risk")
            else:
                # Se renova automaticamente e não tem dias claros, colocamos médio
                risk_level = "medium"
                explanation = "Contrato possui renovação automática sem período de notificação explícito no trecho analisado."
                risk_flags.append("Auto-renewal with unspecified notice period")
                
        elif clause_type == "Liability Cap":
            # Procura por limitação unilateral ou termos de isenção
            is_unilateral = re.search(r"(unilateral|solely|sole remedy|exclusiva responsabilidade|isenta|exclui.*responsabilidade|shall not exceed|limita-se ao valor|limited.*paid|limited.*amounts|limitado.*pago|limitada.*valor)", original_text, re.IGNORECASE)
            
            if is_unilateral:
                risk_level = "high"
                explanation = "Limitação de responsabilidade considerada unilateral ou desfavorável para a SME (ex: limitada ao valor pago)."
                risk_flags.append("Unilateral or low liability cap")
            else:
                risk_level = "medium"
                explanation = "Existe limitação de responsabilidade padrão aplicável."
                risk_flags.append("Standard liability cap present")
                
        # Atualiza a cláusula com as conclusões do Risk Detector
        clause["risk_level"] = risk_level
        clause["risk_explanation"] = explanation
        
        # Penaliza o Health Score
        if risk_level == "high":
            health_score -= 25.0
        elif risk_level == "medium":
            health_score -= 10.0

    # Garante limite inferior do health_score
    health_score = max(0.0, health_score)
    
    state["health_score"] = health_score
    state["risk_flags"] = risk_flags
    state["completed_steps"].append("risk_detector")
    
    logging.info(f"[Risk Detector] Concluído. Health Score calculado: {health_score}. Risk Flags: {risk_flags}")
    return state
