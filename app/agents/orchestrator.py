import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.alert_calendar import notify_alert_webhook, run_alert_calendar
from app.agents.clause_extraction import run_clause_extraction
from app.agents.document_ingestion import (
    DocumentIngestionError,
    DocumentNeedsReviewError,
    run_document_ingestion,
)
from app.agents.financial_impact import run_financial_impact
from app.agents.negotiation_intel import run_negotiation_intel
from app.agents.risk_detector import run_risk_detector
from app.database.db_manager import get_db_context


REQUIRED_PIPELINE_STEPS = {
    "document_ingestion",
    "clause_extraction",
    "risk_detector",
    "financial_impact",
    "alert_calendar",
    "negotiation_intel",
}
RUNNING_ANALYSIS_STATUSES = {"queued", "processing"}
ALLOWED_TRIGGER_SOURCES = {"upload", "manual", "system"}


class AnalysisAlreadyRunningError(RuntimeError):
    """O contrato já possui uma execução em andamento."""


class ContractAnalysisNotFoundError(RuntimeError):
    """O contrato deixou de existir antes de ser enfileirado."""


class StaleAnalysisRunError(RuntimeError):
    """Uma execução mais nova substituiu esta execução."""


class PipelineValidationError(RuntimeError):
    """O grafo terminou sem cumprir os invariantes necessários."""


class VEGAState(TypedDict):
    """Estado consolidado e auditável de uma execução do pipeline."""

    contract_id: int
    file_path: str
    analysis_run_id: str
    analysis_status: str
    raw_text: str
    completed_steps: List[str]
    clauses_found: List[Dict[str, Any]]
    risk_flags: List[str]
    health_score: Optional[float]
    financial_value: Optional[float]
    payment_frequency: str
    start_date: Optional[str]
    end_date: Optional[str]
    auto_renews: Optional[int]
    renewal_notice_days: Optional[int]
    alerts_to_create: List[Dict[str, Any]]
    negotiation_suggestions: List[Dict[str, Any]]
    analysis_evidence: List[Dict[str, Any]]
    analysis_warnings: List[str]
    document_metadata: Dict[str, Any]
    financial_currency: Optional[str]


def create_vega_graph() -> StateGraph:
    """Cria o fluxo sequencial dos agentes de análise."""
    workflow = StateGraph(VEGAState)
    workflow.add_node("document_ingestion", run_document_ingestion)
    workflow.add_node("clause_extraction", run_clause_extraction)
    workflow.add_node("risk_detector", run_risk_detector)
    workflow.add_node("financial_impact", run_financial_impact)
    workflow.add_node("alert_calendar", run_alert_calendar)
    workflow.add_node("negotiation_intel", run_negotiation_intel)

    workflow.set_entry_point("document_ingestion")
    workflow.add_edge("document_ingestion", "clause_extraction")
    workflow.add_edge("clause_extraction", "risk_detector")
    workflow.add_edge("risk_detector", "financial_impact")
    workflow.add_edge("financial_impact", "alert_calendar")
    workflow.add_edge("alert_calendar", "negotiation_intel")
    workflow.add_edge("negotiation_intel", END)
    return workflow.compile()


def queue_contract_analysis(
    db: Session,
    contract_id: int,
    trigger_source: str,
) -> str:
    """Reserva atomicamente uma nova execução para um contrato.

    A função participa da transação do chamador. O chamador deve fazer commit
    antes de entregar o trabalho ao executor em segundo plano.
    """
    if trigger_source not in ALLOWED_TRIGGER_SOURCES:
        raise ValueError("Origem de análise inválida.")

    run_id = uuid4().hex
    claimed = db.execute(
        text(
            """
            UPDATE contracts
            SET analysis_status = 'queued',
                analysis_run_id = :run_id,
                analysis_error_code = NULL,
                analysis_error = NULL,
                analysis_started_at = NULL,
                analysis_completed_at = NULL
            WHERE id = :contract_id
              AND COALESCE(analysis_status, 'not_started')
                  NOT IN ('queued', 'processing')
            """
        ),
        {"contract_id": contract_id, "run_id": run_id},
    )
    if claimed.rowcount != 1:
        current_status = db.execute(
            text("SELECT analysis_status FROM contracts WHERE id = :contract_id"),
            {"contract_id": contract_id},
        ).scalar()
        if current_status is None:
            raise ContractAnalysisNotFoundError("Contrato não encontrado.")
        raise AnalysisAlreadyRunningError("Já existe uma análise em andamento.")

    db.execute(
        text(
            """
            INSERT INTO analysis_runs (
                id, contract_id, trigger_source, status, created_at
            ) VALUES (
                :run_id, :contract_id, :trigger_source, 'queued', :created_at
            )
            """
        ),
        {
            "run_id": run_id,
            "contract_id": contract_id,
            "trigger_source": trigger_source,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        },
    )
    return run_id


