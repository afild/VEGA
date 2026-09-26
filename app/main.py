import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.config import settings
from app.database.db_manager import init_db
from app.api.router import api_router
from app.agents.email_listener import start_email_listener
from app.security import LocalSecurityMiddleware, parse_csv_setting
from app.utils.file_storage import ensure_contracts_storage_dir

# Configuração de Logs
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização do banco de dados na inicialização do servidor
    logging.info("Inicializando recursos do VEGA...")
    storage_dir = ensure_contracts_storage_dir()
    logging.info(f"Diretório de contratos disponível em: {storage_dir}")
    init_db()
    
    # Inicia as rotinas em background
    email_task = start_email_listener()
    
    yield
    # Limpeza se necessário
    logging.info("Encerrando recursos do VEGA...")
    if email_task:
        email_task.cancel()

app = FastAPI(
    title="VEGA — Vendor & Contract Governance Agent",
    description="API de Ingestão, análise e monitoramento de contratos para SMEs.",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    debug=settings.DEBUG
)

# A aplicação é local por padrão. Hosts e origens adicionais precisam ser
# explicitamente autorizados no ambiente.
allowed_hosts = parse_csv_setting(settings.ALLOWED_HOSTS)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost", "testserver"],
    www_redirect=False,
)

allowed_origins = parse_csv_setting(settings.CORS_ALLOWED_ORIGINS)
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

app.add_middleware(
    LocalSecurityMiddleware,
    allowed_origins=allowed_origins,
    max_upload_bytes=settings.MAX_CONTRACT_FILE_SIZE_MB * 1024 * 1024,
)

# Inclui as rotas da API
app.include_router(api_router)

# Servir Frontend Estático
frontend_dir = settings.BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
else:
    logging.warning(f"Diretório frontend não encontrado no caminho esperado: {frontend_dir}")

# Rota raiz para redirecionar para o painel do dashboard
@app.get("/")
def redirect_to_dashboard():
    return RedirectResponse(url="/static/index.html")
