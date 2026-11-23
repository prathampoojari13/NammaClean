"""
Unit tests for NammaClean waste-collection vehicle tracking, telemetry ingestion,
historical breadcrumb position queries, and citizen public map readiness.

Tests authorization, role boundaries, driver scoping, spatial/telemetry validation,
stale location redaction, rate limiting, and simulation segregation without mutating
live databases.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException
from geoalchemy2.elements import WKTElement

from app.models.enums import UserRole, UserStatus, VehicleStatus, VehicleType
from app.models.user import User
from app.models.vehicle import Vehicle, VehiclePosition, utc_now
from app.schemas.vehicle import VehiclePositionCreateRequest
from app.schemas.public_map import PublicVehicleResponse
from app.api.v1.vehicles import (
    get_vehicle_positions,
    ingest_vehicle_position,
)
from app.api.v1.public_map import (
    get_public_vehicle,
    get_public_vehicles,
)


# ==============================================================================
# 1. Historical Vehicle Position Queries (GET /vehicles/{vehicle_id}/positions)
# ==============================================================================

@pytest.mark.asyncio
async def test_get_vehicle_positions_driver_assigned_success():
    """Assigned driver can retrieve position history for their own vehicle."""
    driver_id = uuid.uuid4()
    driver_user = User(id=driver_id, role=UserRole.DRIVER.value, status="ACTIVE")

    vehicle_id = uuid.uuid4()
    vehicle = Vehicle(
        id=vehicle_id,
        registration_number="KA-01-DRV-1001",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.ON_DUTY.value,
        assigned_driver_id=driver_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    t1 = utc_now() - timedelta(minutes=5)
    pos1 = VehiclePosition(
        id=uuid.uuid4(),
        vehicle_id=vehicle_id,
        location=WKTElement("POINT(77.5946 12.9716)", srid=4326),
        speed_kmh=22.5,
        heading=90.0,
        recorded_at=t1,
        received_at=t1,
        is_simulated=False,
    )

    mock_db = AsyncMock()
    # First query gets vehicle; second query gets positions
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle)))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pos1])))),
        ]
    )

    results = await get_vehicle_positions(
        vehicle_id=vehicle_id,
        limit=50,
        current_user=driver_user,
        db=mock_db,
    )

    assert len(results) == 1
    assert results[0].vehicle_id == vehicle_id
    assert results[0].speed_kmh == 22.5
    assert results[0].heading == 90.0
    assert pytest.approx(results[0].latitude, rel=1e-4) == 12.9716
    assert pytest.approx(results[0].longitude, rel=1e-4) == 77.5946


@pytest.mark.asyncio
async def test_get_vehicle_positions_driver_unassigned_denied():
    """Driver cannot view position history for another driver's vehicle (HTTP 403)."""
    driver_a = User(id=uuid.uuid4(), role=UserRole.DRIVER.value, status="ACTIVE")
    driver_b_id = uuid.uuid4()

    vehicle_id = uuid.uuid4()
    vehicle = Vehicle(
        id=vehicle_id,
        registration_number="KA-01-OTH-2002",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        assigned_driver_id=driver_b_id,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle))))
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_vehicle_positions(
            vehicle_id=vehicle_id,
            current_user=driver_a,
            db=mock_db,
        )
    assert exc_info.value.status_code == 403
    assert "You are not authorized to view telemetry for this vehicle" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_vehicle_positions_citizen_role_denied():
    """Citizen role is forbidden from accessing historical telemetry (HTTP 403)."""
    citizen_user = User(id=uuid.uuid4(), role=UserRole.CITIZEN.value, status="ACTIVE")
    vehicle_id = uuid.uuid4()
    vehicle = Vehicle(id=vehicle_id, registration_number="KA-01-CIT-3003")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle))))
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_vehicle_positions(
            vehicle_id=vehicle_id,
            current_user=citizen_user,
            db=mock_db,
        )
    assert exc_info.value.status_code == 403
    assert "Insufficient permissions" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_vehicle_positions_supervisor_assigned_ward_success():
    """Ward Supervisor can view positions for vehicles assigned to their active ward."""
    supervisor_user = User(id=uuid.uuid4(), role=UserRole.WARD_SUPERVISOR.value, status="ACTIVE")
    ward_id = uuid.uuid4()
    vehicle_id = uuid.uuid4()

    vehicle = Vehicle(
        id=vehicle_id,
        registration_number="KA-01-SUP-4004",
        vehicle_type=VehicleType.MECHANICAL_SWEEPER.value,
        assigned_ward_id=ward_id,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle)))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    with patch("app.api.v1.vehicles.verify_ward_access", new=AsyncMock(return_value=None)):
        results = await get_vehicle_positions(
            vehicle_id=vehicle_id,
            current_user=supervisor_user,
            db=mock_db,
        )
    assert results == []


