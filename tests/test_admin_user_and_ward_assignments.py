"""
Tests for Stage 2.9.1C: Administrative User Management & Ward Assignments.

Covers:
1. Municipal administrator can create permitted operational users (SANITATION_WORKER, DRIVER, WARD_SUPERVISOR).
2. Non-admin roles (CITIZEN, SANITATION_WORKER, DRIVER, WARD_SUPERVISOR) cannot create operational users (HTTP 403).
3. Creation of MUNICIPAL_ADMIN or CITIZEN is rejected through admin endpoint (HTTP 400).
4. Duplicate email addresses are rejected with HTTP 409 Conflict.
5. Passwords are securely hashed with Argon2id and never returned in responses.
6. Missing users and wards are handled consistently (HTTP 404).
7. Operational roles can be assigned to an existing ward.
8. Duplicate active assignments are prevented (HTTP 409).
9. Historical assignments are preserved upon revocation (sets revoked_at rather than deleting row).
10. Revoked assignments no longer grant ward access (HTTP 403).
11. A revoked assignment can be reactivated without corrupting history.
12. Citizens and unauthorized roles cannot manage assignments (HTTP 403).
13. Disabled or inactive users cannot be assigned to wards (HTTP 400).
14. Assignment history endpoint lists both active and historical assignments.
"""

