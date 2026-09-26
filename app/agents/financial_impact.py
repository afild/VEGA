import logging
import re
from typing import Any, Optional


MONEY_PATTERN = re.compile(
    r"(?P<currency>R\$|US\$|\$|USD|BRL)\s*"
    r"(?P<amount>(?:\d{1,3}(?:[.,\s]\d{3})+|\d+)(?:[.,]\d{2})?)",
    re.IGNORECASE,
)
MONEY_SUFFIX_PATTERN = re.compile(
    r"(?P<amount>(?:\d{1,3}(?:[.,\s]\d{3})+|\d+)(?:[.,]\d{2})?)\s*"
    r"(?P<currency>USD|BRL)\b",
    re.IGNORECASE,
)

FREQUENCY_TERMS = {
    "monthly": (
        "monthly",
        "per month",
        "every month",
        "mensalmente",
        "mensal",
        "por mês",
        "cada mês",
        "faturamento mensal",
    ),
    "annual": (
        "annually",
        "annual",
        "per year",
        "every year",
        "anualmente",
        "anual",
        "por ano",
        "faturamento anual",
    ),
    "one-time": (
        "one-time",
        "one time",
        "single payment",
        "upfront",
        "pagamento único",
        "parcela única",
        "à vista",
    ),
}


def run_financial_impact(state: dict) -> dict:
    """Extrai valor e frequência com evidência textual rastreável."""
    try:
        logging.info(
            "[Financial Impact] Analisando contrato ID: %s",
            state.get("contract_id"),
        )
        value, frequency, evidence, warnings = parse_financial_details_with_evidence(
            state.get("raw_text", "")
        )

        state["financial_value"] = value
        state["financial_currency"] = next(
            (
                item["normalized_value"]
                for item in evidence
                if item["field_name"] == "financial_currency"
            ),
            None,
        )
        state["payment_frequency"] = frequency
        state.setdefault("analysis_evidence", []).extend(evidence)
        _extend_unique(state.setdefault("analysis_warnings", []), warnings)
        state.setdefault("completed_steps", []).append("financial_impact")

        logging.info(
            "[Financial Impact] Concluído. Valor=%s; frequência=%s.",
            value,
            frequency,
        )
        return state
    except Exception:
        logging.exception("[Financial Impact] Falha no agente financeiro.")
        state.setdefault("risk_flags", []).append("FINANCIAL_IMPACT_FAILED")
        return state


def parse_financial_details(text: str) -> tuple[Optional[float], str]:
    """Interface compatível que retorna apenas valor e frequência."""
    value, frequency, _, _ = parse_financial_details_with_evidence(text)
    return value, frequency


def parse_financial_details_with_evidence(
    text: str,
) -> tuple[Optional[float], str, list[dict[str, Any]], list[str]]:
    """Seleciona a ocorrência monetária mais relevante sem estimar valores."""
    if not text:
        return None, "unknown", [], ["FINANCIAL_VALUE_NOT_FOUND"]

    candidates: list[dict[str, Any]] = []
    matches = list(MONEY_PATTERN.finditer(text))
    occupied = [match.span() for match in matches]
    for suffix_match in MONEY_SUFFIX_PATTERN.finditer(text):
        if not any(
            suffix_match.start() < end and suffix_match.end() > start
            for start, end in occupied
        ):
            matches.append(suffix_match)

    for match in sorted(matches, key=lambda item: item.start()):
        value = _parse_amount(match.group("amount"))
        if value is None or value < 0:
            continue

        context = _financial_sentence_context(text, match.start(), match.end())
        score = _financial_context_score(context)
        candidates.append(
            {
                "value": value,
                "start": match.start(),
                "end": match.end(),
                "source_text": match.group(0),
                "currency": _normalize_currency(match.group("currency")),
                "score": score,
                "confidence": _financial_confidence(score),
            }
        )

    if not candidates:
        return None, "unknown", [], ["FINANCIAL_VALUE_NOT_FOUND"]

    # Contexto contratual explícito prevalece sobre simplesmente escolher o
    # maior número, que pode ser multa, seguro ou limite de responsabilidade.
    selected = max(candidates, key=lambda item: (item["score"], item["value"]))
    if selected["score"] < 0:
        return None, "unknown", [], ["FINANCIAL_VALUE_NOT_FOUND"]
    warnings: list[str] = []
    if len(candidates) > 1:
        warnings.append("MULTIPLE_FINANCIAL_VALUES_FOUND")

    frequency, frequency_evidence, frequency_warnings = _extract_frequency(
        text,
        selected["start"],
        selected["end"],
    )
    warnings.extend(frequency_warnings)

    evidence: list[dict[str, Any]] = [
        {
            "field_name": "financial_value",
            "normalized_value": f"{selected['value']:.2f}",
            "source_text": selected["source_text"],
            "source_start": selected["start"],
            "source_end": selected["end"],
            "extraction_method": "currency_regex_context",
            "confidence": selected["confidence"],
        }
    ]
    evidence.append({
        "field_name": "financial_currency",
        "normalized_value": selected["currency"],
        "source_text": selected["source_text"],
        "source_start": selected["start"],
        "source_end": selected["end"],
        "extraction_method": "currency_symbol_regex",
        "confidence": 0.99,
    })
    if frequency_evidence:
        evidence.append(frequency_evidence)
    elif frequency == "unknown":
        warnings.append("PAYMENT_FREQUENCY_NOT_FOUND")

    return selected["value"], frequency, evidence, list(dict.fromkeys(warnings))


