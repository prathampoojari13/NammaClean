"""
Tests for NammaClean Stage 2.6.1: Current User Authentication Dependency.
Verifies that get_current_user resolves the active user from the database,
enforces status policy, sets WWW-Authenticate headers, and safely rejects
missing, malformed, expired, invalid, nonexistent, and inactive user credentials.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
import jwt
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, _get_auth_exception
from app.core.config import settings
from app.core.security import create_access_token, hash_password, get_jwt_secret_key, validate_jwt_algorithm
from app.models.enums import UserRole, UserStatus
from app.models.user import User


# Lightweight test application utilizing get_current_user dependency
sample_auth_app = FastAPI()

@sample_auth_app.get("/test/protected")
async def protected_endpoint(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role,
        "status": current_user.status,
    }


@pytest.fixture
def auth_client() -> AsyncClient:
    """AsyncClient wired directly to sample_auth_app."""
    transport = ASGITransport(app=sample_auth_app)
    return AsyncClient(transport=transport, base_url="http://testserver")



@pytest.mark.asyncio
async def test_valid_token_resolves_correct_active_user(
    auth_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. A valid token resolves the correct active user.
    2. The returned user is loaded from the database with correct role and status.
    """
    unique_email = f"auth_user_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=unique_email,
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()
    await async_db_session.refresh(user)

    token = create_access_token(subject=user.id, extra_claims={"role": user.role})
    headers = {"Authorization": f"Bearer {token}"}

    # HTTP call through test app
    response = await auth_client.get("/test/protected", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user.id)
    assert data["email"] == unique_email
    assert data["role"] == UserRole.CITIZEN.value
    assert data["status"] == UserStatus.ACTIVE.value

    # Direct dependency call verification
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    resolved_user = await get_current_user(credentials=creds, db=async_db_session)
    assert resolved_user.id == user.id
    assert resolved_user.email == unique_email

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_missing_bearer_credentials_rejected(auth_client: AsyncClient):
    """Verify: Missing Authorization header is rejected with 401 and WWW-Authenticate: Bearer."""
    response = await auth_client.get("/test/protected")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials."


@pytest.mark.asyncio
async def test_non_bearer_scheme_rejected(auth_client: AsyncClient):
    """Verify: Authorization headers using schemes other than Bearer (e.g. Basic) are rejected with 401."""
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_malformed_token_rejected(auth_client: AsyncClient):
    """Verify: Malformed or unparseable JWT string is rejected with 401."""
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": "Bearer not.a.valid.jwt.token"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials."


@pytest.mark.asyncio
async def test_invalid_signature_token_rejected(auth_client: AsyncClient):
    """Verify: Tokens signed with a different key are rejected with 401."""
    fake_payload = {
        "sub": str(uuid.uuid4()),
        "iat": 1000000000,
        "exp": 2000000000,
        "jti": str(uuid.uuid4()),
    }
    tampered_token = jwt.encode(
        fake_payload,
        "wrong_signing_key_at_least_32_characters_long!",
        algorithm="HS256",
    )
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_expired_token_rejected(auth_client: AsyncClient):
    """Verify: Expired tokens are rejected with 401."""
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": str(uuid.uuid4()),
        "iat": int((now - timedelta(minutes=60)).timestamp()),
        "exp": int((now - timedelta(minutes=30)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    expired_token = jwt.encode(
        expired_payload,
        get_jwt_secret_key(),
        algorithm=validate_jwt_algorithm(),
    )
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_missing_required_claims_token_rejected(auth_client: AsyncClient):
    """Verify: Tokens missing jti or other mandatory claims are rejected with 401."""
    now = datetime.now(timezone.utc)
    missing_jti_payload = {
        "sub": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
    }
    token = jwt.encode(
        missing_jti_payload,
        get_jwt_secret_key(),
        algorithm=validate_jwt_algorithm(),
    )
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_invalid_uuid_subject_token_rejected(auth_client: AsyncClient):
    """Verify: Tokens with non-UUID subjects are rejected with 401."""
    now = datetime.now(timezone.utc)
    bad_sub_payload = {
        "sub": "not-a-valid-uuid-identifier",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        bad_sub_payload,
        get_jwt_secret_key(),
        algorithm=validate_jwt_algorithm(),
    )
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_nonexistent_user_token_rejected(auth_client: AsyncClient):
    """Verify: A valid token whose subject UUID does not exist in the database is rejected with 401."""
    nonexistent_id = uuid.uuid4()
    token = create_access_token(subject=nonexistent_id)

    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials."


@pytest.mark.asyncio
async def test_disabled_user_token_rejected(
    auth_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Valid token for a DISABLED account is rejected with 401."""
    unique_email = f"disabled_tok_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=unique_email,
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.DISABLED.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    token = create_access_token(subject=user.id)
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials."

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_pending_verification_user_token_rejected(
    auth_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Valid token for a PENDING_VERIFICATION account is rejected with 401."""
    unique_email = f"pending_tok_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=unique_email,
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.PENDING_VERIFICATION.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    token = create_access_token(subject=user.id)
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials."

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_public_error_responses_do_not_expose_secrets_or_internals(auth_client: AsyncClient):
    """Verify: Authentication error responses contain only generic sanitized messages."""
    response = await auth_client.get(
        "/test/protected",
        headers={"Authorization": "Bearer malformed.secret.token"},
    )
    body = response.text
    assert "jwt" not in body.lower()
    assert "token" not in body.lower()
    assert "signature" not in body.lower()
    assert "postgres" not in body.lower()
    assert "sqlalchemy" not in body.lower()


@pytest.mark.asyncio
async def test_existing_registration_login_health_functional(async_client: AsyncClient):
    """Verify: Existing endpoints continue to function without regressions."""
    # Health checks
    r_root = await async_client.get("/")
    assert r_root.status_code == 200

    r_live = await async_client.get("/api/v1/health/live")
    assert r_live.status_code == 200

    r_health = await async_client.get("/api/v1/health")
    assert r_health.status_code == 200

    # Registration & Login round-trip
    reg_email = f"compat_dep_{uuid.uuid4().hex[:8]}@example.com"
    reg_pass = "SecurePass1234!"
    r_reg = await async_client.post(
        "/api/v1/auth/register",
        json={"email": reg_email, "password": reg_pass},
    )
    assert r_reg.status_code == 201

    r_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": reg_email, "password": reg_pass},
    )
    assert r_login.status_code == 200
    assert "access_token" in r_login.json()
