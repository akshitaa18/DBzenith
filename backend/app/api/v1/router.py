from fastapi import APIRouter

from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.plans import router as plans_router
from app.api.v1.routes.queries import router as queries_router
from app.api.v1.routes.recommendations import router as recommendations_router
from app.api.v1.routes.simulations import router as simulations_router
from app.api.v1.routes.workload import router as workload_router
from app.api.v1.routes.rl import router as rl_router
from app.api.v1.routes.rewriter import router as rewriter_router
from app.api.v1.routes.assistant import router as assistant_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(queries_router)
api_router.include_router(recommendations_router)
api_router.include_router(simulations_router)
api_router.include_router(plans_router)
api_router.include_router(workload_router)
api_router.include_router(rl_router)
api_router.include_router(rewriter_router)
api_router.include_router(assistant_router)


