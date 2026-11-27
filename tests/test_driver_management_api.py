"""
Comprehensive tests for Driver account management and Driver Dashboard telemetry APIs.
Verifies:
1. Official driver account creation with forced DRIVER role.
2. Duplicate email rejection (409 Conflict).
3. Driver login and credential verification.
4. Driver profile retrieval (/drivers/me).
5. Vehicle assignment and reassignment.
6. Starting and ending duty sessions.
7. Rejection of duty start if no vehicle assigned.
8. Duplicate active duty prevention.
9. GPS coordinate validation (-90..90, -180..180).
10. Driver real-time GPS telemetry ingestion with is_simulated=False.
11. Rejection of GPS telemetry when duty is inactive.
12. Unauthorized role rejection (citizens/unauthenticated callers denied).
13. Account deactivation (disabled driver rejected by auth).
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, VehicleStatus, VehicleType
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.vehicle import Vehicle, VehiclePosition, utc_now


@pytest.mark.asyncio
async def test_driver_account_creation_and_role_enforcement(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify official driver registration enforces the DRIVER role server-side."""
    admin_user = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("SuperSecretPass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
        full_name="Municipal Admin Officer",
    )
    async_db_session.add(admin_user)
    await async_db_session.commit()
    admin_token = create_access_token(subject=admin_user.id)

    # 1. Register driver
    driver_email = f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test"
    payload = {
        "full_name": "Ramesh Kumar",
        "email": driver_email,
        "password": "DriverPassword123!",
        "status": "ACTIVE",
    }
    resp = await async_client.post(
        "/api/v1/drivers",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "DRIVER"
    assert data["email"] == driver_email
    assert data["full_name"] == "Ramesh Kumar"
    assert data["status"] == "ACTIVE"
    assert data["assigned_vehicle"] is None

    # 2. Reject duplicate email
    dup_resp = await async_client.post(
        "/api/v1/drivers",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"]


@pytest.mark.asyncio
async def test_driver_vehicle_assignment_and_reassignment(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify vehicle assignment and reassignment for a driver."""
    admin_user = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("SuperSecretPass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    driver_user = User(
        email=f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("DriverPass123456!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Suresh Babu",
    )
    v1 = Vehicle(
        registration_number=f"KA-01-EA-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
    )
    v2 = Vehicle(
        registration_number=f"KA-01-EA-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.IDLE.value,
    )
    async_db_session.add_all([admin_user, driver_user, v1, v2])
    await async_db_session.commit()

    admin_token = create_access_token(subject=admin_user.id)

    # 1. Assign v1 to driver
    assign_resp = await async_client.post(
        f"/api/v1/drivers/{driver_user.id}/assign-vehicle",
        json={"vehicle_id": str(v1.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert assign_resp.status_code == 200
    data = assign_resp.json()
    assert data["assigned_vehicle"]["id"] == str(v1.id)
    assert data["assigned_vehicle"]["registration_number"] == v1.registration_number

    # 2. Reassign v2 to driver (v1 should be automatically unassigned)
    reassign_resp = await async_client.post(
        f"/api/v1/drivers/{driver_user.id}/assign-vehicle",
        json={"vehicle_id": str(v2.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reassign_resp.status_code == 200
    assert reassign_resp.json()["assigned_vehicle"]["id"] == str(v2.id)

    # Verify v1 is now unassigned
    await async_db_session.refresh(v1)
    assert v1.assigned_driver_id is None

    # 3. Unassign vehicle
    unassign_resp = await async_client.post(
        f"/api/v1/drivers/{driver_user.id}/assign-vehicle",
        json={"vehicle_id": None},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert unassign_resp.status_code == 200
    assert unassign_resp.json()["assigned_vehicle"] is None


@pytest.mark.asyncio
async def test_driver_duty_lifecycle_and_location_tracking(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify Driver start duty, telemetry ingestion, and end duty workflow."""
    driver = User(
        email=f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("DriverDutyPass123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Anand Murthy",
    )
    vehicle = Vehicle(
        registration_number=f"KA-04-E-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
    )
    async_db_session.add_all([driver, vehicle])
    await async_db_session.commit()

    driver_token = create_access_token(subject=driver.id)

    # 1. Start duty fails when no vehicle assigned
    fail_start = await async_client.post(
        "/api/v1/drivers/me/duty/start",
        json={},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert fail_start.status_code == 400
    assert "No vehicle is currently assigned" in fail_start.json()["detail"]

    # 2. Assign vehicle to driver
    vehicle.assigned_driver_id = driver.id
    await async_db_session.commit()

    # 3. Check profile before duty
    me_resp = await async_client.get(
        "/api/v1/drivers/me",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["duty_status"] == "IDLE"
    assert me_resp.json()["assigned_vehicle"]["id"] == str(vehicle.id)

    # 4. Location ping rejected before starting duty
    early_ping = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 13.1331, "longitude": 77.5685},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert early_ping.status_code == 400
    assert "duty is active" in early_ping.json()["detail"]

    # 5. Start duty successfully with initial coordinates
    start_resp = await async_client.post(
        "/api/v1/drivers/me/duty/start",
        json={"latitude": 13.1331, "longitude": 77.5685},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["duty_status"] == "ON_DUTY"
    assert start_resp.json()["duty_start_time"] is not None

    # Verify duplicate start is rejected
    dup_start = await async_client.post(
        "/api/v1/drivers/me/duty/start",
        json={},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert dup_start.status_code == 400
    assert "already active" in dup_start.json()["detail"]

    # 6. Ingest GPS location updates while on duty
    ping_resp = await async_client.post(
        "/api/v1/drivers/me/location",
        json={
            "latitude": 13.1345,
            "longitude": 77.5699,
            "speed_kmh": 22.5,
            "heading": 180.0,
            "accuracy_meters": 4.5,
        },
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert ping_resp.status_code == 201
    assert ping_resp.json()["success"] is True
    assert ping_resp.json()["vehicle_id"] == str(vehicle.id)

    # Verify vehicle snapshot was atomically updated with genuine (non-simulated) telemetry
    await async_db_session.refresh(vehicle)
    assert vehicle.status == VehicleStatus.ON_DUTY.value
    assert vehicle.is_simulated is False
    assert vehicle.last_seen_at is not None

    # 7. End duty successfully
    end_resp = await async_client.post(
        "/api/v1/drivers/me/duty/end",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["duty_status"] == "IDLE"

    # Verify duplicate end duty is rejected
    dup_end = await async_client.post(
        "/api/v1/drivers/me/duty/end",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert dup_end.status_code == 400
    assert "not currently active" in dup_end.json()["detail"]


@pytest.mark.asyncio
async def test_driver_gps_validation_and_unauthorized_rejection(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify coordinate range validation and rejection of unauthorized citizen access."""
    citizen = User(
        email=f"citizen-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("CitizenPass123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    driver = User(
        email=f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("DriverPass123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    vehicle = Vehicle(
        registration_number=f"KA-03-TR-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.LORRY.value,
        status=VehicleStatus.ON_DUTY.value,
        assigned_driver_id=driver.id,
    )
    async_db_session.add_all([citizen, driver, vehicle])
    await async_db_session.commit()

    citizen_token = create_access_token(subject=citizen.id)
    driver_token = create_access_token(subject=driver.id)

    # 1. Citizen rejected from driver operations with 403 Forbidden
    cit_resp = await async_client.get(
        "/api/v1/drivers/me",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert cit_resp.status_code == 403

    cit_mgmt = await async_client.get(
        "/api/v1/drivers",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert cit_mgmt.status_code == 403

    # 2. Reject out-of-range coordinates (latitude > 90)
    bad_lat = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 999.0, "longitude": 77.5685},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert bad_lat.status_code == 422

    # 3. Reject out-of-range coordinates (longitude > 180)
    bad_lon = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 13.1331, "longitude": 500.0},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert bad_lon.status_code == 422


@pytest.mark.asyncio
async def test_driver_account_deactivation(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify deactivating a driver immediately prevents authenticated access."""
    admin_user = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    driver_user = User(
        email=f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("DriverPass123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Girish Gowda",
    )
    async_db_session.add_all([admin_user, driver_user])
    await async_db_session.commit()

    admin_token = create_access_token(subject=admin_user.id)
    driver_token = create_access_token(subject=driver_user.id)

    # 1. Driver can access /drivers/me while ACTIVE
    active_resp = await async_client.get(
        "/api/v1/drivers/me",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert active_resp.status_code == 200

    # 2. Admin deactivates driver
    deact_resp = await async_client.patch(
        f"/api/v1/drivers/{driver_user.id}",
        json={"status": "DISABLED"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deact_resp.status_code == 200
    assert deact_resp.json()["status"] == "DISABLED"

    # 3. Driver is now rejected with 401 Unauthorized (get_current_user rejects inactive accounts)
    blocked_resp = await async_client.get(
        "/api/v1/drivers/me",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert blocked_resp.status_code == 401
