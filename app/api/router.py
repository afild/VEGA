from fastapi import APIRouter
from app.api.contracts import router as contracts_router
from app.api.analysis import router as analysis_router
from app.api.alerts import router as alerts_router
from app.api.negotiation import router as negotiation_router
from app.api.system import router as system_router

api_router = APIRouter(prefix="/api")

api_router.include_router(system_router)
api_router.include_router(contracts_router)
api_router.include_router(analysis_router)
api_router.include_router(alerts_router)
api_router.include_router(negotiation_router)
