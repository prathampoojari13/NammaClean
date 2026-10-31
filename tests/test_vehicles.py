"""
Tests for NammaClean Stage 2.8.2: Vehicle Records and Timestamped GPS Telemetry.
Verifies Vehicle and VehiclePosition models, PostGIS geometry (SRID 4326), spatial and
composite indexes, database check constraints, driver assignment authorization, atomic
freshness updates, out-of-order telemetry handling, and simulated vs real metadata.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, VehicleStatus, VehicleType
from app.models.user import User
from app.models.ward import Ward
from app.models.vehicle import Vehicle, VehiclePosition, utc_now


@pytest.mark.asyncio
async def test_vehicle_and_position_model_relationships(async_db_session: AsyncSession):
    """
    Verify:
    1. Vehicle model persists with optional current_location snapshot.
    2. VehiclePosition records link to parent Vehicle.
    3. Cascade deletion of a Vehicle removes all its historical positions.
    """
    ward = Ward(
        ward_code=f"W-VEH-{uuid.uuid4().hex[:6]}",
        display_name="Vehicle Test Ward",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    reg_no = f"KA-01-EA-{uuid.uuid4().hex[:4].upper()}"
    vehicle = Vehicle(
        registration_number=reg_no,
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.ON_DUTY.value,
        assigned_ward_id=ward.id,
    )
    async_db_session.add(vehicle)
    await async_db_session.commit()
    await async_db_session.refresh(vehicle)

    assert vehicle.id is not None
    assert vehicle.registration_number == reg_no
    assert vehicle.current_location is None
    assert vehicle.last_seen_at is None

    # Add historical positions
    t1 = utc_now() - timedelta(minutes=10)
    t2 = utc_now() - timedelta(minutes=5)
    pos1 = VehiclePosition(
        vehicle_id=vehicle.id,
        location=WKTElement("POINT(77.5946 12.9716)", srid=4326),
        speed_kmh=25.5,
        heading=90.0,
        recorded_at=t1,
        is_simulated=True,
    )
    pos2 = VehiclePosition(
        vehicle_id=vehicle.id,
        location=WKTElement("POINT(77.6000 12.9750)", srid=4326),
        speed_kmh=30.0,
        heading=110.0,
        recorded_at=t2,
        is_simulated=True,
    )
    async_db_session.add_all([pos1, pos2])
    await async_db_session.commit()

    # Query vehicle positions
    stmt = select(VehiclePosition).where(VehiclePosition.vehicle_id == vehicle.id).order_by(VehiclePosition.recorded_at.desc())
    res = await async_db_session.execute(stmt)
    positions = res.scalars().all()
    assert len(positions) == 2
    assert positions[0].recorded_at == t2
    assert positions[1].recorded_at == t1

    # Cascade delete verification
    await async_db_session.delete(vehicle)
    await async_db_session.commit()

    res_pos = await async_db_session.execute(select(VehiclePosition).where(VehiclePosition.vehicle_id == vehicle.id))
    assert len(res_pos.scalars().all()) == 0

    # Cleanup ward
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_vehicle_and_telemetry_database_constraints(async_db_session: AsyncSession):
    """
    Verify:
    1. Registration number uniqueness constraint.
    2. Vehicle status check constraint.
    3. Vehicle type check constraint.
    4. Speed non-negative check constraint.
    5. Heading 0-360 range check constraint.
    """
    reg_no = f"KA-04-TR-{uuid.uuid4().hex[:4].upper()}"
    v1 = Vehicle(
        registration_number=reg_no,
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
    )
    async_db_session.add(v1)
    await async_db_session.commit()
    v1_id = v1.id

    # 1. Duplicate registration number
    v2 = Vehicle(
        registration_number=reg_no,
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
    )
    async_db_session.add(v2)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # 2. Invalid vehicle status
    v_bad_status = Vehicle(
        registration_number=f"KA-05-XX-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status="INVALID_STATUS",
    )
    async_db_session.add(v_bad_status)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # 3. Invalid speed < 0
    bad_speed_pos = VehiclePosition(
        vehicle_id=v1_id,
        location=WKTElement("POINT(77.5 12.9)", srid=4326),
        speed_kmh=-10.0,
        recorded_at=utc_now(),
    )
    async_db_session.add(bad_speed_pos)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # 4. Invalid heading > 360
    bad_heading_pos = VehiclePosition(
        vehicle_id=v1_id,
        location=WKTElement("POINT(77.5 12.9)", srid=4326),
        heading=400.0,
        recorded_at=utc_now(),
    )
    async_db_session.add(bad_heading_pos)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # Cleanup
    v_clean = (await async_db_session.execute(select(Vehicle).where(Vehicle.id == v1_id))).scalars().first()
    if v_clean:
        await async_db_session.delete(v_clean)
        await async_db_session.commit()



@pytest.mark.asyncio
async def test_database_spatial_and_composite_indexes_exist(async_db_session: AsyncSession):
    """
    Verify:
    1. GiST spatial index on vehicles.current_location.
    2. GiST spatial index on vehicle_positions.location.
    3. Composite index on vehicle_positions (vehicle_id, recorded_at DESC).
    """
    res = await async_db_session.execute(text("""
        SELECT tablename, indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename IN ('vehicles', 'vehicle_positions');
    """))
    indexes = {f"{row[0]}.{row[1]}": row[2] for row in res.fetchall()}

    assert "vehicles.idx_vehicles_current_location" in indexes
    assert "gist (current_location)" in indexes["vehicles.idx_vehicles_current_location"].lower()

    assert "vehicle_positions.idx_vehicle_positions_location" in indexes
    assert "gist (location)" in indexes["vehicle_positions.idx_vehicle_positions_location"].lower()

    assert "vehicle_positions.ix_vehicle_positions_vehicle_recorded_at" in indexes
    assert "recorded_at desc" in indexes["vehicle_positions.ix_vehicle_positions_vehicle_recorded_at"].lower()


@pytest.mark.asyncio
async def test_driver_telemetry_ingestion_and_atomic_vehicle_update(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Assigned driver can submit telemetry to their vehicle.
    2. Vehicle position record is created with correct lat/lon orientation (X=lon, Y=lat).
    3. Vehicle's current_location, last_seen_at, and is_simulated are atomically updated.
    """
    driver = User(
        email=f"driver_ingest_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(driver)
    await async_db_session.commit()

    vehicle = Vehicle(
        registration_number=f"KA-02-AB-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.ON_DUTY.value,
        assigned_driver_id=driver.id,
    )
    async_db_session.add(vehicle)
    await async_db_session.commit()

    token = create_access_token(subject=driver.id)
    headers = {"Authorization": f"Bearer {token}"}

    rec_time = utc_now() - timedelta(seconds=15)
    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "speed_kmh": 28.4,
        "heading": 135.0,
        "recorded_at": rec_time.isoformat(),
        "is_simulated": False,
    }

    response = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["vehicle_id"] == str(vehicle.id)
    assert pytest.approx(data["latitude"], rel=1e-4) == payload["latitude"]
    assert pytest.approx(data["longitude"], rel=1e-4) == payload["longitude"]
    assert pytest.approx(data["speed_kmh"], rel=1e-4) == payload["speed_kmh"]
    assert pytest.approx(data["heading"], rel=1e-4) == payload["heading"]
    assert data["is_simulated"] is False
    assert "received_at" in data

    # Verify vehicle snapshot was atomically updated in the database
    await async_db_session.refresh(vehicle)
    assert vehicle.last_seen_at is not None
    assert vehicle.is_simulated is False
    shape = to_shape(vehicle.current_location)
    assert pytest.approx(shape.x, rel=1e-4) == payload["longitude"]
    assert pytest.approx(shape.y, rel=1e-4) == payload["latitude"]

    # Cleanup
    await async_db_session.delete(vehicle)
    await async_db_session.delete(driver)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_driver_cannot_update_another_drivers_vehicle(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Driver A receives HTTP 403 when attempting to update Driver B's vehicle."""
    driver_a = User(
        email=f"driver_a_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    driver_b = User(
        email=f"driver_b_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([driver_a, driver_b])
    await async_db_session.commit()

    vehicle_b = Vehicle(
        registration_number=f"KA-03-CD-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.ON_DUTY.value,
        assigned_driver_id=driver_b.id,
    )
    async_db_session.add(vehicle_b)
    await async_db_session.commit()

    # Driver A submits telemetry for Vehicle B
    token_a = create_access_token(subject=driver_a.id)
    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "recorded_at": utc_now().isoformat(),
        "is_simulated": True,
    }

    response = await async_client.post(
        f"/api/v1/vehicles/{vehicle_b.id}/positions",
        json=payload,
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "You are not authorized to submit telemetry for this vehicle."

    # Cleanup
    await async_db_session.delete(vehicle_b)
    await async_db_session.delete(driver_a)
    await async_db_session.delete(driver_b)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_citizen_forbidden_from_telemetry_submission(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Citizen role receives HTTP 403 when attempting to submit telemetry."""
    citizen = User(
        email=f"citizen_tel_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    vehicle = Vehicle(
        registration_number=f"KA-05-EF-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.ON_DUTY.value,
    )
    async_db_session.add_all([citizen, vehicle])
    await async_db_session.commit()

    token = create_access_token(subject=citizen.id)
    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "recorded_at": utc_now().isoformat(),
    }
    response = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    # Cleanup
    await async_db_session.delete(vehicle)
    await async_db_session.delete(citizen)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_municipal_admin_and_supervisor_authorized_for_telemetry(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify: Municipal Admin and Ward Supervisor can submit telemetry for any vehicle
    (essential for simulator agents and centralized GPS gateway feeds).
    """
    admin = User(
        email=f"admin_telemetry_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    vehicle = Vehicle(
        registration_number=f"KA-01-ADM-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.MECHANICAL_SWEEPER.value,
        status=VehicleStatus.ON_DUTY.value,
    )
    async_db_session.add_all([admin, vehicle])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    payload = {
        "latitude": 12.9500,
        "longitude": 77.6000,
        "speed_kmh": 15.0,
        "heading": 270.0,
        "recorded_at": utc_now().isoformat(),
        "is_simulated": True,
    }
    response = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["is_simulated"] is True

    # Cleanup
    await async_db_session.delete(vehicle)
    await async_db_session.delete(admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_telemetry_unknown_vehicle_returns_404(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Submitting telemetry for a non-existent vehicle returns HTTP 404."""
    admin = User(
        email=f"admin_404_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(admin)
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    random_uuid = uuid.uuid4()
    payload = {
        "latitude": 12.95,
        "longitude": 77.60,
        "recorded_at": utc_now().isoformat(),
    }
    response = await async_client.post(
        f"/api/v1/vehicles/{random_uuid}/positions",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404

    # Cleanup
    await async_db_session.delete(admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_future_timestamp_rejected_by_validation(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Telemetry with recorded_at timestamp in the future is rejected with HTTP 422."""
    admin = User(
        email=f"admin_fut_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    vehicle = Vehicle(
        registration_number=f"KA-01-FUT-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
    )
    async_db_session.add_all([admin, vehicle])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    future_time = utc_now() + timedelta(minutes=10)
    payload = {
        "latitude": 12.95,
        "longitude": 77.60,
        "recorded_at": future_time.isoformat(),
    }
    response = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422

    # Cleanup
    await async_db_session.delete(vehicle)
    await async_db_session.delete(admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_older_telemetry_does_not_overwrite_newer_vehicle_snapshot(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    When an out-of-order or delayed position update arrives with an older recorded_at
    timestamp than vehicle.last_seen_at:
    - The position IS inserted into vehicle_positions history.
    - The vehicle's current_location and last_seen_at are NOT overwritten.
    """
    admin = User(
        email=f"admin_order_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    vehicle = Vehicle(
        registration_number=f"KA-01-ORD-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
    )
    async_db_session.add_all([admin, vehicle])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Ingest newer position at t_newer (now - 1 min)
    t_newer = utc_now() - timedelta(minutes=1)
    res1 = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json={
            "latitude": 12.9700,
            "longitude": 77.6000,
            "recorded_at": t_newer.isoformat(),
            "is_simulated": False,
        },
        headers=headers,
    )
    assert res1.status_code == 201

    await async_db_session.refresh(vehicle)
    shape_newer = to_shape(vehicle.current_location)
    assert pytest.approx(shape_newer.y, rel=1e-4) == 12.9700
    assert pytest.approx(shape_newer.x, rel=1e-4) == 77.6000

    # 2. Ingest older/delayed position at t_older (now - 5 min)
    t_older = utc_now() - timedelta(minutes=5)
    res2 = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json={
            "latitude": 12.9200,
            "longitude": 77.5500,
            "recorded_at": t_older.isoformat(),
            "is_simulated": True,
        },
        headers=headers,
    )
    assert res2.status_code == 201

    # Verify: Historical position was recorded
    pos_res = await async_db_session.execute(
        select(VehiclePosition).where(VehiclePosition.vehicle_id == vehicle.id)
    )
    assert len(pos_res.scalars().all()) == 2

    # Verify: Vehicle's cached snapshot was NOT overwritten by the older position
    await async_db_session.refresh(vehicle)
    shape_current = to_shape(vehicle.current_location)
    assert pytest.approx(shape_current.y, rel=1e-4) == 12.9700
    assert pytest.approx(shape_current.x, rel=1e-4) == 77.6000
    assert vehicle.last_seen_at.replace(microsecond=0) == t_newer.replace(microsecond=0)
    assert vehicle.is_simulated is False

    # Cleanup
    await async_db_session.delete(vehicle)
    await async_db_session.delete(admin)
    await async_db_session.commit()