def _parse_amount(raw_amount: str) -> Optional[float]:
    cleaned = raw_amount.replace(" ", "")
    try:
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") < cleaned.rfind("."):
                cleaned = cleaned.replace(",", "")
            else:
                cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            parts = cleaned.split(",")
            cleaned = (
                cleaned.replace(",", ".")
                if len(parts) == 2 and len(parts[1]) == 2
                else cleaned.replace(",", "")
            )
        elif "." in cleaned:
            parts = cleaned.split(".")
            if not (len(parts) == 2 and len(parts[1]) == 2):
                cleaned = cleaned.replace(".", "")
        return float(cleaned)
    except ValueError:
        return None


def _normalize_currency(raw_currency: str) -> str:
    return "BRL" if raw_currency.upper() in {"R$", "BRL"} else "USD"


def _financial_context_score(context: str) -> int:
    score = 0
    positive_terms = {
        "total contract value": 8,
        "contract value": 7,
        "valor total do contrato": 8,
        "valor do contrato": 7,
        "total fee": 5,
        "service fee": 4,
        "subscription fee": 4,
        "monthly fee": 4,
        "annual fee": 4,
        "preço": 3,
        "pagamento": 3,
        "payment": 3,
        "fee": 2,
    }
    negative_terms = {
        "penalty": -6,
        "multa": -6,
        "liability": -5,
        "responsabilidade": -5,
        "insurance": -4,
        "seguro": -4,
        "damages": -4,
        "indenização": -4,
    }
    for term, weight in positive_terms.items():
        if term in context:
            score += weight
    for term, weight in negative_terms.items():
        if term in context:
            score += weight
    return score


def _financial_sentence_context(text: str, start: int, end: int) -> str:
    """Limita o contexto à oração do valor para não herdar rótulos vizinhos."""
    left_boundaries = [text.rfind(separator, 0, start) for separator in (".", "\n", ";")]
    sentence_start = max(left_boundaries) + 1
    right_boundaries = [
        position
        for separator in (".", "\n", ";")
        if (position := text.find(separator, end)) >= 0
    ]
    sentence_end = min(right_boundaries) if right_boundaries else len(text)
    return text[sentence_start:sentence_end].casefold()


def _financial_confidence(score: int) -> float:
    if score >= 7:
        return 0.95
    if score >= 3:
        return 0.8
    if score > 0:
        return 0.7
    return 0.55


def _extract_frequency(
    text: str,
    amount_start: int,
    amount_end: int,
) -> tuple[str, Optional[dict[str, Any]], list[str]]:
    text_lower = text.casefold()
    radius_start = max(0, amount_start - 180)
    radius_end = min(len(text), amount_end + 180)
    occurrences: list[tuple[int, str, int, int, str]] = []

    for frequency, terms in FREQUENCY_TERMS.items():
        for term in terms:
            search_at = radius_start
            while True:
                position = text_lower.find(term, search_at, radius_end)
                if position < 0:
                    break
                term_end = position + len(term)
                distance = min(
                    abs(amount_start - term_end),
                    abs(position - amount_end),
                )
                occurrences.append((distance, frequency, position, term_end, text[position:term_end]))
                search_at = term_end

    if not occurrences:
        return "unknown", None, []

    occurrences.sort(key=lambda item: item[0])
    selected = occurrences[0]
    distinct_frequencies = {item[1] for item in occurrences}
    warnings = (
        ["MULTIPLE_PAYMENT_FREQUENCIES_FOUND"]
        if len(distinct_frequencies) > 1
        else []
    )

    # Preço mensal e cobrança anual não representam a mesma base financeira.
    # A distância textual não resolve esse conflito sem interpretação humana.
    if len(distinct_frequencies) > 1:
        return "unknown", None, warnings

    evidence = {
        "field_name": "payment_frequency",
        "normalized_value": selected[1],
        "source_text": selected[4],
        "source_start": selected[2],
        "source_end": selected[3],
        "extraction_method": "nearest_frequency_term",
        "confidence": 0.85 if len(distinct_frequencies) == 1 else 0.7,
    }
    return selected[1], evidence, warnings


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)
