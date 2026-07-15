import shutil
from pathlib import Path
from fastapi import UploadFile
from app.config import settings

def save_contract_file(file: UploadFile) -> str:
    """
    Salva com segurança o arquivo PDF/DOCX carregado no diretório data/storage/contracts/.
    Retorna o caminho relativo do arquivo salvo a partir da raiz do projeto VEGA.
    """
    # Define o diretório de destino absoluto
    dest_dir = (settings.BASE_DIR / settings.CONTRACTS_STORAGE_DIR).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Sanitiza o nome do arquivo para evitar Path Traversal
    filename = Path(file.filename).name
    
    # Se o arquivo já existir, adicionamos um sufixo numérico para evitar sobrescrever
    dest_path = dest_dir / filename
    counter = 1
    while dest_path.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        dest_path = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1
        
    # Salva o arquivo no disco
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Retorna o caminho relativo a partir do BASE_DIR do VEGA
    try:
        relative_path = dest_path.relative_to(settings.BASE_DIR)
        return str(relative_path).replace("\\", "/")
    except ValueError:
        # Fallback se não conseguir calcular o caminho relativo
        return f"{settings.CONTRACTS_STORAGE_DIR}/{dest_path.name}"
