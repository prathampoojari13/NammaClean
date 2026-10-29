from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan events for startup and shutdown.
    Cleanly handles initialization before taking traffic and cleanup on shutdown.
    """
    # Startup logic
    yield
    # Shutdown logic: dispose async engine pool
    from app.core.database import engine
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="Real-world oriented waste management & municipal fleet monitoring platform for Bengaluru.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Secure CORS setup using explicitly configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Include v1 API endpoints
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Root"])
async def root():
    """Root entrypoint linking to interactive documentation."""
    return {
        "message": f"Welcome to {settings.APP_NAME} Backend API",
        "documentation": "/docs",
        "health_check": f"{settings.API_V1_STR}/health",
        "environment": settings.APP_ENV,
    }
