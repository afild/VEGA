import logging
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.db_manager import get_db_context

# Importando os nós dos agentes
from app.agents.document_ingestion import run_document_ingestion
from app.agents.clause_extraction import run_clause_extraction
from app.agents.risk_detector import run_risk_detector
from app.agents.financial_impact import run_financial_impact
from app.agents.alert_calendar import run_alert_calendar
from app.agents.negotiation_intel import run_negotiation_intel

# Definição do Estado do Grafo
class VEGAState(TypedDict):
    """Tipagem forte para o Estado do Pipeline VEGA."""
    contract_id: int
    file_path: str
    raw_text: str
    completed_steps: List[str]
    clauses_found: List[Dict[str, Any]]
    risk_flags: List[str]
    health_score: float
    financial_value: Optional[float]
    payment_frequency: str
    start_date: Optional[str]
    end_date: Optional[str]
    auto_renews: int
    renewal_notice_days: int
    alerts_to_create: List[Dict[str, Any]]
    negotiation_suggestions: List[Dict[str, Any]]

def create_vega_graph() -> StateGraph:
    """Cria e compila o StateGraph para o pipeline do VEGA.

    Returns:
        StateGraph: O grafo compilado do LangGraph.
    """
    workflow = StateGraph(VEGAState)
    
    # Adicionando os nós correspondentes aos sub-agentes
    workflow.add_node("document_ingestion", run_document_ingestion)
    workflow.add_node("clause_extraction", run_clause_extraction)
    workflow.add_node("risk_detector", run_risk_detector)
    workflow.add_node("financial_impact", run_financial_impact)
    workflow.add_node("alert_calendar", run_alert_calendar)
    workflow.add_node("negotiation_intel", run_negotiation_intel)
    
    # Definindo o fluxo sequencial estrito do pipeline
    workflow.set_entry_point("document_ingestion")
    workflow.add_edge("document_ingestion", "clause_extraction")
    workflow.add_edge("clause_extraction", "risk_detector")
    workflow.add_edge("risk_detector", "financial_impact")
    workflow.add_edge("financial_impact", "alert_calendar")
    workflow.add_edge("alert_calendar", "negotiation_intel")
    workflow.add_edge("negotiation_intel", END)
    
    return workflow.compile()

