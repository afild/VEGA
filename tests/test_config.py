from pathlib import Path

from app.config import resolve_project_path, settings
from app.utils.file_storage import get_contracts_storage_dir


def test_project_root_and_frontend_path():
    expected_root = Path(__file__).resolve().parent.parent

    assert settings.BASE_DIR.resolve() == expected_root
    assert (settings.BASE_DIR / "frontend" / "index.html").is_file()


def test_legacy_project_prefix_is_normalized():
    expected_root = Path(__file__).resolve().parent.parent

    assert resolve_project_path("VEGA/vega_contracts.db") == expected_root / "vega_contracts.db"


def test_contract_storage_uses_isolated_test_runtime():
    storage_dir = get_contracts_storage_dir()

    assert storage_dir.is_absolute()
    assert storage_dir.name == "contracts"


def test_security_defaults_are_explicit():
    assert settings.ALLOW_LLM_RAW_CONTRACT_TEXT is False
    assert settings.CORS_ALLOWED_ORIGINS == ""
    assert settings.MAX_CONTRACT_FILE_SIZE_MB > 0
    assert settings.MAX_DOCX_UNCOMPRESSED_SIZE_MB >= settings.MAX_CONTRACT_FILE_SIZE_MB