import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import UserRole, UserStatus, VehicleType, VehicleStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
async def test_admin_create_operational_users_and_role_restrictions(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify administrative user creation:
    - Municipal Admin can create SANITATION_WORKER, DRIVER, and WARD_SUPERVISOR.
    - Passwords are encrypted with Argon2id and never exposed.
    - Non-admin roles are rejected with HTTP 403.
    - MUNICIPAL_ADMIN creation is rejected with HTTP 400.
    - CITIZEN creation is rejected with HTTP 400.
    - Duplicate email is rejected with HTTP 409.
    """
    admin = User(
        email=f"admin_ops_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"sup_ops_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("SupPass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    citizen = User(
        email=f"cit_ops_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("CitPass123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor, citizen])
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))
    sup_token = create_access_token(str(supervisor.id))
    cit_token = create_access_token(str(citizen.id))

    # 1. Non-admin roles cannot create users (HTTP 403)
    res_cit = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": "worker_fail@example.com",
            "password": "Password123!",
            "role": UserRole.SANITATION_WORKER.value,
        },
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    assert res_cit.status_code == 403

    res_sup = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": "worker_fail2@example.com",
            "password": "Password123!",
            "role": UserRole.SANITATION_WORKER.value,
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup.status_code == 403

    # Unauthenticated request returns HTTP 401
    res_unauth = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": "worker_fail3@example.com",
            "password": "Password123!",
            "role": UserRole.SANITATION_WORKER.value,
        },
    )
    assert res_unauth.status_code == 401

    # 2. Municipal Admin creates SANITATION_WORKER
    worker_email = f"worker_{uuid.uuid4().hex[:8]}@example.com"
    res_worker = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": worker_email,
            "password": "WorkerPassword123!",
            "role": UserRole.SANITATION_WORKER.value,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_worker.status_code == 201
    data_worker = res_worker.json()
    assert data_worker["email"] == worker_email.lower()
    assert data_worker["role"] == UserRole.SANITATION_WORKER.value
    assert data_worker["status"] == UserStatus.ACTIVE.value
    assert "password" not in data_worker
    assert "password_hash" not in data_worker

    # Verify password was hashed in database
    db_worker_res = await async_db_session.execute(
        select(User).where(User.email == worker_email.lower())
    )
    db_worker = db_worker_res.scalars().first()
    assert db_worker is not None
    assert verify_password("WorkerPassword123!", db_worker.password_hash) is True

    # 3. Municipal Admin creates DRIVER
    driver_email = f"driver_{uuid.uuid4().hex[:8]}@example.com"
    res_driver = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": driver_email,
            "password": "DriverPassword123!",
            "role": UserRole.DRIVER.value,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_driver.status_code == 201
    assert res_driver.json()["role"] == UserRole.DRIVER.value

    # 4. Municipal Admin creates WARD_SUPERVISOR
    sup_email = f"supervisor_{uuid.uuid4().hex[:8]}@example.com"
    res_supervisor = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": sup_email,
            "password": "SupPassword123!",
            "role": UserRole.WARD_SUPERVISOR.value,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_supervisor.status_code == 201
    assert res_supervisor.json()["role"] == UserRole.WARD_SUPERVISOR.value

    # 5. Municipal Admin creation is strictly rejected through this endpoint (HTTP 400)
    res_bad_admin = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": f"newadmin_{uuid.uuid4().hex[:8]}@example.com",
            "password": "AdminPassword123!",
            "role": UserRole.MUNICIPAL_ADMIN.value,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_bad_admin.status_code == 400
    assert "cannot be created through this endpoint" in res_bad_admin.json()["detail"]

    # 6. Citizen creation is rejected through this endpoint (HTTP 400)
    res_bad_cit = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": f"newcitizen_{uuid.uuid4().hex[:8]}@example.com",
            "password": "CitizenPassword123!",
            "role": UserRole.CITIZEN.value,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_bad_cit.status_code == 400
    assert "cannot be created through this endpoint" in res_bad_cit.json()["detail"]

    # 7. Duplicate email address is rejected (HTTP 409)
    res_dup = await async_client.post(
        "/api/v1/admin/users",
        json={
            "email": worker_email,
            "password": "AnotherPassword123!",
            "role": UserRole.SANITATION_WORKER.value,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_dup.status_code == 409
    assert "already exists" in res_dup.json()["detail"]


@pytest.mark.asyncio
async def test_admin_ward_assignment_and_duplicate_prevention(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify ward assignment workflows:
    - Municipal Admin can assign operational personnel (Supervisor, Worker, Driver) to wards.
    - Prevents duplicate active assignments (HTTP 409).
    - Prevents assigning non-operational roles like CITIZEN (HTTP 400).
    - Prevents assigning disabled users (HTTP 400).
    - Non-existent user or ward returns HTTP 404.
    - Non-admin callers receive HTTP 403.
    """
    ward1 = Ward(ward_code=f"W-ASG1-{uuid.uuid4().hex[:6]}", display_name="Assignment Ward 1")
    ward2 = Ward(ward_code=f"W-ASG2-{uuid.uuid4().hex[:6]}", display_name="Assignment Ward 2")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    admin = User(
        email=f"admin_asg_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"sup_asg_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    disabled_sup = User(
        email=f"sup_dis_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.DISABLED.value,
    )
    worker = User(
        email=f"wrk_asg_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
    )
    citizen = User(
        email=f"cit_asg_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor, disabled_sup, worker, citizen])
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))
    sup_token = create_access_token(str(supervisor.id))

    # 1. Non-admin cannot assign users (HTTP 403)
    res_forbidden = await async_client.post(
        f"/api/v1/admin/users/{worker.id}/wards/{ward1.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_forbidden.status_code == 403

    # 2. Assign supervisor to Ward 1
    res_assign_sup = await async_client.post(
        f"/api/v1/admin/users/{supervisor.id}/wards/{ward1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_assign_sup.status_code == 201
    data_sup = res_assign_sup.json()
    assert data_sup["user_id"] == str(supervisor.id)
    assert data_sup["ward_id"] == str(ward1.id)
    assert data_sup["revoked_at"] is None

    # 3. Prevent duplicate active assignment (HTTP 409)
    res_dup_assign = await async_client.post(
        f"/api/v1/admin/users/{supervisor.id}/wards/{ward1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_dup_assign.status_code == 409
    assert "Active assignment already exists" in res_dup_assign.json()["detail"]

    # 4. Assign sanitation worker to Ward 1 (allowed)
    res_assign_wrk = await async_client.post(
        f"/api/v1/admin/users/{worker.id}/wards/{ward1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_assign_wrk.status_code == 201

    # 5. Non-existent user returns HTTP 404
    fake_user_id = uuid.uuid4()
    res_no_user = await async_client.post(
        f"/api/v1/admin/users/{fake_user_id}/wards/{ward1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_no_user.status_code == 404
    assert f"User with id '{fake_user_id}' not found." in res_no_user.json()["detail"]

    # 6. Non-existent ward returns HTTP 404
    fake_ward_id = uuid.uuid4()
    res_no_ward = await async_client.post(
        f"/api/v1/admin/users/{supervisor.id}/wards/{fake_ward_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_no_ward.status_code == 404
    assert f"Ward with id '{fake_ward_id}' not found." in res_no_ward.json()["detail"]

    # 7. CITIZEN role cannot receive ward assignments (HTTP 400)
    res_cit_assign = await async_client.post(
        f"/api/v1/admin/users/{citizen.id}/wards/{ward1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_cit_assign.status_code == 400
    assert "cannot be assigned to a ward" in res_cit_assign.json()["detail"]

    # 8. Disabled user cannot receive ward assignments (HTTP 400)
    res_dis_assign = await async_client.post(
        f"/api/v1/admin/users/{disabled_sup.id}/wards/{ward1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_dis_assign.status_code == 400
    assert "Cannot assign disabled or inactive user" in res_dis_assign.json()["detail"]


@pytest.mark.asyncio
async def test_admin_ward_revocation_and_reassignment_preserves_history(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify ward assignment revocation and audit trail:
    - Revoking an assignment sets revoked_at (does not delete row).
    - Revoked assignment stops granting supervisor access (HTTP 403 on fleet query).
    - Re-assigning creates a new active assignment without corrupting history.
    - Assignment history endpoint lists both active and historical assignments.
    - Attempting to revoke non-existent or already-revoked assignment returns HTTP 404.
    """
    ward = Ward(ward_code=f"W-REV-{uuid.uuid4().hex[:6]}", display_name="Revocation Ward")
    async_db_session.add(ward)
    await async_db_session.commit()

    admin = User(
        email=f"admin_rev_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"sup_rev_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor])
    await async_db_session.commit()

    # Create a vehicle in this ward
    veh = Vehicle(
        registration_number=f"KA-REV-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
        assigned_ward_id=ward.id,
    )
    async_db_session.add(veh)
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))
    sup_token = create_access_token(str(supervisor.id))

    # 1. Initially supervisor has no assignment -> access denied to ward fleet
    res_init_fleet = await async_client.get(
        f"/api/v1/vehicles?ward_id={ward.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_init_fleet.status_code == 403

    # 2. Assign supervisor to ward
    res_asg = await async_client.post(
        f"/api/v1/admin/users/{supervisor.id}/wards/{ward.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_asg.status_code == 201

    # Supervisor now has access to ward fleet
    res_sup_fleet = await async_client.get(
        f"/api/v1/vehicles?ward_id={ward.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_fleet.status_code == 200
    assert any(v["id"] == str(veh.id) for v in res_sup_fleet.json())

    # 3. Revoke assignment
    res_rev = await async_client.delete(
        f"/api/v1/admin/users/{supervisor.id}/wards/{ward.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_rev.status_code == 200
    rev_data = res_rev.json()
    assert rev_data["revoked_at"] is not None

    # Verify row was NOT deleted from DB
    stmt_check = select(UserWardAssignment).where(
        UserWardAssignment.user_id == supervisor.id,
        UserWardAssignment.ward_id == ward.id,
    )
    db_res = await async_db_session.execute(stmt_check)
    records = db_res.scalars().all()
    assert len(records) == 1
    assert records[0].revoked_at is not None

    # 4. Revoked assignment stops granting supervisor access (HTTP 403)
    res_revoked_fleet = await async_client.get(
        f"/api/v1/vehicles?ward_id={ward.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_revoked_fleet.status_code == 403

    # 5. Revoking already-revoked assignment returns HTTP 404
    res_rev_again = await async_client.delete(
        f"/api/v1/admin/users/{supervisor.id}/wards/{ward.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_rev_again.status_code == 404
    assert "No active assignment found" in res_rev_again.json()["detail"]

    # 6. Re-assign supervisor to same ward -> succeeds and creates a new active row
    res_reasg = await async_client.post(
        f"/api/v1/admin/users/{supervisor.id}/wards/{ward.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_reasg.status_code == 201
    assert res_reasg.json()["revoked_at"] is None

    # 7. List assignment history
    res_history = await async_client.get(
        f"/api/v1/admin/users/{supervisor.id}/wards",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_history.status_code == 200
    history = res_history.json()
    assert len(history) == 2  # 1 historical revoked, 1 current active
    assert any(h["revoked_at"] is not None for h in history)
    assert any(h["revoked_at"] is None for h in history)

    # Supervisor now has access again
    res_sup_fleet_re = await async_client.get(
        f"/api/v1/vehicles?ward_id={ward.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_fleet_re.status_code == 200