def analyze_contract_pipeline(
    contract_id: int,
    file_path: str,
    run_id: Optional[str] = None,
) -> VEGAState:
    """Executa uma análise protegida por token e registra seu estado final."""
    if run_id is None:
        with get_db_context() as db:
            run_id = queue_contract_analysis(db, contract_id, "system")
            db.commit()

    state = _initial_state(contract_id, file_path, run_id)
    if not _mark_run_processing(contract_id, run_id):
        state["analysis_status"] = "superseded"
        return state

    try:
        state = create_vega_graph().invoke(state)
        final_state: VEGAState = state
        _validate_pipeline_result(final_state)
        save_analysis_to_db(final_state, run_id)
        final_state["analysis_status"] = "completed"
        notify_alert_webhook(final_state)
        return final_state
    except DocumentNeedsReviewError as exc:
        logging.warning(
            "[Orchestrator] Contrato ID %s requer revisão: %s",
            contract_id,
            exc.code,
        )
        _record_unsuccessful_run(
            state,
            run_id,
            status="needs_review",
            error_code=exc.code,
            error_message=exc.user_message,
        )
        state["analysis_status"] = "needs_review"
        state["risk_flags"].append(exc.code)
        return state
    except DocumentIngestionError as exc:
        logging.error(
            "[Orchestrator] Ingestão falhou no contrato ID %s: %s",
            contract_id,
            exc.code,
        )
        _record_unsuccessful_run(
            state,
            run_id,
            status="failed",
            error_code=exc.code,
            error_message=exc.user_message,
        )
        state["analysis_status"] = "failed"
        state["risk_flags"].append(exc.code)
        return state
    except StaleAnalysisRunError:
        logging.info(
            "[Orchestrator] Execução %s do contrato %s foi substituída.",
            run_id,
            contract_id,
        )
        _mark_run_superseded(run_id)
        state["analysis_status"] = "superseded"
        return state
    except PipelineValidationError as exc:
        logging.error(
            "[Orchestrator] Resultado inválido no contrato ID %s: %s",
            contract_id,
            exc,
        )
        _record_unsuccessful_run(
            state,
            run_id,
            status="failed",
            error_code="PIPELINE_INCOMPLETE",
            error_message="A análise não concluiu todas as etapas obrigatórias. Reprocesse o contrato.",
        )
        state["analysis_status"] = "failed"
        state["risk_flags"].append("PIPELINE_INCOMPLETE")
        return state
    except Exception:
        logging.exception(
            "[Orchestrator] Falha inesperada no contrato ID %s.", contract_id
        )
        _record_unsuccessful_run(
            state,
            run_id,
            status="failed",
            error_code="PIPELINE_ERROR",
            error_message="Ocorreu uma falha interna durante a análise. Reprocesse o contrato.",
        )
        state["analysis_status"] = "failed"
        state["risk_flags"].append("PIPELINE_ERROR")
        return state


