"""
API integration tests for NammaClean Stage 2.7.1: Authenticated User Profile API.
Tests GET /api/v1/users/me endpoint for authentication, secret exclusion, role support,
identity spoofing resistance, and inactive user rejection.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import jwt
from app.core.security import (
    create_access_token,
    hash_password,
    get_jwt_secret_key,
    validate_jwt_algorithm,
)
from app.models.enums import UserRole, UserStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_get_current_user_profile_success(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Authenticated GET /api/v1/users/me returns HTTP 200 OK.
    2. Response returns exact database-backed fields: id, email, role, status, created_at, updated_at.
    3. Password hash and secrets are strictly excluded from response.
    """
    email = f"profile_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    token = create_access_token(subject=user.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == str(user.id)
    assert data["email"] == email.lower()
    assert data["role"] == UserRole.CITIZEN.value
    assert data["status"] == UserStatus.ACTIVE.value
    assert "created_at" in data
    assert "updated_at" in data

    # Verify absence of secrets
    assert "password_hash" not in data
    assert "password" not in data
    assert "token" not in data

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_get_current_user_profile_unauthenticated(async_client: AsyncClient):
    """Verify: Unauthenticated request receives HTTP 401 with WWW-Authenticate header."""
    response = await async_client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials."


@pytest.mark.asyncio
async def test_get_current_user_profile_invalid_token(async_client: AsyncClient):
    """Verify: Request with invalid token receives HTTP 401 with WWW-Authenticate header."""
    headers = {"Authorization": "Bearer invalid.token.signature"}
    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials."


@pytest.mark.asyncio
async def test_get_current_user_profile_expired_token(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Request with expired token receives HTTP 401."""
    user = User(
        email=f"expired_profile_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": str(user.id),
        "iat": int((now - timedelta(minutes=60)).timestamp()),
        "exp": int((now - timedelta(minutes=30)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        expired_payload,
        get_jwt_secret_key(),
        algorithm=validate_jwt_algorithm(),
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials."

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_get_current_user_profile_disabled_user(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: A user with DISABLED status cannot access /users/me (HTTP 401)."""
    disabled_user = User(
        email=f"disabled_profile_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.DISABLED.value,
    )
    async_db_session.add(disabled_user)
    await async_db_session.commit()

    token = create_access_token(subject=disabled_user.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials."

    # Cleanup
    await async_db_session.delete(disabled_user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_get_current_user_profile_pending_verification_user(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: A user with PENDING_VERIFICATION status cannot access /users/me (HTTP 401)."""
    pending_user = User(
        email=f"pending_profile_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.PENDING_VERIFICATION.value,
    )
    async_db_session.add(pending_user)
    await async_db_session.commit()

    token = create_access_token(subject=pending_user.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials."

    # Cleanup
    await async_db_session.delete(pending_user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_get_current_user_profile_does_not_trust_client_supplied_ids(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify: The endpoint identifies the user exclusively from the validated JWT subject.
    Supplying a different user_id or id in query parameters does NOT return another user's profile.
    """
    user_a = User(
        email=f"user_a_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    user_b = User(
        email=f"user_b_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([user_a, user_b])
    await async_db_session.commit()

    token_a = create_access_token(subject=user_a.id)
    headers = {"Authorization": f"Bearer {token_a}"}

    # Attempt to query user_b's ID via query params
    response = await async_client.get(
        f"/api/v1/users/me?user_id={user_b.id}&id={user_b.id}",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()

    # The returned profile MUST strictly be user_a
    assert data["id"] == str(user_a.id)
    assert data["email"] == user_a.email
    assert data["role"] == UserRole.CITIZEN.value

    # Cleanup
    await async_db_session.delete(user_a)
    await async_db_session.delete(user_b)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_get_current_user_profile_supports_all_roles(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Users belonging to any of the 5 roles can retrieve their profile."""
    users = []
    for role_enum in UserRole:
        u = User(
            email=f"{role_enum.value.lower()}_prof_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("ValidPassword123!"),
            role=role_enum.value,
            status=UserStatus.ACTIVE.value,
        )
        async_db_session.add(u)
        users.append(u)

    await async_db_session.commit()

    for u in users:
        token = create_access_token(subject=u.id)
        headers = {"Authorization": f"Bearer {token}"}
        response = await async_client.get("/api/v1/users/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(u.id)
        assert data["role"] == u.role

    # Cleanup
    for u in users:
        await async_db_session.delete(u)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_get_current_user_profile_response_excludes_all_secrets(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Response body strictly excludes password_hash, password, and internal credentials."""
    user = User(
        email=f"secret_test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("SuperSecret123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    token = create_access_token(subject=user.id)
    headers = {"Authorization": f"Bearer {token}"}
    response = await async_client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    raw_text = response.text.lower()
    assert "password_hash" not in raw_text
    assert "supersecret123!" not in raw_text
    assert "argon2" not in raw_text

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()
