import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

from app.config import settings


@dataclass(frozen=True)
class DateCandidate:
    value: date
    start: int
    end: int
    source_text: str
    method: str
    confidence: float


MONTHS = {
    "january": 1,
    "jan": 1,
    "janeiro": 1,
    "fevereiro": 2,
    "february": 2,
    "feb": 2,
    "fev": 2,
    "march": 3,
    "marco": 3,
    "mar": 3,
    "april": 4,
    "abril": 4,
    "apr": 4,
    "abr": 4,
    "may": 5,
    "maio": 5,
    "mai": 5,
    "june": 6,
    "junho": 6,
    "jun": 6,
    "july": 7,
    "julho": 7,
    "jul": 7,
    "august": 8,
    "agosto": 8,
    "aug": 8,
    "ago": 8,
    "september": 9,
    "setembro": 9,
    "sep": 9,
    "sept": 9,
    "set": 9,
    "october": 10,
    "outubro": 10,
    "oct": 10,
    "out": 10,
    "november": 11,
    "novembro": 11,
    "nov": 11,
    "december": 12,
    "dezembro": 12,
    "dec": 12,
    "dez": 12,
}

MONTH_PATTERN = "|".join(
    sorted(
        {"março", "marco", *MONTHS.keys()},
        key=len,
        reverse=True,
    )
)
ISO_DATE_PATTERN = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
NUMERIC_DATE_PATTERN = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
MONTH_FIRST_PATTERN = re.compile(
    rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
DAY_FIRST_PATTERN = re.compile(
    rf"\b(\d{{1,2}})\s+(?:de\s+)?({MONTH_PATTERN})(?:\s+de)?\s+(\d{{4}})\b",
    re.IGNORECASE,
)

START_KEYWORDS = (
    "effective date",
    "effective on",
    "commencement date",
    "commences on",
    "starts on",
    "start date",
    "data de inicio",
    "inicio da vigencia",
    "vigencia inicia",
    "entra em vigor",
    "celebrado em",
    "assinado em",
)
END_KEYWORDS = (
    "expiration date",
    "expires on",
    "expire on",
    "termination date",
    "terminates on",
    "ends on",
    "end date",
    "valid until",
    "data de termino",
    "termino da vigencia",
    "data de vencimento",
    "vence em",
    "valido ate",
)


def run_alert_calendar(state: dict) -> dict:
    """Extrai datas/prazos, registra evidências e agenda alertas futuros."""
    try:
        logging.info(
            "[Alert Calendar] Processando contrato ID: %s",
            state.get("contract_id"),
        )
        raw_text = state.get("raw_text", "")

        start_date, end_date, date_evidence, date_warnings = extract_dates_with_evidence(
            raw_text
        )
        auto_renews, renewal_evidence = extract_auto_renewal_with_evidence(raw_text)
        notice_days, notice_evidence = extract_notice_days_with_evidence(raw_text)

        state["start_date"] = start_date
        state["end_date"] = end_date
        state["auto_renews"] = (
            None if auto_renews is None else (1 if auto_renews else 0)
        )
        state["renewal_notice_days"] = notice_days
        state["alerts_to_create"] = []

        evidence = date_evidence.copy()
        if renewal_evidence:
            evidence.append(renewal_evidence)
        if notice_evidence:
            evidence.append(notice_evidence)
        state.setdefault("analysis_evidence", []).extend(evidence)

        warnings = state.setdefault("analysis_warnings", [])
        _extend_unique(warnings, date_warnings)
        if auto_renews is None:
            _extend_unique(warnings, ["AUTO_RENEWAL_NOT_FOUND"])
        if notice_days is None:
            _extend_unique(warnings, ["NOTICE_PERIOD_NOT_FOUND"])

        if end_date:
            end_value = datetime.strptime(end_date, "%Y-%m-%d").date()
            _schedule_alerts(state, end_value, auto_renews, notice_days)

        state.setdefault("completed_steps", []).append("alert_calendar")
        return state
    except Exception:
        logging.exception("[Alert Calendar] Falha no agente de datas e alertas.")
        state.setdefault("risk_flags", []).append("ALERT_CALENDAR_FAILED")
        return state


def extract_dates_from_text(text: str) -> tuple[Optional[str], Optional[str]]:
    """Interface compatível que retorna somente início e término."""
    start_date, end_date, _, _ = extract_dates_with_evidence(text)
    return start_date, end_date


def extract_dates_with_evidence(
    text: str,
) -> tuple[Optional[str], Optional[str], list[dict[str, Any]], list[str]]:
    """Extrai apenas datas válidas com função contratual sustentada pelo contexto."""
    if not text:
        return None, None, [], ["CONTRACT_DATES_NOT_FOUND"]

    candidates, warnings = _date_candidates(text)
    if not candidates:
        return None, None, [], list(dict.fromkeys([*warnings, "CONTRACT_DATES_NOT_FOUND"]))

    folded_text = _fold(text)
    classified: dict[str, list[tuple[int, DateCandidate]]] = {
        "start_date": [],
        "end_date": [],
    }
    unclassified: list[DateCandidate] = []

    for candidate in candidates:
        start_distance = _nearest_keyword_distance(
            folded_text, candidate.start, candidate.end, START_KEYWORDS
        )
        end_distance = _nearest_keyword_distance(
            folded_text, candidate.start, candidate.end, END_KEYWORDS
        )
        if start_distance is None and end_distance is None:
            unclassified.append(candidate)
        elif end_distance is None or (
            start_distance is not None and start_distance < end_distance
        ):
            classified["start_date"].append((start_distance or 0, candidate))
        else:
            classified["end_date"].append((end_distance or 0, candidate))

    _classify_date_ranges(text, unclassified, classified)
    start_candidate = _select_classified_candidate(
        classified["start_date"], "MULTIPLE_START_DATES_FOUND", warnings
    )
    end_candidate = _select_classified_candidate(
        classified["end_date"], "MULTIPLE_END_DATES_FOUND", warnings
    )

    if start_candidate and end_candidate and start_candidate.value > end_candidate.value:
        warnings.append("INVALID_CONTRACT_DATE_RANGE")
        return None, None, [], list(dict.fromkeys(warnings))

    evidence: list[dict[str, Any]] = []
    if start_candidate:
        evidence.append(_date_evidence("start_date", start_candidate))
    if end_candidate:
        evidence.append(_date_evidence("end_date", end_candidate))
    if not start_candidate and not end_candidate:
        warnings.append("CONTRACT_DATES_NOT_CONTEXTUALIZED")

    return (
        start_candidate.value.isoformat() if start_candidate else None,
        end_candidate.value.isoformat() if end_candidate else None,
        evidence,
        list(dict.fromkeys(warnings)),
    )


def detect_auto_renewal(text: str) -> bool:
    """Retorna verdadeiro somente quando há renovação automática afirmativa."""
    value, _ = extract_auto_renewal_with_evidence(text)
    return value is True


def extract_auto_renewal_with_evidence(
    text: str,
) -> tuple[Optional[bool], Optional[dict[str, Any]]]:
    pattern = re.compile(
        r"automatic(?:ally)?\s+renew(?:al|ed|s)?|auto-renew(?:al)?|"
        r"renew(?:ed|s)?\s+automatically|renova(?:ção|do|r)?\s+autom[aá]tica(?:mente)?|"
        r"prorroga(?:ção|do)?\s+autom[aá]tica(?:mente)?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None, None

    lookback = _fold(text[max(0, match.start() - 35):match.start()])
    negated = bool(re.search(r"\b(?:not|no|never|nao|nunca)\b", lookback))
    value = not negated
    return value, {
        "field_name": "auto_renews",
        "normalized_value": "true" if value else "false",
        "source_text": text[match.start():match.end()],
        "source_start": match.start(),
        "source_end": match.end(),
        "extraction_method": "renewal_phrase_context",
        "confidence": 0.9 if negated else 0.95,
    }


def extract_notice_days(text: str) -> Optional[int]:
    """Retorna o aviso prévio expresso; não aplica valor padrão inventado."""
    value, _ = extract_notice_days_with_evidence(text)
    return value


def extract_notice_days_with_evidence(
    text: str,
) -> tuple[Optional[int], Optional[dict[str, Any]]]:
    patterns = (
        re.compile(
            r"\b(\d{1,3})\s*(?:calendar\s+|business\s+|úteis\s+)?(?:days|dias)\s+"
            r"(?:prior(?:\s+written)?\s+notice|before|notice|de antecedência|"
            r"de aviso(?:\s+prévio)?|aviso prévio)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:notice|aviso(?:\s+prévio)?)\s+(?:of|de)\s+(\d{1,3})\s*(?:days|dias)\b",
            re.IGNORECASE,
        ),
    )
    matches = [match for pattern in patterns if (match := pattern.search(text))]
    if not matches:
        return None, None

    match = min(matches, key=lambda item: item.start())
    value = int(match.group(1))
    if value <= 0 or value > 365:
        return None, None
    return value, {
        "field_name": "renewal_notice_days",
        "normalized_value": str(value),
        "source_text": text[match.start():match.end()],
        "source_start": match.start(),
        "source_end": match.end(),
        "extraction_method": "notice_period_regex",
        "confidence": 0.95,
    }


def _date_candidates(text: str) -> tuple[list[DateCandidate], list[str]]:
    candidates: list[DateCandidate] = []
    occupied: list[tuple[int, int]] = []
    warnings: list[str] = []

    def add_candidate(match: re.Match[str], value: date, method: str, confidence: float) -> None:
        span = match.span()
        if any(span[0] < end and span[1] > start for start, end in occupied):
            return
        occupied.append(span)
        candidates.append(
            DateCandidate(value, span[0], span[1], match.group(0), method, confidence)
        )

    for match in ISO_DATE_PATTERN.finditer(text):
        year, month, day = map(int, match.groups())
        try:
            add_candidate(match, date(year, month, day), "iso_date_regex", 0.99)
        except ValueError:
            warnings.append("INVALID_DATE_IGNORED")

    for pattern, month_first in (
        (MONTH_FIRST_PATTERN, True),
        (DAY_FIRST_PATTERN, False),
    ):
        for match in pattern.finditer(text):
            if month_first:
                month_name, day_raw, year_raw = match.groups()
            else:
                day_raw, month_name, year_raw = match.groups()
            month = MONTHS.get(_fold(month_name))
            try:
                if month is not None:
                    add_candidate(
                        match,
                        date(int(year_raw), month, int(day_raw)),
                        "written_date_regex",
                        0.98,
                    )
            except ValueError:
                warnings.append("INVALID_DATE_IGNORED")

    for match in NUMERIC_DATE_PATTERN.finditer(text):
        first, second, year = map(int, match.groups())
        try:
            if first > 12 and second <= 12:
                value = date(year, second, first)
            elif second > 12 and first <= 12:
                value = date(year, first, second)
            elif first == second:
                value = date(year, second, first)
            else:
                warnings.append("AMBIGUOUS_NUMERIC_DATE_IGNORED")
                continue
            add_candidate(match, value, "unambiguous_numeric_date_regex", 0.9)
        except ValueError:
            warnings.append("INVALID_DATE_IGNORED")

    candidates.sort(key=lambda candidate: candidate.start)
    return candidates, warnings


def _nearest_keyword_distance(
    folded_text: str,
    start: int,
    end: int,
    keywords: tuple[str, ...],
) -> Optional[int]:
    distances: list[int] = []
    before_start = max(0, start - 140)
    after_end = min(len(folded_text), end + 55)
    for keyword in keywords:
        folded_keyword = _fold(keyword)
        before_position = folded_text.rfind(folded_keyword, before_start, start)
        if before_position >= 0:
            distances.append(start - (before_position + len(folded_keyword)))
        after_position = folded_text.find(folded_keyword, end, after_end)
        if after_position >= 0:
            # Rótulos anteriores ("Effective Date: ...") são muito mais
            # comuns e específicos. Ainda aceitamos rótulo posterior, mas com
            # penalidade para ele não capturar a data da frase anterior.
            distances.append((after_position - end) + 40)
    return min(distances) if distances else None


def _classify_date_ranges(
    text: str,
    candidates: list[DateCandidate],
    classified: dict[str, list[tuple[int, DateCandidate]]],
) -> None:
    for first, second in zip(candidates, candidates[1:]):
        between = _fold(text[first.end:second.start])
        before = _fold(text[max(0, first.start - 60):first.start])
        connector = re.search(r"\b(?:to|through|until|ate)\b", between)
        range_lead = re.search(r"\b(?:from|period|term|vigencia|de)\b", before)
        if connector and range_lead:
            classified["start_date"].append((80, first))
            classified["end_date"].append((80, second))


def _select_classified_candidate(
    values: list[tuple[int, DateCandidate]],
    warning: str,
    warnings: list[str],
) -> Optional[DateCandidate]:
    if not values:
        return None
    unique = {(candidate.start, candidate.end): (distance, candidate) for distance, candidate in values}
    ranked = sorted(unique.values(), key=lambda item: (item[0], item[1].start))
    if len(ranked) > 1:
        warnings.append(warning)
    return ranked[0][1]


def _date_evidence(field_name: str, candidate: DateCandidate) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "normalized_value": candidate.value.isoformat(),
        "source_text": candidate.source_text,
        "source_start": candidate.start,
        "source_end": candidate.end,
        "extraction_method": candidate.method,
        "confidence": candidate.confidence,
    }


def _schedule_alerts(
    state: dict,
    end_date: date,
    auto_renews: Optional[bool],
    notice_days: Optional[int],
) -> None:
    today = datetime.now().date()
    alerts: list[tuple[str, date]] = [("expiration", end_date)]

    if auto_renews is True:
        if notice_days is None:
            _extend_unique(
                state.setdefault("analysis_warnings", []),
                ["RENEWAL_DEADLINE_UNAVAILABLE"],
            )
        else:
            cancellation_deadline = end_date - timedelta(days=notice_days)
            alerts.extend(
                (f"renewal_{days}d", cancellation_deadline - timedelta(days=days))
                for days in (90, 60, 30)
            )
    else:
        alerts.extend(
            (f"expiration_{days}d", end_date - timedelta(days=days))
            for days in (90, 60, 30)
        )

    state["alerts_to_create"] = [
        {"alert_type": alert_type, "trigger_date": trigger_date.isoformat()}
        for alert_type, trigger_date in alerts
        if trigger_date >= today
    ]
    logging.info(
        "[Alert Calendar] Agendados %s alertas futuros.",
        len(state["alerts_to_create"]),
    )


def notify_alert_webhook(state: dict) -> None:
    """Notifica somente depois que o orquestrador confirma o commit da análise."""
    if not settings.SLACK_WEBHOOK_URL or not state.get("alerts_to_create"):
        return
    try:
        lines = [
            f"🔔 Novos alertas de contrato agendados! (ID: {state.get('contract_id')})"
        ]
        lines.extend(
            f" - {alert['alert_type']} em {alert['trigger_date']}"
            for alert in state["alerts_to_create"]
        )
        response = httpx.post(
            settings.SLACK_WEBHOOK_URL,
            json={"text": "\n".join(lines)},
            timeout=5.0,
        )
        response.raise_for_status()
    except Exception:
        logging.exception("[Alert Calendar] Falha ao enviar webhook de alertas.")
        _extend_unique(
            state.setdefault("analysis_warnings", []),
            ["ALERT_WEBHOOK_FAILED"],
        )


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)
