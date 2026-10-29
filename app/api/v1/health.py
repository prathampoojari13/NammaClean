from datetime import datetime, timezone
from typing import Dict, Any
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import check_database_connection

router = APIRouter()


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    summary="Application Process Liveness",
    description="Lightweight ping returning 200 OK if the Python FastAPI application process is alive, without querying the database.",
)
async def get_liveness() -> Dict[str, Any]:
    """Lightweight liveness check for orchestrators."""
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": {
            "name": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "version": "0.1.0",
        },
    }


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="System Health & Database Readiness",
    description="Comprehensive readiness check that pings PostgreSQL and verifies PostGIS extension status.",
)
async def get_system_health() -> JSONResponse:
    """Full readiness check querying database connectivity and PostGIS status."""
    db_status = await check_database_connection()

    is_overall_healthy = db_status.get("connected", False)
    http_status = status.HTTP_200_OK if is_overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    payload: Dict[str, Any] = {
        "status": "healthy" if is_overall_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": {
            "name": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "version": "0.1.0",
        },
        "database": db_status,
    }

    return JSONResponse(status_code=http_status, content=payload)
