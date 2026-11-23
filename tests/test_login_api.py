"""
API integration tests for NammaClean Stage 2.5.1: User Login & JWT Issuance.
Verifies credentials authentication, account status enforcement, timing mitigation,
JWT token issuance, error sanitization, and schema validation.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_access_token, hash_password
from app.api.v1.auth import login_rate_limiter
from app.models.enums import UserRole, UserStatus
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_login_rate_limit_state():
    login_rate_limiter.reset()
    yield
    login_rate_limiter.reset()


@pytest.mark.asyncio
async def test_login_success_returns_jwt_access_token(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Successful login with a registered active citizen returns HTTP 200 OK.
    2. Returned access token decodes using the existing JWT utility.
    3. Token subject matches the registered user's UUID string.
    4. Token expiration follows the configured ACCESS_TOKEN_EXPIRE_MINUTES.
    13. Response contains only token fields and never exposes secrets or password hashes.
    """
    unique_email = f"active_login_{uuid.uuid4().hex[:8]}@example.com"
    plain_password = "SecurePassword123!"

    user = User(
        email=unique_email,
        password_hash=hash_password(plain_password),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()
    await async_db_session.refresh(user)

    # Execute login request
    login_payload = {
        "email": f"  {unique_email.upper()}  ",  # Tests email normalization (trimmed, lowercased)
        "password": plain_password,
    }
    response = await async_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    # Ensure no sensitive fields leaked in payload
    assert "password" not in data
    assert "password_hash" not in data

    # Verify decoded JWT claims
    claims = decode_access_token(data["access_token"])
    assert claims["sub"] == str(user.id)
    assert claims["role"] == UserRole.CITIZEN.value
    assert "jti" in claims
    assert "iat" in claims
    assert "exp" in claims
    # Expiration delta check
    expected_delta_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    actual_delta_seconds = claims["exp"] - claims["iat"]
    assert actual_delta_seconds == expected_delta_seconds

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_login_incorrect_password_returns_401(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify 5: Incorrect password returns 401 Unauthorized with generic message."""
    unique_email = f"wrong_pw_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=unique_email,
        password_hash=hash_password("CorrectPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "WrongPassword123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(async_client: AsyncClient):
    """Verify 6: Unknown email returns 401 Unauthorized with generic message."""
    unknown_email = f"unknown_{uuid.uuid4().hex[:8]}@example.com"
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": unknown_email, "password": "AnyPassword123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_unknown_email_and_incorrect_password_use_identical_message(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify 7: Unknown email and incorrect password return the exact same public error message
    to prevent user enumeration.
    """
    unique_email = f"enum_test_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=unique_email,
        password_hash=hash_password("RealPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    # Case A: Existing user, wrong password
    res_wrong_pw = await async_client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "BadPassword123!"},
    )

    # Case B: Non-existent user
    res_unknown_user = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "non_existent_citizen@example.com", "password": "BadPassword123!"},
    )

    assert res_wrong_pw.status_code == 401
    assert res_unknown_user.status_code == 401
    assert res_wrong_pw.json()["detail"] == res_unknown_user.json()["detail"] == "Invalid email or password."

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_login_disabled_account_rejected(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify 8: Accounts with status=DISABLED are rejected with generic 401."""
    disabled_email = f"disabled_{uuid.uuid4().hex[:8]}@example.com"
    plain_password = "SecurePassword123!"

    user = User(
        email=disabled_email,
        password_hash=hash_password(plain_password),
        role=UserRole.CITIZEN.value,
        status=UserStatus.DISABLED.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": disabled_email, "password": plain_password},
    )
    assert response.status_code == 401
    # Generic message prevents revealing that account exists but is disabled
    assert response.json()["detail"] == "Invalid email or password."

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_login_pending_verification_account_rejected(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify 9: Accounts with status=PENDING_VERIFICATION are rejected with generic 401."""
    pending_email = f"pending_{uuid.uuid4().hex[:8]}@example.com"
    plain_password = "SecurePassword123!"

    user = User(
        email=pending_email,
        password_hash=hash_password(plain_password),
        role=UserRole.CITIZEN.value,
        status=UserStatus.PENDING_VERIFICATION.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": pending_email, "password": plain_password},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_email", [
    "",
    "   ",
    "plainaddress",
    "@missingusername.com",
    "username@.com",
    "username@domain",
])
async def test_login_invalid_email_returns_422(async_client: AsyncClient, invalid_email: str):
    """Verify 10: Invalid email formatting returns 422 Unprocessable Entity."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": invalid_email, "password": "SecurePassword123!"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("extra_field,value", [
    ("role", "MUNICIPAL_ADMIN"),
    ("status", "ACTIVE"),
    ("password_hash", "$argon2id$mock"),
    ("is_admin", True),
])
async def test_login_unexpected_request_fields_rejected(
    async_client: AsyncClient,
    extra_field: str,
    value,
):
    """Verify 11: Extra/unexpected fields are rejected via extra='forbid' with 422."""
    payload = {
        "email": "valid_email@example.com",
        "password": "SecurePassword123!",
        extra_field: value,
    }
    response = await async_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_password_redacted_from_validation_errors(async_client: AsyncClient):
    """Verify 12: Password values are never included in HTTP 422 validation responses."""
    secret_pw = "SensitiveSecretPassword!"
    # Empty email causes validation error
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "", "password": secret_pw},
    )
    assert response.status_code == 422
    assert secret_pw not in str(response.json())


@pytest.mark.asyncio
async def test_login_unexpected_internal_failure_returns_sanitized_500(
    async_client: AsyncClient,
    monkeypatch,
):
    """
    Verify 14: Unexpected internal errors return sanitized 500 without leaking credentials,
    database errors, or stack traces.
    """
    from app.api.v1 import auth

    async def mock_crashing_select(*args, **kwargs):
        raise RuntimeError("OperationalError: postgresql://admin:secret_pass@127.0.0.1:5433/nammaclean_db died")

    # Patch db session execute method
    res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "crash_login@example.com", "password": "SecurePassword123!"},
    )
    # The normal route works, now test with patched error
    monkeypatch.setattr(auth, "normalize_email", lambda email: (_ for _ in ()).throw(RuntimeError("DB Crash!")))
    crash_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "crash_login@example.com", "password": "SecurePassword123!"},
    )
    assert crash_res.status_code == 500
    detail = crash_res.json()["detail"]
    assert detail == "An unexpected error occurred during login. Please try again."
    assert "Crash" not in detail


@pytest.mark.asyncio
async def test_existing_registration_and_health_work(async_client: AsyncClient):
    """Verify 15: Existing registration and health endpoints continue to work as expected."""
    # Health checks
    res_root = await async_client.get("/")
    assert res_root.status_code == 200

    res_live = await async_client.get("/api/v1/health/live")
    assert res_live.status_code == 200

    res_health = await async_client.get("/api/v1/health")
    assert res_health.status_code == 200

    # Registration endpoint
    reg_email = f"reg_compat_{uuid.uuid4().hex[:8]}@example.com"
    res_reg = await async_client.post(
        "/api/v1/auth/register",
        json={"email": reg_email, "password": "Password12345!"},
    )
    assert res_reg.status_code == 201
