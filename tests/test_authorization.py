"""
Tests for NammaClean Stage 2.6.2: Role-Based Authorization Foundation.
Verifies that require_roles restricts access to authorized roles, delegates
authentication to get_current_user (returning 401 when unauthenticated),
enforces database-backed role authority (returning 403 on role mismatch),
and supports multi-role evaluation across all 5 system roles.
"""

import uuid
import pytest
from fastapi import FastAPI, Depends, status
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User


# Test application defining protected endpoints with different role requirements
authz_test_app = FastAPI()

@authz_test_app.get("/admin-only")
async def admin_only_endpoint(user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN))):
    return {"id": str(user.id), "role": user.role}

@authz_test_app.get("/supervisor-or-admin")
async def supervisor_or_admin_endpoint(
    user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN))
):
    return {"id": str(user.id), "role": user.role}

@authz_test_app.get("/worker-or-driver")
async def worker_or_driver_endpoint(
    user: User = Depends(require_roles(UserRole.SANITATION_WORKER, UserRole.DRIVER))
):
    return {"id": str(user.id), "role": user.role}

@authz_test_app.get("/citizen-only")
async def citizen_only_endpoint(user: User = Depends(require_roles(UserRole.CITIZEN))):
    return {"id": str(user.id), "role": user.role}


@pytest.fixture
def authz_client() -> AsyncClient:
    """AsyncClient wired to authz_test_app."""
    transport = ASGITransport(app=authz_test_app)
    return AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_active_user_with_allowed_role_authorized(
    authz_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: An active user with an allowed role receives HTTP 200 and access to resource."""
    admin_user = User(
        email=f"admin_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(admin_user)
    await async_db_session.commit()

    token = create_access_token(subject=admin_user.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await authz_client.get("/admin-only", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(admin_user.id)
    assert data["role"] == UserRole.MUNICIPAL_ADMIN.value

    # Cleanup
    await async_db_session.delete(admin_user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_active_user_with_disallowed_role_receives_403(
    authz_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: An active user with a disallowed role receives HTTP 403 Forbidden."""
    citizen_user = User(
        email=f"citizen_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(citizen_user)
    await async_db_session.commit()

    token = create_access_token(subject=citizen_user.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await authz_client.get("/admin-only", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions for this resource."

    # Cleanup
    await async_db_session.delete(citizen_user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_unauthenticated_request_receives_401(authz_client: AsyncClient):
    """Verify: Unauthenticated request receives HTTP 401 Unauthorized (not 403)."""
    response = await authz_client.get("/admin-only")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials."


@pytest.mark.asyncio
async def test_invalid_token_receives_401(authz_client: AsyncClient):
    """Verify: Invalid token receives HTTP 401 Unauthorized (not 403)."""
    response = await authz_client.get(
        "/admin-only",
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_every_existing_role_evaluated_correctly(
    authz_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify: Every existing UserRole value (all 5 roles) can be evaluated accurately
    against single and multi-role dependencies.
    """
    created_users = []
    for role_enum in UserRole:
        user = User(
            email=f"{role_enum.value.lower()}_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("Password123!"),
            role=role_enum.value,
            status=UserStatus.ACTIVE.value,
        )
        async_db_session.add(user)
        created_users.append(user)

    await async_db_session.commit()

    for user in created_users:
        token = create_access_token(subject=user.id)
        headers = {"Authorization": f"Bearer {token}"}

        # Test against citizen_only endpoint
        res_citizen = await authz_client.get("/citizen-only", headers=headers)
        if user.role == UserRole.CITIZEN.value:
            assert res_citizen.status_code == 200
        else:
            assert res_citizen.status_code == 403

        # Test against worker_or_driver endpoint
        res_worker_driver = await authz_client.get("/worker-or-driver", headers=headers)
        if user.role in (UserRole.SANITATION_WORKER.value, UserRole.DRIVER.value):
            assert res_worker_driver.status_code == 200
        else:
            assert res_worker_driver.status_code == 403

        # Test against supervisor_or_admin endpoint
        res_sup_admin = await authz_client.get("/supervisor-or-admin", headers=headers)
        if user.role in (UserRole.WARD_SUPERVISOR.value, UserRole.MUNICIPAL_ADMIN.value):
            assert res_sup_admin.status_code == 200
        else:
            assert res_sup_admin.status_code == 403

    # Cleanup
    for user in created_users:
        await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_database_role_determines_access_not_client_token_claim(
    authz_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify: Access is governed exclusively by the database-backed user record,
    NOT by a client-supplied or unverified role claim embedded in the token.
    """
    # Create user with CITIZEN role in database
    db_citizen = User(
        email=f"fake_admin_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(db_citizen)
    await async_db_session.commit()

    # Craft token with extra_claims alleging role=MUNICIPAL_ADMIN
    spoofed_token = create_access_token(
        subject=db_citizen.id,
        extra_claims={"role": UserRole.MUNICIPAL_ADMIN.value},
    )
    headers = {"Authorization": f"Bearer {spoofed_token}"}

    # Request admin endpoint: must be FORBIDDEN because DB record is CITIZEN
    response = await authz_client.get("/admin-only", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions for this resource."

    # Cleanup
    await async_db_session.delete(db_citizen)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_inactive_and_pending_users_rejected_by_auth(
    authz_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify: Even if a user has an allowed role (e.g. MUNICIPAL_ADMIN),
    disabled or pending-verification accounts fail authentication with HTTP 401.
    """
    disabled_admin = User(
        email=f"dis_admin_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.DISABLED.value,
    )
    pending_admin = User(
        email=f"pen_admin_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.PENDING_VERIFICATION.value,
    )
    async_db_session.add_all([disabled_admin, pending_admin])
    await async_db_session.commit()

    for user in (disabled_admin, pending_admin):
        token = create_access_token(subject=user.id)
        res = await authz_client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        # Fails at authentication stage with 401
        assert res.status_code == 401
        assert res.json()["detail"] == "Could not validate credentials."

    # Cleanup
    await async_db_session.delete(disabled_admin)
    await async_db_session.delete(pending_admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_forbidden_response_does_not_leak_secrets_or_internals(
    authz_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: 403 responses contain only generic sanitized error messages."""
    citizen = User(
        email=f"leak_test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(citizen)
    await async_db_session.commit()

    token = create_access_token(subject=citizen.id)
    response = await authz_client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    body = response.text
    assert "token" not in body.lower()
    assert "password" not in body.lower()
    assert "hash" not in body.lower()
    assert "postgres" not in body.lower()
    assert "sqlalchemy" not in body.lower()

    # Cleanup
    await async_db_session.delete(citizen)
    await async_db_session.commit()


def test_require_roles_factory_requires_arguments():
    """Verify: Invoking require_roles without any allowed role raises ValueError."""
    with pytest.raises(ValueError, match="at least one allowed role"):
        require_roles()
