import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock
from app.core.database import check_database_connection


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    """Verify that root endpoint responds with API metadata and documentation link."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "NammaClean" in data["message"]
    assert data["documentation"] == "/docs"
    assert "/api/v1/health" in data["health_check"]


@pytest.mark.asyncio
async def test_liveness_endpoint(async_client: AsyncClient):
    """Verify that the lightweight liveness endpoint returns 200 OK without requiring DB operations."""
    response = await async_client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert data["service"]["name"] == "NammaClean"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_readiness_endpoint_healthy(async_client: AsyncClient):
    """
    Verify that health endpoint strictly returns HTTP 200 and confirms connected database
    and installed PostGIS extension under healthy operating conditions.
    """
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"]["name"] == "NammaClean"
    assert data["database"]["connected"] is True
    assert data["database"]["postgis_installed"] is True
    assert data["database"]["port"] == 5433


@pytest.mark.asyncio
async def test_health_readiness_endpoint_degraded(async_client: AsyncClient, monkeypatch):
    """
    Verify that health endpoint strictly returns HTTP 503 Service Unavailable with status 'degraded'
    when the database connection is lost or unavailable.
    """
    mock_db_failure = AsyncMock(
        return_value={
            "connected": False,
            "latency_ms": 12.5,
            "database": "nammaclean_db",
            "host": "localhost",
            "port": 5433,
            "postgis_installed": False,
            "postgis_version": None,
            "error": "Connection refused to database host",
        }
    )
    monkeypatch.setattr("app.api.v1.health.check_database_connection", mock_db_failure)

    response = await async_client.get("/api/v1/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["database"]["connected"] is False
    assert "error" in data["database"]


@pytest.mark.asyncio
async def test_database_direct_ping():
    """Verify direct async database ping against PostGIS on port 5433."""
    db_status = await check_database_connection()
    assert isinstance(db_status, dict)
    assert db_status["connected"] is True
    assert db_status["postgis_installed"] is True
    assert isinstance(db_status["latency_ms"], (int, float))
    assert db_status["database"] == "nammaclean_db"
    assert db_status["port"] == 5433
