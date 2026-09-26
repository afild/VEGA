import logging
from pathlib import Path

import fitz  # PyMuPDF

from app.config import settings
from app.utils.file_storage import resolve_contract_file_path


class DocumentIngestionError(RuntimeError):
    """Falha fatal e segura para exibição durante a ingestão."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


class DocumentNeedsReviewError(DocumentIngestionError):
    """Documento válido, mas sem conteúdo textual analisável automaticamente."""


def run_document_ingestion(state: dict) -> dict:
    """Extrai texto somente de um arquivo autorizado e falha de forma explícita.

    Um documento vazio ou escaneado não recebe marcador textual nem segue para
    os agentes seguintes. O orquestrador o classifica como ``needs_review``.
    """
    contract_id = state.get("contract_id")
    logging.info("[Document Ingestion] Iniciando contrato ID: %s", contract_id)

    file_path = state.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        raise DocumentIngestionError(
            "DOCUMENT_PATH_MISSING",
            "O caminho do arquivo do contrato não está disponível.",
        )

    try:
        abs_path: Path = resolve_contract_file_path(file_path)
    except (TypeError, ValueError) as exc:
        raise DocumentIngestionError(
            "DOCUMENT_PATH_REJECTED",
            "O arquivo do contrato está fora do armazenamento autorizado.",
        ) from exc

    if not abs_path.is_file():
        raise DocumentIngestionError(
            "DOCUMENT_NOT_FOUND",
            "O arquivo original do contrato não foi encontrado.",
        )

    suffix = abs_path.suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise DocumentIngestionError(
            "UNSUPPORTED_DOCUMENT_TYPE",
            "O formato do documento não é compatível com a análise.",
        )

    try:
        if suffix == ".pdf":
            raw_text, page_count, truncated = _extract_pdf_text(abs_path)
        else:
            raw_text, page_count, truncated = _extract_docx_text(abs_path)
    except DocumentIngestionError:
        raise
    except Exception as exc:
        logging.exception(
            "[Document Ingestion] Falha ao extrair o contrato ID %s.", contract_id
        )
        raise DocumentIngestionError(
            "DOCUMENT_EXTRACTION_FAILED",
            "Não foi possível extrair o texto do documento.",
        ) from exc

    if not raw_text.strip():
        raise DocumentNeedsReviewError(
            "NO_EXTRACTABLE_TEXT",
            "Nenhum texto foi encontrado. O documento pode ser escaneado e requer OCR ou revisão manual.",
        )

    state["raw_text"] = raw_text
    state["document_metadata"] = {
        "file_type": suffix.removeprefix("."),
        "page_count": page_count,
        "extracted_text_chars": len(raw_text),
        "truncated": truncated,
    }
    if truncated:
        raise DocumentNeedsReviewError(
            "EXTRACTED_TEXT_TRUNCATED",
            "O texto excedeu o limite de análise. Revise o documento completo antes de usar os resultados.",
        )
    state.setdefault("completed_steps", []).append("document_ingestion")

    logging.info(
        "[Document Ingestion] Concluído contrato ID %s: %s caracteres.",
        contract_id,
        len(raw_text),
    )
    return state


def _extract_pdf_text(path: Path) -> tuple[str, int, bool]:
    logging.info("[Document Ingestion] Extraindo PDF: %s", path)
    pages_text: list[str] = []
    remaining_chars = settings.MAX_EXTRACTED_TEXT_CHARS
    truncated = False

    with fitz.open(path) as document:
        page_count = len(document)
        for page_number in range(page_count):
            page_text = document.load_page(page_number).get_text("text")
            if len(page_text) > remaining_chars:
                pages_text.append(page_text[:remaining_chars])
                truncated = True
                break

            pages_text.append(page_text)
            remaining_chars -= len(page_text)
            if remaining_chars <= 0 and page_number < page_count - 1:
                truncated = True
                break

    return "\n".join(pages_text), page_count, truncated


def _extract_docx_text(path: Path) -> tuple[str, int | None, bool]:
    logging.info("[Document Ingestion] Extraindo DOCX: %s", path)
    from llama_index.core import SimpleDirectoryReader

    documents = SimpleDirectoryReader(input_files=[str(path)]).load_data()
    raw_text = "\n".join(document.text for document in documents)
    truncated = len(raw_text) > settings.MAX_EXTRACTED_TEXT_CHARS
    if truncated:
        raw_text = raw_text[: settings.MAX_EXTRACTED_TEXT_CHARS]
    return raw_text, None, truncated
