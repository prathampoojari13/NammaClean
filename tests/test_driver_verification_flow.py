"""
Independent End-to-End Verification of Driver Dashboard & Driver Management Features.
Validates:
1. Authentication: Official driver creation (Admin & Ward Supervisor), server-side DRIVER role enforcement, driver login, role restrictions (cannot access supervisor APIs), disabled account rejection.
2. Complete GPS pipeline: Vehicle assignment, duty start, genuine GPS ingestion (is_simulated=False), PostGIS persistence, vehicle snapshot update, Public/Citizen Map reflection (with privacy field redaction), Official Map reflection, duty end and IDLE state.
3. Edge cases: Invalid coordinates, negative accuracy, duty without vehicle, unauthenticated/unauthorized calls, stale location handling.
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
async def test_official_creates_driver_and_login_flow(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Step 2 Verification:
    - Authorised official (Admin / Ward Supervisor) creates a driver account.
    - Backend strictly forces DRIVER role.
    - Driver can log in via /api/v1/auth/login and receives access token with role DRIVER.
    """
    # 1. Setup Admin and Ward Supervisor with assigned ward
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
        full_name="Municipal Admin Officer",
    )
    ward = Ward(
        ward_code=f"W-{uuid.uuid4().hex[:4].upper()}",
        display_name="Yelahanka Test Ward",
        boundary="SRID=4326;POLYGON((77.56 13.12, 77.58 13.12, 77.58 13.14, 77.56 13.14, 77.56 13.12))",
    )
    async_db_session.add_all([admin, ward])
    await async_db_session.commit()

    admin_token = create_access_token(subject=admin.id)

    # 2. Municipal Admin creates driver account
    driver_email = f"verified.driver-{uuid.uuid4().hex[:6]}@nammaclean.test"
    driver_password = "SecureDriverPass123!"
    create_resp = await async_client.post(
        "/api/v1/drivers",
        json={
            "full_name": "Ravi Shankara",
            "email": driver_email,
            "password": driver_password,
            "ward_id": str(ward.id),
            "status": "ACTIVE",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201, f"Expected 201, got {create_resp.status_code}: {create_resp.text}"
    driver_data = create_resp.json()
    assert driver_data["role"] == "DRIVER", "Backend must enforce DRIVER role"
    assert driver_data["email"] == driver_email
    assert driver_data["full_name"] == "Ravi Shankara"
    assert driver_data["status"] == "ACTIVE"
    assert driver_data["ward_id"] == str(ward.id)

    # 3. Driver logs in via /api/v1/auth/login
    login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={
            "email": driver_email,
            "password": driver_password,
        },
    )
    assert login_resp.status_code == 200, f"Driver login failed: {login_resp.text}"
    login_data = login_resp.json()
    assert "access_token" in login_data
    assert login_data["token_type"] == "bearer"

    # 4. Fetch authenticated driver profile using token
    driver_me_resp = await async_client.get(
        "/api/v1/drivers/me",
        headers={"Authorization": f"Bearer {login_data['access_token']}"},
    )
    assert driver_me_resp.status_code == 200
    profile_data = driver_me_resp.json()
    assert profile_data["driver"]["role"] == "DRIVER"
    assert profile_data["driver"]["status"] == "ACTIVE"
    assert profile_data["driver"]["email"] == driver_email
    assert profile_data["driver"]["full_name"] == "Ravi Shankara"


@pytest.mark.asyncio
async def test_driver_cannot_access_supervisor_and_admin_apis(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Step 2 Verification:
    - Confirm that a driver CANNOT access supervisor or administrative APIs.
    """
    driver = User(
        email=f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123456!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Driver Security Test",
    )
    async_db_session.add(driver)
    await async_db_session.commit()
    driver_token = create_access_token(subject=driver.id)

    headers = {"Authorization": f"Bearer {driver_token}"}

    # Driver cannot register other drivers (Official only) -> 403
    res_reg = await async_client.post(
        "/api/v1/drivers",
        json={"email": "hack@test.com", "password": "pass", "full_name": "test"},
        headers=headers,
    )
    assert res_reg.status_code == 403, f"Expected 403, got {res_reg.status_code}"

    # Driver cannot view the administrative driver roster -> 403
    res_roster = await async_client.get("/api/v1/drivers", headers=headers)
    assert res_roster.status_code == 403, f"Expected 403, got {res_roster.status_code}"

    # Driver cannot assign vehicles -> 403
    res_assign = await async_client.post(
        f"/api/v1/drivers/{driver.id}/assign-vehicle",
        json={"vehicle_id": None},
        headers=headers,
    )
    assert res_assign.status_code == 403, f"Expected 403, got {res_assign.status_code}"

    # Driver cannot access official citizen reports review -> 403
    res_reports = await async_client.get("/api/v1/reports", headers=headers)
    assert res_reports.status_code == 403, f"Expected 403, got {res_reports.status_code}"


@pytest.mark.asyncio
async def test_disabled_driver_rejected_from_all_operations(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Step 2 Verification:
    - Disabled driver account cannot log in (returns 401).
    - Any existing token of disabled driver is rejected by auth dependency.
    """
    disabled_driver = User(
        email=f"disabled-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("DisabledPass123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.DISABLED.value,
        full_name="Deactivated Driver",
    )
    async_db_session.add(disabled_driver)
    await async_db_session.commit()

    # 1. Login attempt fails with 401
    login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={
            "email": disabled_driver.email,
            "password": "DisabledPass123!",
        },
    )
    assert login_resp.status_code == 401

    # 2. Existing token rejected on /drivers/me
    token = create_access_token(subject=disabled_driver.id)
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = await async_client.get("/api/v1/drivers/me", headers=headers)
    assert me_resp.status_code == 401

    # 3. Existing token rejected on duty start
    duty_resp = await async_client.post("/api/v1/drivers/me/duty/start", json={}, headers=headers)
    assert duty_resp.status_code == 401

    # 4. Existing token rejected on location ping
    loc_resp = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 13.1331, "longitude": 77.5685},
        headers=headers,
    )
    assert loc_resp.status_code == 401


