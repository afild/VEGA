import re
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional

def run_alert_calendar(state: dict) -> dict:
    """
    Agente de Alertas e Calendário.
    Extrai as datas críticas do contrato (start_date, end_date), notice days e se renova automaticamente.
    Calcula os alertas de renovação/expiração (90d, 60d, 30d antes do limite de cancelamento).
    Regra estrita anti-alucinação: datas são validadas contra regex no texto do documento.
    """
    logging.info(f"[Alert Calendar] Processando datas e alertas para o contrato ID: {state.get('contract_id')}")
    
    raw_text = state.get("raw_text", "")
    
    # Executa a extração heurística/regex de datas
    start_date, end_date = extract_dates_from_text(raw_text)
    auto_renews = detect_auto_renewal(raw_text)
    notice_days = extract_notice_days(raw_text)
    
    # Salva no estado
    state["start_date"] = start_date
    state["end_date"] = end_date
    state["auto_renews"] = 1 if auto_renews else 0
    state["renewal_notice_days"] = notice_days
    
    state["alerts_to_create"] = []
    
    if end_date:
        try:
            # Converte end_date (string YYYY-MM-DD) para objeto date
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
            today = datetime.now().date()
            
            # Prazo limite para notificar o cancelamento
            cancel_deadline = end_dt - timedelta(days=notice_days)
            
            # Tipos de alerta e datas de trigger
            alerts_config = [
                ("renewal_90d", cancel_deadline - timedelta(days=90)),
                ("renewal_60d", cancel_deadline - timedelta(days=60)),
                ("renewal_30d", cancel_deadline - timedelta(days=30)),
                ("expiration", end_dt)
            ]
            
            for alert_type, trigger_date in alerts_config:
                # Apenas criamos alertas no futuro
                if trigger_date >= today:
                    state["alerts_to_create"].append({
                        "alert_type": alert_type,
                        "trigger_date": trigger_date.strftime("%Y-%m-%d")
                    })
            
            logging.info(f"[Alert Calendar] Agendados {len(state['alerts_to_create'])} alertas futuros.")
        except Exception as e:
            logging.error(f"[Alert Calendar] Erro ao calcular datas de alertas: {e}")
            
    state["completed_steps"].append("alert_calendar")
    return state


