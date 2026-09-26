# tests/test_extraction.py
from datetime import datetime, timedelta
from app.agents.clause_extraction import run_clause_extraction, run_heuristic_extraction
from app.agents.risk_detector import run_risk_detector
from app.agents.financial_impact import (
    parse_financial_details_with_evidence,
    run_financial_impact,
)
from app.agents.alert_calendar import (
    detect_auto_renewal,
    extract_dates_with_evidence,
    extract_notice_days,
    run_alert_calendar,
)

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
    assert result["payment_frequency"] == "unknown"
    assert "MULTIPLE_PAYMENT_FREQUENCIES_FOUND" in result["analysis_warnings"]

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


def test_heuristic_clause_text_is_literal_and_contiguous():
    raw_text = (
        "Termination requires 90 days prior notice.\n"
        "The agreement shall automatically renew every year.\n"
        "Liability is limited to amounts paid by the customer."
    )

    clauses = run_heuristic_extraction(raw_text)

    assert len(clauses) == 3
    for clause in clauses:
        assert clause["original_text"] in raw_text
        assert "[...]" not in clause["original_text"]
        start = clause["source_start"]
        end = clause["source_end"]
        assert raw_text[start:end] == clause["original_text"]


def test_duplicate_clause_occurrences_do_not_double_penalize_same_risk_type():
    state = {
        "contract_id": 1,
        "clauses_found": [
            {
                "clause_type": "Termination",
                "original_text": "Termination requires 90 days prior notice.",
                "summary": "",
                "risk_explanation": "",
            },
            {
                "clause_type": "Termination",
                "original_text": "A second termination route also requires 120 days notice.",
                "summary": "",
                "risk_explanation": "",
            },
        ],
        "risk_flags": [],
        "completed_steps": [],
    }

    result = run_risk_detector(state)

    assert result["health_score"] == 75.0
    assert all(clause["risk_level"] == "high" for clause in result["clauses_found"])


def test_financial_extraction_prefers_contract_value_over_larger_penalty():
    text = (
        "The total contract value is USD 1,200.00. "
        "A termination penalty of USD 9,000.00 applies."
    )

    value, frequency, evidence, warnings = parse_financial_details_with_evidence(text)

    assert value == 1200.0
    assert frequency == "unknown"
    assert evidence[0]["source_text"] == "USD 1,200.00"
    assert text[evidence[0]["source_start"]:evidence[0]["source_end"]] == evidence[0]["source_text"]
    assert "MULTIPLE_FINANCIAL_VALUES_FOUND" in warnings


def test_financial_extraction_preserves_brl_currency():
    value, frequency, evidence, _ = parse_financial_details_with_evidence(
        "O valor total do contrato é R$ 2.500,50, pago mensalmente."
    )

    assert value == 2500.50
    assert frequency == "monthly"
    currency_evidence = next(
        item for item in evidence if item["field_name"] == "financial_currency"
    )
    assert currency_evidence["normalized_value"] == "BRL"


def test_date_extraction_supports_written_dates_and_rejects_ambiguous_numeric_date():
    text = (
        "Effective Date: December 31, 2026. "
        "Expiration Date: 2 de janeiro de 2028."
    )

    start_date, end_date, evidence, warnings = extract_dates_with_evidence(text)
    ambiguous = extract_dates_with_evidence("Contract date: 01/02/2027.")

    assert start_date == "2026-12-31"
    assert end_date == "2028-01-02"
    assert {item["field_name"] for item in evidence} == {"start_date", "end_date"}
    assert warnings == []
    assert ambiguous[0] is None and ambiguous[1] is None
    assert "AMBIGUOUS_NUMERIC_DATE_IGNORED" in ambiguous[3]


def test_renewal_and_notice_are_not_invented():
    assert detect_auto_renewal("This agreement shall not automatically renew.") is False
    assert extract_notice_days("No notice period is stated in this agreement.") is None
