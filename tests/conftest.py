import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from typing import AsyncGenerator

from app.main import app
from app.core.database import engine


@pytest_asyncio.fixture(scope="function")
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provides an async test client simulating HTTP calls directly to FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def cleanup_database_engine():
    """
    Ensure all connections in the SQLAlchemy connection pool are cleanly closed
    and awaited after each test. This prevents unawaited coroutine warnings
    (such as asyncpg Connection._cancel) during event loop teardown.
    """
    yield
    await engine.dispose()
