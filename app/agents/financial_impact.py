import re
import logging
from typing import Tuple, Optional

def run_financial_impact(state: dict) -> dict:
    """
    Agente de Impacto Financeiro.
    Vasculha o texto bruto do contrato em busca de valores financeiros e frequências de pagamento.
    Regra estrita anti-alucinação: se nenhum valor financeiro claro for encontrado, preenche com None (NULL no SQLite) ou 0.0.
    """
    logging.info(f"[Financial Impact] Analisando impacto financeiro do contrato ID: {state.get('contract_id')}")
    
    raw_text = state.get("raw_text", "")
    
    financial_value, payment_frequency = parse_financial_details(raw_text)
    
    state["financial_value"] = financial_value
    state["payment_frequency"] = payment_frequency
    state["completed_steps"].append("financial_impact")
    
    logging.info(f"[Financial Impact] Concluído. Valor extraído: {financial_value}, Frequência: {payment_frequency}")
    return state

def parse_financial_details(text: str) -> Tuple[Optional[float], str]:
    """
    Analisa o texto do contrato com regex para encontrar valores financeiros e termos de recorrência.
    """
    if not text:
        return None, "unknown"
        
    # Regex para capturar valores monetários ($1,000, $15000.00, USD 5000, R$ 2.000,00)
    # Suporta vírgula/ponto para milhares e decimais
    currency_regex = re.compile(
        r"(?:\$|USD|R\$)\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)", 
        re.IGNORECASE
    )
    
    matches = currency_regex.findall(text)
    
    # Processa os valores encontrados
    parsed_values = []
    for match_str in matches:
        try:
            # Limpa caracteres de milhares e converte para float
            # Se tiver vírgula e ponto, tratamos de acordo (ex: 1,500.00 -> 1500.00 ou 1.500,00 -> 1500.00)
            cleaned = match_str.replace(" ", "")
            if "," in cleaned and "." in cleaned:
                # Caso clássico americano: 1,000.00
                if cleaned.find(",") < cleaned.find("."):
                    cleaned = cleaned.replace(",", "")
                # Caso brasileiro: 1.000,00
                else:
                    cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                # Apenas vírgula: se tiver 2 casas decimais após a vírgula, tratamos como decimal (ex: 150,00)
                parts = cleaned.split(",")
                if len(parts) == 2 and len(parts[1]) == 2:
                    cleaned = cleaned.replace(",", ".")
                else:
                    cleaned = cleaned.replace(",", "")
            elif "." in cleaned:
                # Apenas ponto: se tiver 2 casas decimais após o ponto, mantemos. Senão, removemos (ex: 1.000)
                parts = cleaned.split(".")
                if len(parts) == 2 and len(parts[1]) == 2:
                    pass
                else:
                    cleaned = cleaned.replace(".", "")
            
            val = float(cleaned)
            # Ignora valores irrisórios (como taxas de centavos ou referências a leis)
            if val > 5.0:
                parsed_values.append(val)
        except ValueError:
            continue
            
    # Regra Anti-Alucinação: se não encontrou nenhum valor coerente, define como None
    financial_value = None
    if parsed_values:
        # Pega o maior valor (geralmente representa o valor total do contrato ou teto de despesa)
        # Se for um contrato de fornecimento mensal de $500, o maior valor pode ser a multa ou o limite anual,
        # mas as heurísticas de regex buscam extrair o valor de referência principal.
        # Em abordagens normais de CLM, o valor de referência é o valor máximo expresso.
        financial_value = max(parsed_values)

    # Identifica a frequência
    payment_frequency = "one-time"
    text_lower = text.lower()
    
    monthly_terms = ["monthly", "per month", "every month", "mensal", "por mês", "cada mês", "faturamento mensal", "monthly payment"]
    annual_terms = ["annual", "annually", "per year", "every year", "anual", "por ano", "anualmente", "annual payment"]
    
    is_monthly = any(term in text_lower for term in monthly_terms)
    is_annual = any(term in text_lower for term in annual_terms)
    
    if is_monthly:
        payment_frequency = "monthly"
    elif is_annual:
        payment_frequency = "annual"
    else:
        # Se contiver recorrência mas não soubermos qual, mantemos unknown
        if "recurring" in text_lower or "recorrente" in text_lower:
            payment_frequency = "unknown"
            
    return financial_value, payment_frequency