def extract_dates_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Usa regex para buscar datas de início e término no texto do contrato.
    Garante que a data venha do texto original (critério anti-alucinação).
    """
    if not text:
        return None, None
        
    # Expressões regulares para vários formatos de datas comuns:
    # 1. YYYY-MM-DD
    # 2. DD/MM/YYYY ou MM/DD/YYYY
    # 3. Formato escrito: Month DD, YYYY ou DD de Month de YYYY
    
    # Padrão numérico genérico: dd/mm/aaaa ou mm/dd/aaaa
    numeric_date_regex = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
    # Padrão YYYY-MM-DD
    iso_date_regex = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
    
    months_en = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
                 "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    months_pt = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
                 "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    
    all_months = months_en + months_pt
    months_pattern = "|".join(all_months)
    
    # Padrão extenso: "December 31, 2026" ou "31 de dezembro de 2026" ou "December 31st, 2026"
    written_date_regex = re.compile(
        r"\b(\d{1,2})?(?:\s*(?:de|of)?\s*)?(" + months_pattern + r")\s*(?:\d{1,2}(?:st|nd|rd|th)?)?,?\s*(?:de|of|,)?,?\s*(\d{4})\b", 
        re.IGNORECASE
    )

    all_dates = []
    
    # 1. Procura datas numéricas ISO (YYYY-MM-DD)
    for match in iso_date_regex.finditer(text):
        y, m, d = match.groups()
        try:
            dt = datetime(int(y), int(m), int(d)).date()
            all_dates.append((match.start(), dt))
        except ValueError:
            continue
            
    # 2. Procura datas numéricas padrão (DD/MM/YYYY ou MM/DD/YYYY)
    for match in numeric_date_regex.finditer(text):
        p1, p2, y = match.groups()
        # Tentamos interpretar como DD/MM/YYYY primeiro, depois MM/DD/YYYY
        dt = None
        try:
            dt = datetime(int(y), int(p2), int(p1)).date() # DD/MM/YYYY
        except ValueError:
            try:
                dt = datetime(int(y), int(p1), int(p2)).date() # MM/DD/YYYY
            except ValueError:
                pass
        if dt:
            all_dates.append((match.start(), dt))
            
    # 3. Procura datas por extenso
    for match in written_date_regex.finditer(text):
        day_str, month_str, year_str = match.groups()
        day = int(day_str) if day_str else 1
        
        # Mapeia mês para número
        month_lower = month_str.lower()
        month_idx = 1
        for idx, m in enumerate(months_en):
            if m in month_lower:
                month_idx = (idx % 12) + 1
                break
        for idx, m in enumerate(months_pt):
            if m in month_lower:
                month_idx = (idx % 12) + 1
                break
                
        try:
            dt = datetime(int(year_str), month_idx, day).date()
            all_dates.append((match.start(), dt))
        except ValueError:
            continue
            
    # Classifica as datas encontradas com base no contexto textual
    if not all_dates:
        return None, None
        
    # Ordena datas por posição de aparecimento no documento
    all_dates.sort(key=lambda x: x[0])
    
    start_date_str = None
    end_date_str = None
    
    # Heurística simples: se encontramos duas ou mais datas
    # A primeira data que vem depois de palavras de início é start_date
    # A primeira data que vem depois de palavras de término é end_date
    # Se não houver contexto claro, assumimos que a menor data é o início e a maior é o término.
    
    start_keywords = ["effective", "commence", "start", "início", "começo", "vigência", "celebrado", "assinado"]
    end_keywords = ["expire", "terminate", "end", "expiration", "término", "fim", "vence", "vencimento", "valido ate", "válido até"]
    
    start_dt = None
    end_dt = None
    
    for idx, dt in all_dates:
        # Pega a janela de texto anterior a data (100 caracteres)
        context = text[max(0, idx - 100):idx].lower()
        
        is_start = any(k in context for k in start_keywords)
        is_end = any(k in context for k in end_keywords)
        
        if is_start and not start_dt:
            start_dt = dt
        elif is_end and not end_dt:
            end_dt = dt
            
    # Fallback se a heurística de contexto falhar
    extracted_dts = [d[1] for d in all_dates]
    if not start_dt and extracted_dts:
        start_dt = min(extracted_dts)
    if not end_dt and extracted_dts:
        # Se houver apenas uma data e ela for no futuro, pode ser o end_date
        if len(extracted_dts) == 1:
            if extracted_dts[0] > datetime.now().date():
                end_dt = extracted_dts[0]
                start_dt = None
        else:
            end_dt = max(extracted_dts)
            
    # Se start e end forem iguais, não faz sentido
    if start_dt == end_dt and len(extracted_dts) > 1:
        end_dt = max(extracted_dts)
        start_dt = min(extracted_dts)

    if start_dt:
        start_date_str = start_dt.strftime("%Y-%m-%d")
    if end_dt:
        end_date_str = end_dt.strftime("%Y-%m-%d")
        
    return start_date_str, end_date_str


def detect_auto_renewal(text: str) -> bool:
    """Detecta se o contrato renova automaticamente."""
    terms = ["automatic renew", "auto-renew", "renovação automática", "automatically renew", "renova automaticamente", "renovado automaticamente"]
    text_lower = text.lower()
    return any(term in text_lower for term in terms)


def extract_notice_days(text: str) -> int:
    """Extrai o número de dias de aviso prévio para cancelamento (default 30)."""
    text_lower = text.lower()
    
    # Procura por padrões do tipo: "30 days prior notice", "60 dias de antecedência"
    pattern = re.compile(
        r"(\d{2,3})\s*(?:days|dias)\s*(?:prior|before|notice|written notice|de antecedência|aviso prévio|de aviso)", 
        re.IGNORECASE
    )
    
    match = pattern.search(text_lower)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
            
    return 30  # Default regulamentar do SDD