@pytest.mark.asyncio
async def test_get_vehicle_positions_supervisor_unassigned_ward_denied():
    """Ward Supervisor is rejected when accessing a vehicle in an unassigned ward (HTTP 403)."""
    supervisor_user = User(id=uuid.uuid4(), role=UserRole.WARD_SUPERVISOR.value, status="ACTIVE")
    ward_id = uuid.uuid4()
    vehicle_id = uuid.uuid4()

    vehicle = Vehicle(
        id=vehicle_id,
        registration_number="KA-01-UNAS-5005",
        assigned_ward_id=ward_id,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle))))
    )

    with patch(
        "app.api.v1.vehicles.verify_ward_access",
        side_effect=HTTPException(status_code=403, detail="Supervisor not assigned to ward"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_vehicle_positions(
                vehicle_id=vehicle_id,
                current_user=supervisor_user,
                db=mock_db,
            )
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_vehicle_positions_municipal_admin_success():
    """Municipal Admin has city-wide access to position history for any vehicle."""
    admin_user = User(id=uuid.uuid4(), role=UserRole.MUNICIPAL_ADMIN.value, status="ACTIVE")
    vehicle_id = uuid.uuid4()
    vehicle = Vehicle(id=vehicle_id, registration_number="KA-01-ADM-6006")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle)))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    results = await get_vehicle_positions(
        vehicle_id=vehicle_id,
        current_user=admin_user,
        db=mock_db,
    )
    assert results == []


@pytest.mark.asyncio
async def test_get_vehicle_positions_nonexistent_vehicle_returns_404():
    """Querying position history for a non-existent vehicle returns HTTP 404."""
    admin_user = User(id=uuid.uuid4(), role=UserRole.MUNICIPAL_ADMIN.value, status="ACTIVE")
    random_id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_vehicle_positions(
            vehicle_id=random_id,
            current_user=admin_user,
            db=mock_db,
        )
    assert exc_info.value.status_code == 404
    assert f"Vehicle with id '{random_id}' not found" in exc_info.value.detail


# ==============================================================================
# 2. Public Map Single Vehicle Endpoint (GET /public/map/vehicles/{vehicle_id})
# ==============================================================================

@pytest.mark.asyncio
async def test_get_public_vehicle_published_and_fresh_success():
    """Citizens can retrieve published vehicle with fresh coordinates; sensitive fields redacted."""
    vehicle_id = uuid.uuid4()
    now = utc_now()
    vehicle = Vehicle(
        id=vehicle_id,
        registration_number="KA-01-SECRET-PLATE",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.COLLECTING.value,
        assigned_driver_id=uuid.uuid4(),
        current_location=WKTElement("POINT(77.5946 12.9716)", srid=4326),
        last_seen_at=now,
        is_published=True,
        is_simulated=False,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle))))
    )

    response = await get_public_vehicle(vehicle_id=vehicle_id, db=mock_db)

    assert response.id == vehicle_id
    assert response.vehicle_type == VehicleType.COMPACTOR_TRUCK.value
    assert response.status == VehicleStatus.COLLECTING.value
    assert pytest.approx(response.latitude, rel=1e-4) == 12.9716
    assert pytest.approx(response.longitude, rel=1e-4) == 77.5946
    assert response.is_fresh is True
    assert response.is_simulated is False

    # Verify Pydantic schema strictly excludes private fields
    dumped = response.model_dump()
    assert "registration_number" not in dumped
    assert "assigned_driver_id" not in dumped
    assert "driver" not in dumped


@pytest.mark.asyncio
async def test_get_public_vehicle_stale_location_redacted():
    """Vehicle with telemetry older than freshness threshold has coordinates redacted."""
    vehicle_id = uuid.uuid4()
    stale_time = utc_now() - timedelta(minutes=30)  # > 15 min threshold
    vehicle = Vehicle(
        id=vehicle_id,
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.ON_DUTY.value,
        current_location=WKTElement("POINT(77.6000 12.9800)", srid=4326),
        last_seen_at=stale_time,
        is_published=True,
        is_simulated=False,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=vehicle))))
    )

    response = await get_public_vehicle(vehicle_id=vehicle_id, db=mock_db)
    assert response.is_fresh is False
    assert response.latitude is None
    assert response.longitude is None


