import time
from typing import AsyncGenerator, Dict, Any
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from app.core.config import settings

# Create async engine for high-performance non-blocking queries
engine = create_async_engine(
    settings.async_database_url,
    echo=settings.APP_DEBUG,
    pool_pre_ping=True,  # Automatically check if connection is alive before using
    pool_size=10,
    max_overflow=20,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Base class for all ORM models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a transactional database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_database_connection() -> Dict[str, Any]:
    """
    Performs a live database ping and verifies PostGIS extension availability
    via the pg_extension catalog.
    Returns status dictionary with connection details and latency.
    """
    start_time = time.perf_counter()
    try:
        async with engine.connect() as conn:
            # 1. Test basic SQL query execution
            await conn.execute(text("SELECT 1"))
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # 2. Query actual database name from active connection
            db_res = await conn.execute(text("SELECT current_database()"))
            actual_db = db_res.scalar() or (engine.url.database or settings.POSTGRES_DB)

            # 3. Query pg_extension system catalog safely without throwing if absent
            ext_result = await conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
            row = ext_result.fetchone()
            postgis_installed = row is not None
            postgis_version = str(row[0]) if row else None

            # 4. Query current migration revision safely without throwing if absent
            migration_revision = None
            try:
                rev_res = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
                rev_row = rev_res.fetchone()
                if rev_row:
                    migration_revision = str(rev_row[0])
            except Exception:
                pass

            # 5. Diagnostic column inspection and model select probe
            user_columns = []
            user_query_error = None
            try:
                cols_res = await conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position")
                )
                user_columns = [r[0] for r in cols_res.fetchall()]

                from sqlalchemy import select
                from app.models.user import User
                test_stmt = select(User).limit(1)
                await conn.execute(test_stmt)
            except Exception as e:
                user_query_error = f"{type(e).__name__}: {str(e)}"

            return {
                "connected": True,
                "latency_ms": latency_ms,
                "database": actual_db,
                "host": engine.url.host or settings.POSTGRES_HOST,
                "port": engine.url.port or settings.POSTGRES_PORT,
                "postgis_installed": postgis_installed,
                "postgis_version": postgis_version,
                "migration_revision": migration_revision,
                "user_columns": user_columns,
                "user_query_error": user_query_error,
            }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "connected": False,
            "latency_ms": latency_ms,
            "database": engine.url.database or settings.POSTGRES_DB,
            "host": engine.url.host or settings.POSTGRES_HOST,
            "port": engine.url.port or settings.POSTGRES_PORT,
            "postgis_installed": False,
            "postgis_version": None,
            "error": str(exc),
        }