def save_analysis_to_db(state: VEGAState, run_id: Optional[str] = None) -> None:
    """Substitui o último resultado válido em uma única transação."""
    contract_id = state["contract_id"]
    active_run_id = run_id or state["analysis_run_id"]
    lifecycle_status = _lifecycle_status(state.get("end_date"))
    warnings_json = json.dumps(
        list(dict.fromkeys(state.get("analysis_warnings", []))),
        ensure_ascii=False,
    )
    extracted_chars = state.get("document_metadata", {}).get(
        "extracted_text_chars",
        len(state.get("raw_text", "")),
    )

    with get_db_context() as db:
        try:
            updated = db.execute(
                text(
                    """
                    UPDATE contracts
                    SET start_date = :start_date,
                        end_date = :end_date,
                        auto_renews = :auto_renews,
                        renewal_notice_days = :renewal_notice_days,
                        financial_value = :financial_value,
                        financial_currency = :financial_currency,
                        payment_frequency = :payment_frequency,
                        health_score = :health_score,
                        status = CASE
                            WHEN status = 'terminated' THEN status
                            ELSE :lifecycle_status
                        END,
                        analysis_status = 'completed',
                        analysis_error_code = NULL,
                        analysis_error = NULL,
                        analysis_completed_at = CURRENT_TIMESTAMP,
                        last_successful_analysis_at = CURRENT_TIMESTAMP,
                        last_successful_run_id = :run_id,
                        analysis_revision = analysis_revision + 1
                    WHERE id = :contract_id
                      AND analysis_run_id = :run_id
                      AND analysis_status = 'processing'
                    """
                ),
                {
                    "start_date": state.get("start_date"),
                    "end_date": state.get("end_date"),
                    "auto_renews": state.get("auto_renews"),
                    "renewal_notice_days": state.get("renewal_notice_days"),
                    "financial_value": state.get("financial_value"),
                    "financial_currency": state.get("financial_currency"),
                    "payment_frequency": state.get("payment_frequency", "unknown"),
                    "health_score": state["health_score"],
                    "lifecycle_status": lifecycle_status,
                    "contract_id": contract_id,
                    "run_id": active_run_id,
                },
            )
            if updated.rowcount != 1:
                raise StaleAnalysisRunError(active_run_id)

            _replace_clauses(db, state, active_run_id)
            _replace_alerts(db, state)
            _replace_negotiation_intel(db, state)
            _insert_analysis_evidence(db, state, active_run_id)
            db.execute(
                text(
                    """
                    UPDATE analysis_runs
                    SET status = 'completed',
                        completed_at = CURRENT_TIMESTAMP,
                        warnings_json = :warnings_json,
                        extracted_text_chars = :extracted_chars
                    WHERE id = :run_id AND status = 'processing'
                    """
                ),
                {
                    "run_id": active_run_id,
                    "warnings_json": warnings_json,
                    "extracted_chars": extracted_chars,
                },
            )
            db.commit()
            logging.info(
                "[Orchestrator DB] Análise %s persistida para contrato ID %s.",
                active_run_id,
                contract_id,
            )
        except Exception:
            db.rollback()
            raise


def _initial_state(contract_id: int, file_path: str, run_id: str) -> VEGAState:
    return VEGAState(
        contract_id=contract_id,
        file_path=file_path,
        analysis_run_id=run_id,
        analysis_status="queued",
        raw_text="",
        completed_steps=[],
        clauses_found=[],
        risk_flags=[],
        health_score=None,
        financial_value=None,
        financial_currency=None,
        payment_frequency="unknown",
        start_date=None,
        end_date=None,
        auto_renews=None,
        renewal_notice_days=None,
        alerts_to_create=[],
        negotiation_suggestions=[],
        analysis_evidence=[],
        analysis_warnings=[],
        document_metadata={},
    )


def _mark_run_processing(contract_id: int, run_id: str) -> bool:
    with get_db_context() as db:
        updated = db.execute(
            text(
                """
                UPDATE contracts
                SET analysis_status = 'processing',
                    analysis_started_at = CURRENT_TIMESTAMP
                WHERE id = :contract_id
                  AND analysis_run_id = :run_id
                  AND analysis_status = 'queued'
                """
            ),
            {"contract_id": contract_id, "run_id": run_id},
        )
        if updated.rowcount != 1:
            db.execute(
                text(
                    """
                    UPDATE analysis_runs
                    SET status = 'superseded', completed_at = CURRENT_TIMESTAMP
                    WHERE id = :run_id AND status = 'queued'
                    """
                ),
                {"run_id": run_id},
            )
            db.commit()
            return False

        db.execute(
            text(
                """
                UPDATE analysis_runs
                SET status = 'processing', started_at = CURRENT_TIMESTAMP
                WHERE id = :run_id AND status = 'queued'
                """
            ),
            {"run_id": run_id},
        )
        db.commit()
        return True


