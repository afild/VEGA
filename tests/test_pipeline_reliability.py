from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agents.orchestrator import (
    AnalysisAlreadyRunningError,
    analyze_contract_pipeline,
    queue_contract_analysis,
)
from app.database.db_manager import SessionLocal
from app.main import app
from app.utils.file_storage import get_contracts_storage_dir


client = TestClient(app)


def _make_pdf(lines: list[str], *, empty: bool = False) -> Path:
    storage_dir = get_contracts_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / f"pipeline-{uuid4().hex}.pdf"
    document = fitz.open()
    page = document.new_page()
    if not empty:
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + (index * 24)), line)
    document.save(path)
    document.close()
    return path


def _insert_contract(path: Path, title: str) -> int:
    db = SessionLocal()
    try:
        contract_id = db.execute(
            text(
                """
                INSERT INTO contracts (
                    title, file_path, status, health_score, analysis_status
                ) VALUES (
                    :title, :file_path, 'draft', NULL, 'not_started'
                ) RETURNING id
                """
            ),
            {"title": title, "file_path": str(path)},
        ).scalar_one()
        db.commit()
        return contract_id
    finally:
        db.close()


def _queue(contract_id: int, trigger: str = "manual") -> str:
    db = SessionLocal()
    try:
        run_id = queue_contract_analysis(db, contract_id, trigger)
        db.commit()
        return run_id
    finally:
        db.close()


def test_empty_pdf_requires_review_without_false_health_score():
    path = _make_pdf([], empty=True)
    contract_id = _insert_contract(path, f"Empty {uuid4().hex}")
    run_id = _queue(contract_id)

    result = analyze_contract_pipeline(contract_id, str(path), run_id)

    assert result["analysis_status"] == "needs_review"
    db = SessionLocal()
    try:
        contract = db.execute(
            text(
                """
                SELECT status, analysis_status, analysis_error_code,
                       health_score, analysis_revision
                FROM contracts WHERE id = :id
                """
            ),
            {"id": contract_id},
        ).one()
        run_status = db.execute(
            text("SELECT status FROM analysis_runs WHERE id = :run_id"),
            {"run_id": run_id},
        ).scalar_one()
    finally:
        db.close()

    assert contract[0] == "draft"
    assert contract[1] == "needs_review"
    assert contract[2] == "NO_EXTRACTABLE_TEXT"
    assert contract[3] is None
    assert contract[4] == 0
    assert run_status == "needs_review"


def test_successful_reanalysis_is_idempotent_and_failure_preserves_last_result():
    path = _make_pdf([
        "Effective Date: September 21, 2026.",
        "Expiration Date: September 21, 2027.",
        "The total contract value is USD 1,200.00, payable annually.",
        "This contract shall automatically renew unless either party gives 30 days prior written notice.",
        "Liability is limited solely to the amounts paid by the client.",
    ])
    contract_id = _insert_contract(path, f"Reliable {uuid4().hex}")

    first_run = _queue(contract_id)
    first_result = analyze_contract_pipeline(contract_id, str(path), first_run)
    assert first_result["analysis_status"] == "completed"

    db = SessionLocal()
    try:
        first_contract = db.execute(
            text(
                """
                SELECT status, analysis_status, health_score, financial_value,
                       payment_frequency, analysis_revision,
                       last_successful_run_id
                FROM contracts WHERE id = :id
                """
            ),
            {"id": contract_id},
        ).one()
        first_clause_count = db.execute(
            text("SELECT COUNT(*) FROM clauses WHERE contract_id = :id"),
            {"id": contract_id},
        ).scalar_one()
        evidence_fields = set(db.execute(
            text(
                "SELECT field_name FROM analysis_evidence "
                "WHERE contract_id = :id AND analysis_run_id = :run_id"
            ),
            {"id": contract_id, "run_id": first_run},
        ).scalars())
    finally:
        db.close()

    assert first_contract[0] == "active"
    assert first_contract[1] == "completed"
    assert first_contract[2] == 75.0
    assert first_contract[3] == 1200.0
    assert first_contract[4] == "annual"
    assert first_contract[5] == 1
    assert first_contract[6] == first_run
    assert first_clause_count >= 2
    assert {
        "start_date",
        "end_date",
        "financial_value",
        "financial_currency",
        "payment_frequency",
        "auto_renews",
        "renewal_notice_days",
    }.issubset(evidence_fields)

    db = SessionLocal()
    try:
        resolved_id = db.execute(
            text("SELECT id FROM alerts WHERE contract_id = :id LIMIT 1"),
            {"id": contract_id},
        ).scalar_one()
        db.execute(text("UPDATE alerts SET is_resolved = 1 WHERE id = :id"), {"id": resolved_id})
        db.commit()
    finally:
        db.close()

    second_run = _queue(contract_id)
    second_result = analyze_contract_pipeline(contract_id, str(path), second_run)
    assert second_result["analysis_status"] == "completed"

    db = SessionLocal()
    try:
        revision, last_successful_run = db.execute(
            text(
                "SELECT analysis_revision, last_successful_run_id "
                "FROM contracts WHERE id = :id"
            ),
            {"id": contract_id},
        ).one()
        second_clause_count = db.execute(
            text("SELECT COUNT(*) FROM clauses WHERE contract_id = :id"),
            {"id": contract_id},
        ).scalar_one()
        completed_runs = db.execute(
            text(
                "SELECT COUNT(*) FROM analysis_runs "
                "WHERE contract_id = :id AND status = 'completed'"
            ),
            {"id": contract_id},
        ).scalar_one()
    finally:
        db.close()

    assert revision == 2
    assert last_successful_run == second_run
    assert second_clause_count == first_clause_count
    assert completed_runs == 2
    db = SessionLocal()
    try:
        assert db.execute(
            text("SELECT is_resolved FROM alerts WHERE id = :id"),
            {"id": resolved_id},
        ).scalar_one() == 1
    finally:
        db.close()

    before_failure = client.get(f"/api/contracts/{contract_id}").json()
    path.unlink()
    failed_run = _queue(contract_id)
    failed_result = analyze_contract_pipeline(contract_id, str(path), failed_run)
    assert failed_result["analysis_status"] == "failed"

    after_failure = client.get(f"/api/contracts/{contract_id}").json()
    assert after_failure["analysis_status"] == "failed"
    assert after_failure["analysis_error_code"] == "DOCUMENT_NOT_FOUND"
    assert after_failure["analysis_revision"] == 2
    assert after_failure["health_score"] == before_failure["health_score"]
    assert after_failure["financial_value"] == before_failure["financial_value"]
    assert after_failure["clauses"] == before_failure["clauses"]
    assert after_failure["analysis_evidence"] == before_failure["analysis_evidence"]

    history = client.get(f"/api/contracts/{contract_id}/analysis-runs")
    assert history.status_code == 200
    assert [item["status"] for item in history.json()][:3] == [
        "failed",
        "completed",
        "completed",
    ]


