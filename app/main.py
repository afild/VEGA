import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.config import settings
from app.database.db_manager import init_db
from app.api.router import api_router
from app.agents.email_listener import start_email_listener

# Configuração de Logs
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização do banco de dados na inicialização do servidor
    logging.info("Inicializando recursos do VEGA...")
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
    version="0.2.0",
    lifespan=lifespan,
    debug=settings.DEBUG
)

# Configuração do Middleware CORS para permitir integração com outros agentes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