def _validate_pipeline_result(state: VEGAState) -> None:
    completed = set(state.get("completed_steps", []))
    missing = REQUIRED_PIPELINE_STEPS - completed
    if missing:
        raise PipelineValidationError(
            f"Etapas ausentes: {', '.join(sorted(missing))}"
        )

    raw_text = state.get("raw_text", "")
    if not raw_text.strip():
        raise PipelineValidationError("Texto extraído vazio.")

    failure_flags = [
        flag
        for flag in state.get("risk_flags", [])
        if flag.endswith("_FAILED") or flag == "CRITICAL_PIPELINE_ERROR"
    ]
    if failure_flags:
        raise PipelineValidationError(
            f"Falhas declaradas: {', '.join(failure_flags)}"
        )

    score = state.get("health_score")
    if score is None and not state.get("clauses_found"):
        pass
    elif not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
        raise PipelineValidationError("Health score inválido.")

    for clause in state.get("clauses_found", []):
        original = clause.get("original_text", "")
        if not original or original not in raw_text:
            raise PipelineValidationError("Cláusula sem evidência verbatim.")
        _validate_source_offsets(raw_text, clause)

    for evidence in state.get("analysis_evidence", []):
        if not evidence.get("field_name") or not evidence.get("source_text"):
            raise PipelineValidationError("Evidência de campo incompleta.")
        _validate_source_offsets(raw_text, evidence)


def _validate_source_offsets(raw_text: str, item: Dict[str, Any]) -> None:
    start = item.get("source_start")
    end = item.get("source_end")
    source_text = item.get("source_text") or item.get("original_text")
    if start is None and end is None:
        return
    if not isinstance(start, int) or not isinstance(end, int):
        raise PipelineValidationError("Offsets de evidência inválidos.")
    if start < 0 or end < start or raw_text[start:end] != source_text:
        raise PipelineValidationError("Offsets não correspondem ao texto original.")


def _replace_clauses(db: Session, state: VEGAState, run_id: str) -> None:
    contract_id = state["contract_id"]
    db.execute(text("DELETE FROM clauses WHERE contract_id = :cid"), {"cid": contract_id})
    for clause in state.get("clauses_found", []):
        db.execute(
            text(
                """
                INSERT INTO clauses (
                    contract_id, clause_type, original_text, summary,
                    risk_level, risk_explanation, analysis_run_id,
                    extraction_method, source_start, source_end
                ) VALUES (
                    :cid, :clause_type, :original_text, :summary,
                    :risk_level, :risk_explanation, :run_id,
                    :extraction_method, :source_start, :source_end
                )
                """
            ),
            {
                "cid": contract_id,
                "clause_type": clause.get("clause_type"),
                "original_text": clause.get("original_text", ""),
                "summary": clause.get("summary", ""),
                "risk_level": clause.get("risk_level", "low"),
                "risk_explanation": clause.get("risk_explanation", ""),
                "run_id": run_id,
                "extraction_method": clause.get("extraction_method"),
                "source_start": clause.get("source_start"),
                "source_end": clause.get("source_end"),
            },
        )


def _replace_alerts(db: Session, state: VEGAState) -> None:
    contract_id = state["contract_id"]
    existing = db.execute(
        text("SELECT id, alert_type, trigger_date FROM alerts WHERE contract_id = :cid"),
        {"cid": contract_id},
    ).fetchall()
    wanted = {
        (alert["alert_type"], alert["trigger_date"])
        for alert in state.get("alerts_to_create", [])
    }
    retained = set()
    for alert_id, alert_type, trigger_date in existing:
        key = (alert_type, trigger_date)
        if key in wanted and key not in retained:
            retained.add(key)
        else:
            db.execute(text("DELETE FROM alerts WHERE id = :id"), {"id": alert_id})
    for alert in state.get("alerts_to_create", []):
        key = (alert["alert_type"], alert["trigger_date"])
        if key in retained:
            continue
        retained.add(key)
        db.execute(
            text(
                """
                INSERT INTO alerts (contract_id, alert_type, trigger_date, is_resolved)
                VALUES (:cid, :alert_type, :trigger_date, 0)
                """
            ),
            {
                "cid": contract_id,
                "alert_type": alert.get("alert_type"),
                "trigger_date": alert.get("trigger_date"),
            },
        )


