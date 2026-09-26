import os
import re
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import fitz  # PyMuPDF
from fastapi import UploadFile

from app.config import resolve_project_path, settings


CHUNK_SIZE_BYTES = 1024 * 1024
ALLOWED_FILE_TYPES = {
    ".pdf": {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
    },
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ContractFileValidationError(ValueError):
    """O upload não representa um PDF ou DOCX seguro e válido."""


class ContractFileTooLargeError(ContractFileValidationError):
    """O upload ultrapassou o limite configurado."""


def get_contracts_storage_dir() -> Path:
    """Retorna o diretório absoluto e canônico de contratos."""
    return resolve_project_path(settings.CONTRACTS_STORAGE_DIR)


def ensure_contracts_storage_dir() -> Path:
    """Cria o diretório de contratos quando necessário e retorna seu caminho."""
    storage_dir = get_contracts_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def resolve_contract_file_path(file_path: str | Path) -> Path:
    """Resolve um arquivo persistido e garante que ele permaneça no storage."""
    storage_dir = get_contracts_storage_dir()
    resolved_path = resolve_project_path(file_path)

    try:
        resolved_path.relative_to(storage_dir)
    except ValueError as exc:
        raise ValueError("Caminho de contrato fora do diretório permitido.") from exc

    return resolved_path


def delete_contract_file(file_path: str | Path) -> bool:
    """Remove somente um arquivo que esteja dentro do storage de contratos."""
    try:
        resolved_path = resolve_contract_file_path(file_path)
    except (TypeError, ValueError):
        return False

    if not resolved_path.is_file():
        return False

    resolved_path.unlink()
    return True


def save_contract_file(file: UploadFile) -> str:
    """Valida e persiste um PDF/DOCX de forma limitada e atômica.

    O conteúdo é gravado primeiro em um arquivo temporário no próprio storage,
    validado por assinatura/estrutura e só então movido para o nome definitivo.
    """
    safe_name, suffix = _validate_upload_metadata(file)
    destination_dir = ensure_contracts_storage_dir()
    temporary_path = destination_dir / f".upload-{uuid.uuid4().hex}.tmp"
    max_size_bytes = settings.MAX_CONTRACT_FILE_SIZE_MB * 1024 * 1024

    try:
        total_bytes = _stream_upload(file, temporary_path, max_size_bytes)
        if total_bytes == 0:
            raise ContractFileValidationError("O arquivo enviado está vazio.")

        if suffix == ".pdf":
            _validate_pdf(temporary_path)
        else:
            _validate_docx(temporary_path)

        stem = Path(safe_name).stem
        destination_path = destination_dir / (
            f"{stem}-{uuid.uuid4().hex[:12]}{suffix}"
        )
        os.replace(temporary_path, destination_path)
        return _path_for_database(destination_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _validate_upload_metadata(file: UploadFile) -> tuple[str, str]:
    filename = (file.filename or "").strip()
    if not filename:
        raise ContractFileValidationError("O arquivo precisa ter um nome.")

    normalized_name = unicodedata.normalize("NFKC", filename.replace("\\", "/"))
    basename = PurePosixPath(normalized_name).name
    suffix = Path(basename).suffix.casefold()
    if suffix not in ALLOWED_FILE_TYPES:
        raise ContractFileValidationError(
            "Formato de arquivo inválido. Apenas PDF ou DOCX são aceitos."
        )

    declared_type = (file.content_type or "").partition(";")[0].strip().casefold()
    if declared_type and declared_type not in ALLOWED_FILE_TYPES[suffix]:
        raise ContractFileValidationError(
            "O tipo de conteúdo informado não corresponde à extensão do arquivo."
        )

    stem = Path(basename).stem
    stem = "".join(
        "_" if unicodedata.category(char).startswith("C") else char for char in stem
    )
    stem = re.sub(r'[<>:"/\\|?*]+', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    stem = stem[:120].rstrip(" .") or "contrato"
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"contrato_{stem}"

    return f"{stem}{suffix}", suffix


def _stream_upload(file: UploadFile, destination: Path, max_size_bytes: int) -> int:
    total_bytes = 0
    with destination.open("xb") as buffer:
        while True:
            chunk = file.file.read(CHUNK_SIZE_BYTES)
            if not chunk:
                break

            total_bytes += len(chunk)
            if total_bytes > max_size_bytes:
                raise ContractFileTooLargeError(
                    f"O arquivo excede o limite de {settings.MAX_CONTRACT_FILE_SIZE_MB} MB."
                )
            buffer.write(chunk)

        buffer.flush()
        os.fsync(buffer.fileno())
    return total_bytes


def _validate_pdf(path: Path) -> None:
    with path.open("rb") as file_handle:
        if b"%PDF-" not in file_handle.read(1024):
            raise ContractFileValidationError("O conteúdo enviado não é um PDF válido.")

    document = None
    try:
        document = fitz.open(path, filetype="pdf")
        if document.needs_pass or document.is_encrypted:
            raise ContractFileValidationError(
                "PDFs protegidos por senha não podem ser processados."
            )
        if document.page_count < 1:
            raise ContractFileValidationError("O PDF precisa conter ao menos uma página.")
    except ContractFileValidationError:
        raise
    except Exception as exc:
        raise ContractFileValidationError(
            "O conteúdo enviado não é um PDF íntegro."
        ) from exc
    finally:
        if document is not None:
            document.close()


def _validate_docx(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ContractFileValidationError("O conteúdo enviado não é um DOCX válido.")

    max_uncompressed_bytes = settings.MAX_DOCX_UNCOMPRESSED_SIZE_MB * 1024 * 1024
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10_000:
                raise ContractFileValidationError("O DOCX contém arquivos internos demais.")

            total_uncompressed = 0
            names = set()
            for entry in entries:
                normalized_entry_name = entry.filename.replace("\\", "/")
                member_path = PurePosixPath(normalized_entry_name)
                has_windows_drive = bool(member_path.parts and ":" in member_path.parts[0])
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or has_windows_drive
                ):
                    raise ContractFileValidationError(
                        "O DOCX contém um caminho interno inseguro."
                    )
                if entry.flag_bits & 0x1:
                    raise ContractFileValidationError(
                        "DOCX protegido por senha não pode ser processado."
                    )

                file_mode = (entry.external_attr >> 16) & 0o170000
                if file_mode == 0o120000:
                    raise ContractFileValidationError(
                        "O DOCX contém um link simbólico não permitido."
                    )

                names.add(entry.filename)
                total_uncompressed += entry.file_size
                if total_uncompressed > max_uncompressed_bytes:
                    raise ContractFileValidationError(
                        "O conteúdo descompactado do DOCX excede o limite permitido."
                    )

            required_entries = {"[Content_Types].xml", "word/document.xml"}
            if not required_entries.issubset(names):
                raise ContractFileValidationError(
                    "O arquivo ZIP não possui a estrutura obrigatória de um DOCX."
                )

            document_xml = archive.read("word/document.xml").upper()
            if b"<!DOCTYPE" in document_xml or b"<!ENTITY" in document_xml:
                raise ContractFileValidationError(
                    "O DOCX contém declarações XML não permitidas."
                )

            if archive.testzip() is not None:
                raise ContractFileValidationError("O DOCX está corrompido.")
    except ContractFileValidationError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ContractFileValidationError("O DOCX está corrompido.") from exc


def _path_for_database(path: Path) -> str:
    try:
        return path.relative_to(settings.BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)
