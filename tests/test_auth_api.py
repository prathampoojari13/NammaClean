"""
API integration tests for NammaClean Stage 2.4.2: Citizen Registration Endpoint.
Tests HTTP request handling, validation, error mapping, transaction rollback, and security.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.v1.auth import register_rate_limiter
from app.core.security import verify_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_register_rate_limit_state():
    register_rate_limiter.reset()
    yield
    register_rate_limiter.reset()


@pytest.mark.asyncio
async def test_register_citizen_success_returns_201_and_public_fields(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Successful registration returns 201 Created.
    2. Response contains all expected public user fields.
    3. Response never exposes password, password_hash, or secret fields.
    4. Database row stores Argon2id password hash.
    5. Assigned role is CITIZEN and status is ACTIVE.
    """
    unique_email = f"citizen_api_{uuid.uuid4().hex[:8]}@example.com"
    plain_password = "SecurePassword123!"

    payload = {
        "email": unique_email,
        "password": plain_password,
    }

    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    # 2. Public fields present
    assert "id" in data
    assert data["email"] == unique_email.lower()
    assert data["role"] == UserRole.CITIZEN.value
    assert data["status"] == UserStatus.ACTIVE.value
    assert "created_at" in data
    assert "updated_at" in data

    # 3. Secret fields strictly absent from HTTP response
    assert "password" not in data
    assert "password_hash" not in data
    assert "hashed_password" not in data

    # 4 & 5. Verify database persistence and password hashing
    user_id = uuid.UUID(data["id"])
    stmt = select(User).where(User.id == user_id)
    db_res = await async_db_session.execute(stmt)
    db_user = db_res.scalars().first()

    assert db_user is not None
    assert db_user.email == unique_email.lower()
    assert db_user.role == UserRole.CITIZEN.value
    assert db_user.status == UserStatus.ACTIVE.value
    assert db_user.password_hash.startswith("$argon2id$")
    assert db_user.password_hash != plain_password
    assert verify_password(plain_password, db_user.password_hash) is True

    # Cleanup test row
    await async_db_session.delete(db_user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409_conflict(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    6. Duplicate email returns 409 Conflict with sanitized messaging.
    7. Email normalization is consistent (different case triggers duplicate conflict).
    """
    shared_email = f"dup_api_{uuid.uuid4().hex[:8]}@example.com"
    payload1 = {
        "email": shared_email.lower(),
        "password": "SecurePassword123!",
    }

    # First registration: succeeds
    res1 = await async_client.post("/api/v1/auth/register", json=payload1)
    assert res1.status_code == 201
    user_id = uuid.UUID(res1.json()["id"])

    # Second registration with uppercase email: returns 409 Conflict
    payload2 = {
        "email": f"  {shared_email.upper()}  ",
        "password": "AnotherSecurePassword123!",
    }
    res2 = await async_client.post("/api/v1/auth/register", json=payload2)
    assert res2.status_code == 409
    err_data = res2.json()
    assert "already exists" in err_data["detail"].lower()
    assert "password" not in str(err_data)

    # Cleanup
    db_user = await async_db_session.get(User, user_id)
    if db_user:
        await async_db_session.delete(db_user)
        await async_db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_email", [
    "",
    "   ",
    "plainaddress",
    "@missingusername.com",
    "username@.com",
    "username@domain",
    "user name@domain.com",
])
async def test_register_invalid_email_returns_422(async_client: AsyncClient, invalid_email: str):
    """Verify 8: Invalid or empty email returns 422 Unprocessable Entity."""
    payload = {
        "email": invalid_email,
        "password": "SecurePassword123!",
    }
    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert "password" not in str(response.json())


@pytest.mark.asyncio
async def test_register_password_length_validation_returns_422(async_client: AsyncClient):
    """
    Verify:
    9. Password shorter than 12 characters returns 422.
    10. Password longer than 128 characters returns 422.
    """
    test_email = "length_test@example.com"

    # Too short: 11 chars
    res_short = await async_client.post(
        "/api/v1/auth/register",
        json={"email": test_email, "password": "Short12345!"},
    )
    assert res_short.status_code == 422
    # Verify password value is not echoed in validation error
    assert "Short12345!" not in str(res_short.json())

    # Too long: 129 chars
    res_long = await async_client.post(
        "/api/v1/auth/register",
        json={"email": test_email, "password": "A" * 128 + "!"},
    )
    assert res_long.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("privileged_field,value", [
    ("role", "MUNICIPAL_ADMIN"),
    ("status", "ACTIVE"),
    ("password_hash", "$argon2id$somehash"),
    ("id", str(uuid.uuid4())),
    ("is_admin", True),
    ("is_superuser", True),
])
async def test_register_extra_privileged_fields_returns_422(
    async_client: AsyncClient,
    privileged_field: str,
    value,
):
    """Verify 11: Attempting to supply client-controlled privileged fields returns 422."""
    payload = {
        "email": f"hacker_{uuid.uuid4().hex[:6]}@example.com",
        "password": "SecurePassword123!",
        privileged_field: value,
    }
    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_failed_request_leaves_no_persisted_user(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify 12: A failed request does not leave a partially persisted or staged user."""
    probe_email = f"failed_probe_{uuid.uuid4().hex[:8]}@example.com"

    # Submit invalid request (password too short)
    res = await async_client.post(
        "/api/v1/auth/register",
        json={"email": probe_email, "password": "short"},
    )
    assert res.status_code == 422

    # Check database: user was never created
    stmt = select(User).where(User.email == probe_email)
    db_res = await async_db_session.execute(stmt)
    assert db_res.scalars().first() is None


@pytest.mark.asyncio
async def test_register_database_level_duplicate_conflict_handled_safely(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    13. A database-level duplicate race is handled safely returning 409 Conflict.
    14. The session remains usable after the duplicate conflict.
    """
    race_email = f"race_api_{uuid.uuid4().hex[:8]}@example.com"

    # Pre-insert user directly in the database
    direct_user = User(
        email=race_email,
        password_hash="$argon2id$directhash",
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(direct_user)
    await async_db_session.commit()

    # Attempt registration via API with the same email
    res = await async_client.post(
        "/api/v1/auth/register",
        json={"email": race_email, "password": "SecurePassword123!"},
    )
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"].lower()

    # 14. Verify database session is fully functional and not poisoned
    stmt = select(User).where(User.email == race_email)
    check_res = await async_db_session.execute(stmt)
    assert check_res.scalars().first() is not None

    # Cleanup
    await async_db_session.delete(direct_user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_register_unexpected_internal_error_sanitized(
    async_client: AsyncClient,
    monkeypatch,
):
    """
    Verify 15: Unexpected internal server errors return 500 without leaking credentials,
    SQL statements, or internal stack traces in the HTTP response.
    """
    from app.api.v1 import auth

    async def mock_crashing_register(db, payload):
        raise RuntimeError("SensitiveDatabaseException: connection to postgres://admin:secret@db failed")

    monkeypatch.setattr(auth, "register_citizen", mock_crashing_register)

    res = await async_client.post(
        "/api/v1/auth/register",
        json={"email": "crash_test@example.com", "password": "SecurePassword123!"},
    )
    assert res.status_code == 500
    detail = res.json()["detail"]
    assert detail == "An unexpected error occurred during registration. Please try again."
    # Ensure sensitive information is never leaked in response
    assert "postgres" not in detail
    assert "secret" not in detail
    assert "SensitiveDatabaseException" not in detail
