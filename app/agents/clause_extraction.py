import json
import logging
import re
from typing import List, Dict, Any
from app.config import settings

def run_clause_extraction(state: dict) -> dict:
    """
    Agente de Extração de Cláusulas.
    Identifica cláusulas críticas (Termination, Auto-renewal, Liability Cap) no raw_text.
    Usa Anthropic Claude via LangChain se a API key estiver disponível; caso contrário, usa regras heurísticas locais (regex).
    """
    logging.info(f"[Clause Extraction] Iniciando extração de cláusulas para o contrato ID: {state.get('contract_id')}")
    
    raw_text = state.get("raw_text", "")
    state["clauses_found"] = []
    
    if not raw_text or raw_text == "[CONTEÚDO VAZIO - ARQUIVO ESCANEADO OU NÃO IDENTIFICADO]":
        logging.warning("[Clause Extraction] O texto do contrato está vazio ou inválido. Usando resposta vazia.")
        state["completed_steps"].append("clause_extraction")
        return state

    # Verifica se há chave de API para o Claude
    api_key = settings.ANTHROPIC_API_KEY
    
    if api_key:
        try:
            logging.info("[Clause Extraction] Utilizando Anthropic Claude para análise das cláusulas.")
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import SystemMessage, HumanMessage
            
            chat = ChatAnthropic(
                anthropic_api_key=api_key,
                model_name=settings.LLM_MODEL,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS
            )
            
            system_prompt = (
                "Você é um analista jurídico especializado em análise de riscos contratuais para PMEs.\n"
                "Sua tarefa é identificar e extrair cláusulas críticas do contrato fornecido nas seguintes categorias:\n"
                "1. 'Termination' (Cláusulas de Rescisão, prazos de aviso prévio, multas, rescisão por conveniência).\n"
                "2. 'Auto-renewal' (Renovação Automática, prazos para notificação de não renovação).\n"
                "3. 'Liability Cap' (Limitação de Responsabilidade, tetos de indenização, exclusões).\n\n"
                "Regra Estrita de Anti-Alucinação: Você DEVE extrair o trecho original EXATO e completo do contrato no campo 'original_text'. NÃO resuma nem altere o original_text.\n"
                "Retorne EXCLUSIVAMENTE um array JSON contendo objetos com o seguinte formato estruturado:\n"
                "[\n"
                "  {\n"
                "    \"clause_type\": \"Termination\" | \"Auto-renewal\" | \"Liability Cap\",\n"
                "    \"original_text\": \"trecho exato e completo contido no contrato\",\n"
                "    \"summary\": \"resumo em português simples\",\n"
                "    \"risk_explanation\": \"breve explicação do risco envolvido para uma SME\"\n"
                "  }\n"
                "]\n"
                "Se alguma dessas cláusulas não for encontrada no contrato, não a inclua no array. Não adicione markdown block de código, responda apenas o JSON puro."
            )
            
            # Corta o texto para caber no limite padrão se for muito longo
            text_snippet = raw_text[:40000] 
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Aqui está o texto do contrato a ser analisado:\n\n{text_snippet}")
            ]
            
            response = chat.invoke(messages)
            response_text = response.content.strip()
            
            # Limpa possíveis blocos de código markdown ```json
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            clauses = json.loads(response_text)
            
            # Validação anti-alucinação extra: Garante que original_text existe de fato no texto original
            validated_clauses = []
            for c in clauses:
                orig = c.get("original_text", "").strip()
                # Verifica se o original_text (desconsiderando espaços) está presente no texto bruto
                cleaned_orig = re.sub(r'\s+', '', orig)
                cleaned_raw = re.sub(r'\s+', '', raw_text)
                
                if cleaned_orig and cleaned_orig in cleaned_raw:
                    validated_clauses.append(c)
                else:
                    logging.warning(f"[Clause Extraction] Descartada cláusula alucinada (não encontrada no texto bruto): {orig[:50]}...")
                    # Se não bater exato por espaçamento, mas a frase for parecida, podemos manter com aviso,
                    # ou tentar buscar uma substring parcial. Para ser estrito, se for muito diferente descartamos.
                    # Mas se bater em formato mais flexível (ex: case-insensitive ou similar), mantemos.
                    if orig.lower() in raw_text.lower():
                        validated_clauses.append(c)
                    
            state["clauses_found"] = validated_clauses
            logging.info(f"[Clause Extraction] Claude identificou com sucesso {len(validated_clauses)} cláusulas.")
            
        except Exception as e:
            logging.error(f"[Clause Extraction] Falha ao chamar a API Claude: {e}. Iniciando fallback offline...")
            state["clauses_found"] = run_heuristic_extraction(raw_text)
    else:
        logging.info("[Clause Extraction] Chave ANTHROPIC_API_KEY ausente. Iniciando fallback heurístico offline.")
        state["clauses_found"] = run_heuristic_extraction(raw_text)

    state["completed_steps"].append("clause_extraction")
    return state