def test_only_one_analysis_can_be_queued_per_contract():
    path = _make_pdf(["This contract is effective on 2026-09-21."])
    contract_id = _insert_contract(path, f"Concurrent {uuid4().hex}")
    run_id = _queue(contract_id)

    api_response = client.post(f"/api/contracts/{contract_id}/analyze")
    assert api_response.status_code == 409
    assert "andamento" in api_response.json()["detail"]

    db = SessionLocal()
    try:
        with pytest.raises(AnalysisAlreadyRunningError):
            queue_contract_analysis(db, contract_id, "manual")
        db.rollback()
    finally:
        db.close()

    result = analyze_contract_pipeline(contract_id, str(path), run_id)
    assert result["analysis_status"] == "completed"


def test_transaction_failure_rolls_back_all_derived_results(monkeypatch):
    import app.agents.orchestrator as orchestrator

    path = _make_pdf([
        "Termination requires 90 days prior notice.",
        "The contract value is USD 1200.00.",
    ])
    contract_id = _insert_contract(path, "Atomic results")
    analyze_contract_pipeline(contract_id, str(path), _queue(contract_id))
    before = client.get(f"/api/contracts/{contract_id}").json()

    def fail_after_clause_replacement(*args):
        raise RuntimeError("Simulated database write failure")

    monkeypatch.setattr(orchestrator, "_replace_negotiation_intel", fail_after_clause_replacement)
    result = analyze_contract_pipeline(contract_id, str(path), _queue(contract_id))
    after = client.get(f"/api/contracts/{contract_id}").json()
    assert result["analysis_status"] == "failed"
    assert after["analysis_revision"] == before["analysis_revision"] == 1
    assert after["clauses"] == before["clauses"]
    assert after["analysis_evidence"] == before["analysis_evidence"]
    assert after["health_score"] == before["health_score"]


def test_stale_run_cannot_overwrite_a_newer_run():
    from app.agents.orchestrator import (
        StaleAnalysisRunError,
        _mark_run_processing,
        save_analysis_to_db,
    )

    path = _make_pdf(["Termination requires 90 days prior notice."])
    contract_id = _insert_contract(path, "Run ownership")
    old_run = _queue(contract_id)
    old_state = analyze_contract_pipeline(contract_id, str(path), old_run)
    new_run = _queue(contract_id)
    assert _mark_run_processing(contract_id, new_run)

    with pytest.raises(StaleAnalysisRunError):
        save_analysis_to_db(old_state, old_run)
    db = SessionLocal()
    try:
        current = db.execute(
            text("SELECT analysis_run_id, analysis_status, analysis_revision FROM contracts WHERE id = :id"),
            {"id": contract_id},
        ).one()
    finally:
        db.close()
    assert tuple(current) == (new_run, "processing", 1)


def test_truncated_pdf_requires_review(monkeypatch):
    from app.config import settings

    path = _make_pdf(["Termination requires 90 days prior notice."])
    contract_id = _insert_contract(path, "Truncated document")
    monkeypatch.setattr(settings, "MAX_EXTRACTED_TEXT_CHARS", 10)
    result = analyze_contract_pipeline(contract_id, str(path), _queue(contract_id))
    detail = client.get(f"/api/contracts/{contract_id}").json()
    assert result["analysis_status"] == "needs_review"
    assert detail["health_score"] is None
    assert detail["analysis_error_code"] == "EXTRACTED_TEXT_TRUNCATED"


def test_no_target_clauses_does_not_mean_healthy():
    path = _make_pdf(["An unrelated piece of text with no contractual clauses."])
    contract_id = _insert_contract(path, "No target clauses")
    result = analyze_contract_pipeline(contract_id, str(path), _queue(contract_id))
    assert result["analysis_status"] == "completed"
    assert result["health_score"] is None
    assert "NO_TARGET_CLAUSES_FOUND" in result["analysis_warnings"]