def _replace_negotiation_intel(db: Session, state: VEGAState) -> None:
    contract_id = state["contract_id"]
    db.execute(
        text("DELETE FROM negotiation_intel WHERE contract_id = :cid"),
        {"cid": contract_id},
    )
    for suggestion in state.get("negotiation_suggestions", []):
        db.execute(
            text(
                """
                INSERT INTO negotiation_intel (
                    contract_id, benchmark_type, market_rate, suggestion
                ) VALUES (:cid, :benchmark_type, :market_rate, :suggestion)
                """
            ),
            {
                "cid": contract_id,
                "benchmark_type": suggestion.get("benchmark_type", ""),
                "market_rate": suggestion.get("market_rate", ""),
                "suggestion": suggestion.get("suggestion", ""),
            },
        )


def _insert_analysis_evidence(db: Session, state: VEGAState, run_id: str) -> None:
    for evidence in state.get("analysis_evidence", []):
        confidence = evidence.get("confidence")
        if confidence is not None:
            confidence = min(1.0, max(0.0, float(confidence)))
        db.execute(
            text(
                """
                INSERT INTO analysis_evidence (
                    contract_id, analysis_run_id, field_name, normalized_value,
                    source_text, source_start, source_end,
                    extraction_method, confidence
                ) VALUES (
                    :contract_id, :run_id, :field_name, :normalized_value,
                    :source_text, :source_start, :source_end,
                    :extraction_method, :confidence
                )
                """
            ),
            {
                "contract_id": state["contract_id"],
                "run_id": run_id,
                "field_name": evidence["field_name"],
                "normalized_value": evidence.get("normalized_value"),
                "source_text": evidence["source_text"],
                "source_start": evidence.get("source_start"),
                "source_end": evidence.get("source_end"),
                "extraction_method": evidence.get("extraction_method", "heuristic"),
                "confidence": confidence,
            },
        )


def _record_unsuccessful_run(
    state: VEGAState,
    run_id: str,
    *,
    status: str,
    error_code: str,
    error_message: str,
) -> None:
    warnings_json = json.dumps(
        list(dict.fromkeys(state.get("analysis_warnings", []))),
        ensure_ascii=False,
    )
    extracted_chars = state.get("document_metadata", {}).get(
        "extracted_text_chars",
        len(state.get("raw_text", "")),
    )
    with get_db_context() as db:
        updated = db.execute(
            text(
                """
                UPDATE contracts
                SET analysis_status = :status,
                    analysis_error_code = :error_code,
                    analysis_error = :error_message,
                    analysis_completed_at = CURRENT_TIMESTAMP
                WHERE id = :contract_id
                  AND analysis_run_id = :run_id
                  AND analysis_status = 'processing'
                """
            ),
            {
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "contract_id": state["contract_id"],
                "run_id": run_id,
            },
        )
        if updated.rowcount == 1:
            db.execute(
                text(
                    """
                    UPDATE analysis_runs
                    SET status = :status,
                        completed_at = CURRENT_TIMESTAMP,
                        error_code = :error_code,
                        error_message = :error_message,
                        warnings_json = :warnings_json,
                        extracted_text_chars = :extracted_chars
                    WHERE id = :run_id
                    """
                ),
                {
                    "status": status,
                    "error_code": error_code,
                    "error_message": error_message,
                    "warnings_json": warnings_json,
                    "extracted_chars": extracted_chars,
                    "run_id": run_id,
                },
            )
        else:
            db.execute(
                text(
                    """
                    UPDATE analysis_runs
                    SET status = 'superseded', completed_at = CURRENT_TIMESTAMP
                    WHERE id = :run_id AND status IN ('queued', 'processing')
                    """
                ),
                {"run_id": run_id},
            )
        db.commit()


def _mark_run_superseded(run_id: str) -> None:
    with get_db_context() as db:
        db.execute(
            text(
                """
                UPDATE analysis_runs
                SET status = 'superseded', completed_at = CURRENT_TIMESTAMP
                WHERE id = :run_id AND status IN ('queued', 'processing')
                """
            ),
            {"run_id": run_id},
        )
        db.commit()


def _lifecycle_status(end_date: Optional[str]) -> str:
    if not end_date:
        return "active"
    try:
        return "expired" if datetime.strptime(end_date, "%Y-%m-%d").date() < date.today() else "active"
    except ValueError:
        return "active"
