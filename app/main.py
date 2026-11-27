from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router


_migrations_applied = False


def ensure_migrations_applied() -> None:
    """
    Executes database pre-deployment checks and migrations to head exactly once per process.
    Ensures that PostGIS extension is enabled and Alembic migrations are applied
    automatically on startup across all deployment environments (including Render free tier).
    """
    global _migrations_applied
    if _migrations_applied:
        return

    import logging
    app_logger = logging.getLogger("app.main")

    try:
        from scripts.pre_deploy import run_pre_deploy
        run_pre_deploy()
        _migrations_applied = True
        app_logger.info("Startup database migration check completed successfully.")
    except Exception as exc:
        app_logger.warning(
            "Startup database migration check encountered an error: %s",
            exc,
        )
        if settings.APP_ENV == "production":
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan events for startup and shutdown.
    Cleanly handles initialization before taking traffic and cleanup on shutdown.
    """
    # Startup logic: ensure database schema and PostGIS are up to date
    import asyncio
    await asyncio.to_thread(ensure_migrations_applied)

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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Sanitizes validation errors to ensure sensitive fields (such as passwords and secrets)
    are never returned to the client in HTTP 422 responses or logged in plaintext.
    """
    raw_errors = jsonable_encoder(exc.errors())
    sanitized_errors = []
    for error in raw_errors:
        err_dict = dict(error)
        loc_parts = [str(part).lower() for part in err_dict.get("loc", ())]
        if any(sensitive in loc_parts for sensitive in ("password", "secret", "token")):
            err_dict.pop("input", None)
            if "ctx" in err_dict and isinstance(err_dict["ctx"], dict):
                err_dict["ctx"] = {k: v for k, v in err_dict["ctx"].items() if k != "error"}
        sanitized_errors.append(err_dict)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": sanitized_errors},
    )




from app.api.v1.health import get_system_health


@app.get("/", tags=["Root"])
async def root():
    """Root entrypoint linking to interactive documentation."""
    return {
        "message": f"Welcome to {settings.APP_NAME} Backend API",
        "documentation": "/docs",
        "health_check": f"{settings.API_V1_STR}/health",
        "environment": settings.APP_ENV,
    }


@app.get("/health", tags=["Root"])
async def health_check():
    """Root-level health check alias."""
    return await get_system_health()