@pytest.mark.asyncio
async def test_get_public_vehicle_unpublished_returns_404():
    """Unpublished vehicle returns HTTP 404 on the public citizen map."""
    vehicle_id = uuid.uuid4()

    mock_db = AsyncMock()
    # Query filters by is_published.is_(True), returning None for unpublished
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_public_vehicle(vehicle_id=vehicle_id, db=mock_db)
    assert exc_info.value.status_code == 404
    assert f"Published vehicle with id '{vehicle_id}' not found" in exc_info.value.detail


# ==============================================================================
# 3. Telemetry Ingestion Validation & Simulation Guardrails
# ==============================================================================

def test_telemetry_payload_invalid_coordinates():
    """Pydantic rejects invalid latitude and longitude ranges."""
    # Latitude > 90
    with pytest.raises(ValueError):
        VehiclePositionCreateRequest(
            latitude=95.0,
            longitude=77.59,
            recorded_at=utc_now(),
        )

    # Latitude < -90
    with pytest.raises(ValueError):
        VehiclePositionCreateRequest(
            latitude=-91.5,
            longitude=77.59,
            recorded_at=utc_now(),
        )

    # Longitude > 180
    with pytest.raises(ValueError):
        VehiclePositionCreateRequest(
            latitude=12.97,
            longitude=185.0,
            recorded_at=utc_now(),
        )

    # Longitude < -180
    with pytest.raises(ValueError):
        VehiclePositionCreateRequest(
            latitude=12.97,
            longitude=-181.0,
            recorded_at=utc_now(),
        )


def test_telemetry_payload_invalid_heading_and_speed():
    """Pydantic rejects invalid heading (> 360 or < 0) and negative speed."""
    with pytest.raises(ValueError):
        VehiclePositionCreateRequest(
            latitude=12.97,
            longitude=77.59,
            heading=400.0,
            recorded_at=utc_now(),
        )

    with pytest.raises(ValueError):
        VehiclePositionCreateRequest(
            latitude=12.97,
            longitude=77.59,
            heading=-10.0,
            recorded_at=utc_now(),
        )

    with pytest.raises(ValueError):
        VehiclePositionCreateRequest(
            latitude=12.97,
            longitude=77.59,
            speed_kmh=-5.0,
            recorded_at=utc_now(),
        )


def test_telemetry_payload_future_timestamp_rejected():
    """Future timestamp beyond 1-minute clock skew tolerance is rejected."""
    future_time = utc_now() + timedelta(minutes=5)
    with pytest.raises(ValueError, match="recorded_at timestamp cannot be in the future"):
        VehiclePositionCreateRequest(
            latitude=12.97,
            longitude=77.59,
            recorded_at=future_time,
        )


@pytest.mark.asyncio
async def test_simulated_telemetry_cannot_overwrite_genuine_vehicle_snapshot():
    """
    Simulation segregation guardrail:
    Simulated telemetry (is_simulated=True) submitted for a genuine municipal vehicle
    (is_simulated=False) is saved into history, but NEVER overwrites vehicle.current_location.
    """
    admin_user = User(id=uuid.uuid4(), role=UserRole.MUNICIPAL_ADMIN.value, status="ACTIVE")
    vehicle_id = uuid.uuid4()
    original_loc = WKTElement("POINT(77.5000 12.5000)", srid=4326)
    original_last_seen = utc_now() - timedelta(minutes=2)

    genuine_vehicle = Vehicle(
        id=vehicle_id,
        registration_number="KA-01-GENUINE",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        is_simulated=False,  # Genuine municipal vehicle
        current_location=original_loc,
        last_seen_at=original_last_seen,
    )

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=genuine_vehicle))))
    )
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    simulated_payload = VehiclePositionCreateRequest(
        latitude=12.9999,
        longitude=77.9999,
        recorded_at=utc_now(),
        is_simulated=True,  # Simulated packet
    )

    result = await ingest_vehicle_position(
        vehicle_id=vehicle_id,
        payload=simulated_payload,
        current_user=admin_user,
        db=mock_db,
    )

    assert result.is_simulated is True
    # Verify genuine vehicle snapshot was NOT overwritten
    assert genuine_vehicle.is_simulated is False
    assert genuine_vehicle.current_location == original_loc
    assert genuine_vehicle.last_seen_at == original_last_seen