def run_heuristic_extraction(raw_text: str) -> List[Dict[str, Any]]:
    """
    Extrai cláusulas usando Regex e heurísticas locais (Offline Fallback).
    Busca por sentenças em torno de palavras-chave sobre Rescisão, Renovação e Responsabilidade.
    """
    clauses = []
    sentences = re.split(r'\. |\n', raw_text)
    
    # Padrões Regex em inglês e português
    patterns = {
        "Termination": re.compile(
            r"(terminate|termination|rescindir|rescisão|notificação prévia|notice period|prior notice|cancel|cancelamento|default)", 
            re.IGNORECASE
        ),
        "Auto-renewal": re.compile(
            r"(automatic.*renew|auto-renew|renovação automática|prorrogação automática|automatically renew|renovado automaticamente)", 
            re.IGNORECASE
        ),
        "Liability Cap": re.compile(
            r"(limitation of liability|liability cap|limite de responsabilidade|responsabilidade máxima|indenização máxima|maximum liability|exclusão de danos)", 
            re.IGNORECASE
        )
    }
    
    # Dicionário temporário para agrupar as sentenças que batem
    found_segments = {key: [] for key in patterns}
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20: # ignora pedaços muito curtos
            continue
        for clause_type, pattern in patterns.items():
            if pattern.search(sentence):
                found_segments[clause_type].append(sentence)
                
    # Monta os objetos de cláusula a partir dos segmentos encontrados
    for clause_type, segments in found_segments.items():
        if not segments:
            continue
        # Limita para os 4 primeiros trechos relevantes para evitar encher o banco com ruído
        selected_text = " [...] ".join(segments[:4])
        
        # Cria sumários heurísticos
        if clause_type == "Termination":
            summary = "Define os termos de rescisão contratual, avisos prévios e penalidades."
            risk_explanation = "Avisos prévios muito longos (>60 dias) ou multas rescisórias elevadas podem aprisionar a empresa e causar prejuízos."
        elif clause_type == "Auto-renewal":
            summary = "Define que o contrato será renovado automaticamente ao fim da vigência."
            risk_explanation = "Renovações automáticas sem aviso prévio podem forçar a empresa a pagar por serviços não mais desejados."
        else:
            summary = "Define o limite máximo que a contraparte pagará por eventuais danos ocorridos."
            risk_explanation = "Limitações de responsabilidade muito baixas ou unilaterais deixam a empresa desprotegida em caso de falhas críticas ou negligência do fornecedor."
            
        clauses.append({
            "clause_type": clause_type,
            "original_text": selected_text,
            "summary": summary,
            "risk_explanation": risk_explanation
        })
        
    logging.info(f"[Heuristic Extraction] Extração offline concluída. Encontrados {len(clauses)} tipos de cláusula.")
    return clauses
