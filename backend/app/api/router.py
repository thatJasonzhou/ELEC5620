from fastapi import APIRouter

from app.api.routes import health, quotations, use_cases

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(use_cases.router)
api_router.include_router(quotations.router)

