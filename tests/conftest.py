import os
import sys
import asyncio
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# ==============================================================================
# Fail-Closed Test Database Target Enforcement
# Ensure all pytest runs strictly target nammaclean_test_db on localhost:5433.
# Environment variables override .env settings before application modules load.
# ==============================================================================
os.environ["POSTGRES_DB"] = "nammaclean_test_db"
os.environ["POSTGRES_PORT"] = "5433"
os.environ["POSTGRES_HOST"] = "localhost"

from app.core.config import settings
from app.core.database import engine, AsyncSessionLocal
from app.main import app


def _assert_test_database_isolation() -> None:
    """Fail-closed assertion verifying test target isolation before running tests."""
    assert settings.POSTGRES_DB == "nammaclean_test_db", (
        f"Security Alert: Target database is '{settings.POSTGRES_DB}', not 'nammaclean_test_db'!"
    )
    assert settings.POSTGRES_PORT == 5433, (
        f"Security Alert: Target port is {settings.POSTGRES_PORT}, not 5433!"
    )
    assert settings.POSTGRES_HOST in ("localhost", "127.0.0.1"), (
        f"Security Alert: Target host is '{settings.POSTGRES_HOST}', not localhost!"
    )
    assert "nammaclean_test_db" in settings.async_database_url, (
        "Security Alert: async_database_url does not target nammaclean_test_db!"
    )
    assert "nammaclean_db" not in settings.async_database_url, (
        "Security Alert: async_database_url references development database nammaclean_db!"
    )
    assert ":5432/" not in settings.async_database_url, (
        "Security Alert: async_database_url references port 5432 / MigrationGuard!"
    )
    assert ":5433/" in settings.async_database_url, (
        "Security Alert: async_database_url does not reference port 5433!"
    )
    # Check sync URL as well for Alembic/psycopg2 protection
    assert "nammaclean_test_db" in settings.sync_database_url
    assert "nammaclean_db" not in settings.sync_database_url
    assert ":5432/" not in settings.sync_database_url
    assert ":5433/" in settings.sync_database_url


# Execute static configuration assertion on module load
_assert_test_database_isolation()


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Fail-closed preflight check executed before test collection or execution.
    Verifies live connectivity to nammaclean_test_db and aborts if unreachable
    or if connected to the wrong database or port.
    """
    _assert_test_database_isolation()

    async def _verify_live_database() -> None:
        try:
            async with engine.connect() as conn:
                res = await conn.execute(text("SELECT current_database(), current_user;"))
                curr_db, curr_user = res.fetchone()
                if curr_db != "nammaclean_test_db":
                    raise RuntimeError(
                        f"FATAL: Database guard failed! Expected 'nammaclean_test_db', connected to '{curr_db}'. Aborting."
                    )

                rev_res = await conn.execute(text("SELECT version_num FROM alembic_version;"))
                actual_rev = rev_res.scalar_one_or_none()
                if actual_rev != "b7e4d2c9f1a8":
                    raise RuntimeError(
                        f"FATAL: Database guard failed! Expected revision 'b7e4d2c9f1a8', found '{actual_rev}'. Aborting."
                    )

                gis_res = await conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'postgis';"))
                if not gis_res.scalar_one_or_none():
                    raise RuntimeError("FATAL: PostGIS extension not active in nammaclean_test_db! Aborting.")
        finally:
            await engine.dispose()

    try:
        asyncio.run(_verify_live_database())
    except Exception as exc:
        raise RuntimeError(
            f"FATAL: Dedicated test database nammaclean_test_db on localhost:5433 is unavailable or failed preflight: {exc}"
        ) from exc


@pytest_asyncio.fixture(scope="function")
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provides an async test client simulating HTTP calls directly to FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides an isolated async database session with automatic rollback/cleanup."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
        await session.close()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_database_engine():
    """
    Ensure all connections in the SQLAlchemy connection pool are cleanly closed
    and awaited after each test. This prevents unawaited coroutine warnings
    (such as asyncpg Connection._cancel) during event loop teardown.
    """
    yield
    await engine.dispose()
