from fastapi import APIRouter

from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.queries import router as queries_router
from app.api.v1.routes.workload import router as workload_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(queries_router)
api_router.include_router(workload_router)
