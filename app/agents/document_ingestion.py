import fitz  # PyMuPDF
import logging
from pathlib import Path
from app.config import settings

def run_document_ingestion(state: dict) -> dict:
    """Agente de Ingestão de Documentos.

    Lê o arquivo de contrato (geralmente PDF) a partir do disco local e extrai todo o texto.
    Salva o texto extraído no estado (raw_text).

    Args:
        state (dict): Estado atual do LangGraph (VEGAState).

    Returns:
        dict: O estado atualizado com o texto bruto do documento.
    """
    try:
        logging.info(f"[Document Ingestion] Iniciando ingestão do contrato ID: {state.get('contract_id')}")
        
        file_path: str = state.get("file_path", "")
        if not file_path:
            logging.error("[Document Ingestion] Caminho do arquivo não fornecido no estado.")
            state["raw_text"] = ""
            state["completed_steps"].append("document_ingestion")
            return state

        # Resolve o caminho do arquivo
        abs_path: Path = Path(settings.BASE_DIR) / file_path
        if not abs_path.exists():
            logging.error(f"[Document Ingestion] Arquivo não encontrado no caminho: {abs_path}")
            state["raw_text"] = ""
            state["completed_steps"].append("document_ingestion")
            return state

        raw_text: str = ""
        suffix: str = abs_path.suffix.lower()
        
        try:
            if suffix == ".pdf":
                # Abre o PDF usando PyMuPDF (fitz)
                logging.info(f"[Document Ingestion] Extraindo texto do PDF com PyMuPDF: {abs_path}")
                doc = fitz.open(abs_path)
                pages_text = []
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    pages_text.append(page.get_text("text"))
                raw_text = "\n".join(pages_text)
                doc.close()
            elif suffix == ".docx":
                # Usando LlamaIndex SimpleDirectoryReader para DOCX como fallback especificado no SDD
                logging.info(f"[Document Ingestion] Extraindo texto do DOCX usando LlamaIndex: {abs_path}")
                from llama_index.core import SimpleDirectoryReader
                reader = SimpleDirectoryReader(input_files=[str(abs_path)])
                docs = reader.load_data()
                raw_text = "\n".join([doc.text for doc in docs])
            else:
                logging.warning(f"[Document Ingestion] Formato de arquivo não suportado explicitamente: {suffix}. Tentando leitura genérica.")
                # Fallback de leitura como texto se não for PDF ou DOCX
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw_text = f.read()
                    
        except Exception as e:
            logging.error(f"[Document Ingestion] Erro crítico ao extrair texto do documento: {e}")
            raw_text = ""

        # Tratamento anti-alucinação se não houver texto extraído
        if not raw_text.strip():
            logging.warning("[Document Ingestion] O texto extraído está vazio. O documento pode ser escaneado (imagem sem OCR).")
            raw_text = "[CONTEÚDO VAZIO - ARQUIVO ESCANEADO OU NÃO IDENTIFICADO]"

        state["raw_text"] = raw_text
        state["completed_steps"].append("document_ingestion")
        
        logging.info(f"[Document Ingestion] Concluído. Extraídos {len(raw_text)} caracteres de texto.")
        return state
        
    except Exception as e:
        logging.error(f"[Document Ingestion] Erro inesperado e catastrófico no nó: {e}")
        state.setdefault("risk_flags", []).append("DOCUMENT_INGESTION_FAILED")
        return state