def save_analysis_to_db(state: VEGAState) -> None:
    """Grava de forma atômica e consistente todos os resultados do pipeline no banco SQLite.
    
    Limpa registros antigos de análises parciais para evitar duplicidade.
    Utiliza um context manager (get_db_context) para evitar vazamento de sessões.

    Args:
        state (VEGAState): O estado final consolidado gerado pelo LangGraph.
        
    Raises:
        Exception: Em caso de erro na transação do banco, efetua rollback e repassa a exceção.
    """
    contract_id = state.get("contract_id")
    logging.info(f"[Orchestrator DB] Persistindo dados da análise no SQLite para o contrato ID: {contract_id}")
    
    with get_db_context() as db:
        try:
            # 1. Determina status do contrato com base na data de vencimento
            status = "active"
            end_date_str = state.get("end_date")
            if end_date_str:
                try:
                    from datetime import datetime
                    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                    if end_dt < datetime.now().date():
                        status = "expired"
                except Exception:
                    pass
                    
            # 2. Atualiza a tabela 'contracts'
            db.execute(
                text("""
                    UPDATE contracts 
                    SET start_date = :start_date,
                        end_date = :end_date,
                        auto_renews = :auto_renews,
                        renewal_notice_days = :renewal_notice_days,
                        financial_value = :financial_value,
                        payment_frequency = :payment_frequency,
                        health_score = :health_score,
                        status = :status
                    WHERE id = :contract_id
                """),
                {
                    "start_date": state.get("start_date"),
                    "end_date": state.get("end_date"),
                    "auto_renews": state.get("auto_renews", 0),
                    "renewal_notice_days": state.get("renewal_notice_days", 30),
                    "financial_value": state.get("financial_value"),
                    "payment_frequency": state.get("payment_frequency", "one-time"),
                    "health_score": state.get("health_score", 100.0),
                    "status": status,
                    "contract_id": contract_id
                }
            )
            
            # 3. Limpa e insere 'clauses'
            db.execute(text("DELETE FROM clauses WHERE contract_id = :cid"), {"cid": contract_id})
            for clause in state.get("clauses_found", []):
                db.execute(
                    text("""
                        INSERT INTO clauses (contract_id, clause_type, original_text, summary, risk_level, risk_explanation)
                        VALUES (:cid, :clause_type, :original_text, :summary, :risk_level, :risk_explanation)
                    """),
                    {
                        "cid": contract_id,
                        "clause_type": clause.get("clause_type"),
                        "original_text": clause.get("original_text", ""),
                        "summary": clause.get("summary", ""),
                        "risk_level": clause.get("risk_level", "low"),
                        "risk_explanation": clause.get("risk_explanation", "")
                    }
                )
                
            # 4. Limpa e insere 'alerts'
            db.execute(text("DELETE FROM alerts WHERE contract_id = :cid"), {"cid": contract_id})
            for alert in state.get("alerts_to_create", []):
                db.execute(
                    text("""
                        INSERT INTO alerts (contract_id, alert_type, trigger_date, is_resolved)
                        VALUES (:cid, :alert_type, :trigger_date, 0)
                    """),
                    {
                        "cid": contract_id,
                        "alert_type": alert.get("alert_type"),
                        "trigger_date": alert.get("trigger_date")
                    }
                )
                
            # 5. Limpa e insere 'negotiation_intel'
            db.execute(text("DELETE FROM negotiation_intel WHERE contract_id = :cid"), {"cid": contract_id})
            for suggestion in state.get("negotiation_suggestions", []):
                db.execute(
                    text("""
                        INSERT INTO negotiation_intel (contract_id, benchmark_type, market_rate, suggestion)
                        VALUES (:cid, :benchmark_type, :market_rate, :suggestion)
                    """),
                    {
                        "cid": contract_id,
                        "benchmark_type": suggestion.get("benchmark_type", ""),
                        "market_rate": suggestion.get("market_rate", ""),
                        "suggestion": suggestion.get("suggestion", "")
                    }
                )
                
            db.commit()
            logging.info(f"[Orchestrator DB] Análise persistida com sucesso para o contrato ID: {contract_id}")
        except Exception as e:
            db.rollback()
            logging.error(f"[Orchestrator DB] Falha crítica ao salvar análise no SQLite: {e}")
            raise e

def analyze_contract_pipeline(contract_id: int, file_path: str) -> VEGAState:
    """Função principal executada pela API para processar um contrato. 
    
    Inicializa o estado, executa o StateGraph do LangGraph e persiste o resultado final no banco de dados.

    Args:
        contract_id (int): O ID numérico do contrato a ser analisado.
        file_path (str): Caminho para o arquivo contendo o contrato.

    Returns:
        VEGAState: Estado consolidado resultante da análise do LangGraph.
    """
    initial_state = VEGAState(
        contract_id=contract_id,
        file_path=file_path,
        raw_text="",
        completed_steps=[],
        clauses_found=[],
        risk_flags=[],
        health_score=100.0,
        financial_value=None,
        payment_frequency="one-time",
        start_date=None,
        end_date=None,
        auto_renews=0,
        renewal_notice_days=30,
        alerts_to_create=[],
        negotiation_suggestions=[]
    )
    
    try:
        # Compila e roda o Grafo
        graph = create_vega_graph()
        final_state: VEGAState = graph.invoke(initial_state)
    except Exception as e:
        logging.critical(f"[Orchestrator] Falha catastrófica durante a execução do LangGraph: {e}")
        # Mesmo falhando na orquestração geral, devolvemos o que foi inicializado ou o que passou
        # e adicionamos a flag de risco.
        initial_state["risk_flags"].append("CRITICAL_PIPELINE_ERROR")
        final_state = initial_state
    
    # Persiste os resultados no SQLite de forma transacional
    try:
        save_analysis_to_db(final_state)
    except Exception as e:
        logging.error(f"[Orchestrator] Não foi possível persistir estado no DB: {e}")
    
    return final_state
