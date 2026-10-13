from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.database import initialise_database

settings = get_settings()
initialise_database()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="ELEC5620 Stage 2 prototype API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(
        {settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"}
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }

