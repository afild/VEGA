# tests/test_extraction.py
import pytest
from datetime import datetime, timedelta
from app.agents.clause_extraction import run_clause_extraction
from app.agents.risk_detector import run_risk_detector
from app.agents.financial_impact import run_financial_impact
from app.agents.alert_calendar import run_alert_calendar

def test_heuristic_clause_extraction():
    """Valida se o extrator heurístico offline detecta termos de risco."""
    raw_text = (
        "This contract shall automatically renew for additional 1-year terms unless "
        "either party provides a 90 days prior written notice of termination.\n"
        "The provider's total limitation of liability is limited to the amounts paid under this contract."
    )
    
    state = {
        "contract_id": 1,
        "raw_text": raw_text,
        "clauses_found": [],
        "completed_steps": []
    }
    
    # Executa o extrator (vai cair no fallback offline pois ANTHROPIC_API_KEY não está no config de teste)
    result = run_clause_extraction(state)
    
    assert "clause_extraction" in result["completed_steps"]
    clauses = result["clauses_found"]
    
    # Deve encontrar pelo menos as cláusulas de Auto-renewal ou Termination devido aos termos chaves
    types_found = [c["clause_type"] for c in clauses]
    assert "Auto-renewal" in types_found or "Termination" in types_found
    assert "Liability Cap" in types_found

def test_risk_detector_notice_period_and_health_score():
    """Valida se o Risk Detector sinaliza aviso prévio longo (>60 dias) como risco High e penaliza a saúde."""
    clauses = [
        {
            "clause_type": "Termination",
            "original_text": "Aviso prévio para rescisão contratual é de 90 dias úteis de antecedência.",
            "summary": "Rescisão com 90 dias",
            "risk_explanation": ""
        },
        {
            "clause_type": "Liability Cap",
            "original_text": "Liability is limited solely to the amounts paid by the client.",
            "summary": "Limitação de responsabilidade",
            "risk_explanation": ""
        }
    ]
    
    state = {
        "contract_id": 1,
        "clauses_found": clauses,
        "risk_flags": [],
        "completed_steps": []
    }
    
    result = run_risk_detector(state)
    
    assert "risk_detector" in result["completed_steps"]
    # Como temos notice de 90 dias (>60) e liability cap unilateral, ambos devem ser classificados como high risk
    assert result["clauses_found"][0]["risk_level"] == "high"
    assert result["clauses_found"][1]["risk_level"] == "high"
    
    # Duas cláusulas High risk penalizam -25 cada. 100 - 50 = 50
    assert result["health_score"] == 50.0
    assert len(result["risk_flags"]) >= 2

def test_financial_impact_extraction():
    """Valida a detecção de valores monetários e frequência."""
    text = "The monthly fee for the cloud server license is $1,500.00 USD, billed annually."
    state = {
        "contract_id": 1,
        "raw_text": text,
        "completed_steps": []
    }
    
    result = run_financial_impact(state)
    
    assert "financial_impact" in result["completed_steps"]
    assert result["financial_value"] == 1500.0
    assert result["payment_frequency"] == "monthly" or result["payment_frequency"] == "annual"

def test_alert_calendar_generation():
    """Valida a geração de alertas futuros baseados no vencimento do contrato."""
    # Define uma data de término no futuro (daqui a 120 dias)
    future_date = (datetime.now() + timedelta(days=120)).date()
    future_date_str = future_date.strftime("%Y-%m-%d")
    
    # Texto contendo a data
    text = f"This contract will expire on {future_date_str} and requires a 30 days prior notice."
    
    state = {
        "contract_id": 1,
        "raw_text": text,
        "completed_steps": []
    }
    
    result = run_alert_calendar(state)
    
    assert "alert_calendar" in result["completed_steps"]
    assert result["end_date"] == future_date_str
    assert result["renewal_notice_days"] == 30
    
    # Alertas devem ser criados se as datas calculadas forem no futuro
    # Para expiração em 120 dias e notice de 30 dias:
    # Cancelamento limite = dia 90.
    # Alerta 30d antes do limite = dia 60 (no futuro).
    # Alerta 60d antes do limite = dia 30 (no futuro).
    # Alerta 90d antes do limite = dia 0 (pode ser hoje ou passado dependendo da hora).
    assert len(result["alerts_to_create"]) > 0