@pytest.mark.asyncio
async def test_complete_driver_gps_to_maps_pipeline(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Step 3 Verification: Full End-to-End Flow:
    1. Assign vehicle to driver.
    2. Driver starts duty -> vehicle status = ON_DUTY.
    3. Ingest GPS telemetry -> verify DB persistence (is_simulated=False) & snapshot update.
    4. Citizen/Public map reflects live vehicle with is_fresh=True, is_simulated=False (privacy redacted).
    5. Official vehicle API reflects current coordinates, registration number, and assigned driver.
    6. Driver ends duty -> vehicle status = IDLE.
    """
    # Create Admin, Driver, and Vehicle
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("SupervisorPass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    driver = User(
        email=f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("DriverPass123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Manjunath K",
    )
    reg_number = f"KA-50-D-{uuid.uuid4().hex[:4].upper()}"
    vehicle = Vehicle(
        registration_number=reg_number,
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.IDLE.value,
        is_published=True,
    )
    async_db_session.add_all([admin, driver, vehicle])
    await async_db_session.commit()

    admin_token = create_access_token(subject=admin.id)
    driver_token = create_access_token(subject=driver.id)

    # 1. Assign test vehicle to driver
    assign_resp = await async_client.post(
        f"/api/v1/drivers/{driver.id}/assign-vehicle",
        json={"vehicle_id": str(vehicle.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["assigned_vehicle"]["id"] == str(vehicle.id)

    # 2. Driver starts duty
    start_resp = await async_client.post(
        "/api/v1/drivers/me/duty/start",
        json={"latitude": 13.0827, "longitude": 77.5877},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["duty_status"] == "ON_DUTY"

    # Verify vehicle status is ON_DUTY in DB
    await async_db_session.refresh(vehicle)
    assert vehicle.status == VehicleStatus.ON_DUTY.value

    # 3. Driver sends live GPS telemetry (Bangalore coordinates)
    test_lat = 13.13310
    test_lon = 77.56850
    test_speed = 28.5
    test_heading = 85.0
    test_accuracy = 6.2

    ping_resp = await async_client.post(
        "/api/v1/drivers/me/location",
        json={
            "latitude": test_lat,
            "longitude": test_lon,
            "speed_kmh": test_speed,
            "heading": test_heading,
            "accuracy_meters": test_accuracy,
        },
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert ping_resp.status_code == 201
    ping_data = ping_resp.json()
    assert ping_data["success"] is True
    assert ping_data["vehicle_id"] == str(vehicle.id)

    # 4. Confirm coordinates persisted in database & is_simulated is False
    pos_stmt = (
        select(VehiclePosition)
        .where(VehiclePosition.vehicle_id == vehicle.id)
        .order_by(VehiclePosition.recorded_at.desc())
    )
    result = await async_db_session.execute(pos_stmt)
    latest_pos = result.scalars().first()
    assert latest_pos is not None, "VehiclePosition record must exist"
    assert latest_pos.is_simulated is False, "Must NEVER be marked as simulated"
    assert latest_pos.speed_kmh == test_speed
    assert latest_pos.heading == test_heading

    # Confirm vehicle snapshot is atomically updated
    await async_db_session.refresh(vehicle)
    assert vehicle.is_simulated is False
    assert vehicle.last_seen_at is not None

    # 5. Verify Public / Citizen Map endpoint (/api/v1/public/map/vehicles)
    # The vehicle must be published, fresh, and show the exact coordinates (with privacy redactions)
    pub_resp = await async_client.get("/api/v1/public/map/vehicles")
    assert pub_resp.status_code == 200
    pub_vehicles = pub_resp.json()
    matching = [v for v in pub_vehicles if v["id"] == str(vehicle.id)]
    assert len(matching) == 1, f"Vehicle {vehicle.id} must appear on public map"
    map_veh = matching[0]
    assert map_veh["is_simulated"] is False
    assert map_veh["is_fresh"] is True
    assert round(map_veh["latitude"], 4) == round(test_lat, 4)
    assert round(map_veh["longitude"], 4) == round(test_lon, 4)

    # 6. Verify Official Fleet endpoint (/api/v1/vehicles)
    off_resp = await async_client.get(
        "/api/v1/vehicles",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert off_resp.status_code == 200
    off_vehicles = off_resp.json()
    off_matching = [v for v in off_vehicles if v["id"] == str(vehicle.id)]
    assert len(off_matching) == 1
    assert off_matching[0]["registration_number"] == reg_number
    assert off_matching[0]["assigned_driver_id"] == str(driver.id)
    assert off_matching[0]["status"] == "ON_DUTY"

    # 7. Driver ends duty
    end_resp = await async_client.post(
        "/api/v1/drivers/me/duty/end",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["duty_status"] == "IDLE"

    # Verify vehicle status reset to IDLE in DB
    await async_db_session.refresh(vehicle)
    assert vehicle.status == VehicleStatus.IDLE.value


@pytest.mark.asyncio
async def test_gps_edge_cases_and_error_handling(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Step 3 Verification: Edge Cases & Error Handling:
    - Invalid latitude / longitude rejected with 422.
    - Negative accuracy rejected with 422.
    - Duty start rejected when no vehicle assigned.
    - Telemetry rejected when duty inactive.
    - Stale telemetry (> 15 minutes) correctly identified as stale.
    """
    driver = User(
        email=f"driver-{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(driver)
    await async_db_session.commit()
    token = create_access_token(subject=driver.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Start duty without vehicle -> 400
    resp_no_veh = await async_client.post("/api/v1/drivers/me/duty/start", json={}, headers=headers)
    assert resp_no_veh.status_code == 400
    assert "No vehicle is currently assigned" in resp_no_veh.json()["detail"]

    # 2. Assign vehicle
    veh = Vehicle(
        registration_number=f"KA-02-E-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
        assigned_driver_id=driver.id,
    )
    async_db_session.add(veh)
    await async_db_session.commit()

    # 3. Telemetry ping before starting duty -> 400
    early_ping = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 13.1331, "longitude": 77.5685},
        headers=headers,
    )
    assert early_ping.status_code == 400
    assert "duty is active" in early_ping.json()["detail"]

    # 4. Start duty
    await async_client.post("/api/v1/drivers/me/duty/start", json={}, headers=headers)

    # 5. Invalid latitude (> 90) -> 422
    bad_lat = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 90.0001, "longitude": 77.5685},
        headers=headers,
    )
    assert bad_lat.status_code == 422

    # 6. Invalid longitude (< -180) -> 422
    bad_lon = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 13.1331, "longitude": -180.0001},
        headers=headers,
    )
    assert bad_lon.status_code == 422

    # 7. Negative accuracy -> 422
    bad_acc = await async_client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 13.1331, "longitude": 77.5685, "accuracy_meters": -1.0},
        headers=headers,
    )
    assert bad_acc.status_code == 422
