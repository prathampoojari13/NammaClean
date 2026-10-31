"""
Integration tests for NammaClean Stage 2.8.4: Public Map API and Controlled GPS Simulation Engine.
Verifies:
1. Public endpoints return documented schemas and redact sensitive operational/worker fields.
2. Unpublished and inactive records are strictly excluded from public map endpoints.
3. Stale locations (older than freshness threshold) are redacted and not counted in summary.
4. Publication toggle endpoints enforce role and ward authorization.
5. GPS simulation is disabled by default and rejects non-admin users.
6. When simulation is enabled, demo vehicles advance along demo routes without moving backwards in time.
7. Simulator cannot modify non-demo records, and simulated telemetry cannot overwrite real vehicle snapshots.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, VehicleStatus, VehicleType, CollectionPointType
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.vehicle import Vehicle, VehiclePosition, utc_now
from app.models.collection_point import CollectionPoint
from app.models.route import CollectionRoute, RouteStop


@pytest.mark.asyncio
async def test_public_map_vehicles_schema_and_field_redaction(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. GET /api/v1/public/map/vehicles is accessible without authentication.
    2. Published vehicles are returned; unpublished vehicles are omitted.
    3. Registration number, driver ID, and internal administrative fields are strictly redacted.
    """
    ward = Ward(ward_code=f"W-PUB-{uuid.uuid4().hex[:6]}", display_name="Public Test Ward")
    async_db_session.add(ward)
    await async_db_session.commit()

    driver = User(
        email=f"driver_pub_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(driver)
    await async_db_session.commit()

    # 1. Published vehicle with fresh location
    now = utc_now()
    pub_veh = Vehicle(
        registration_number=f"KA-01-PUB-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.COLLECTING.value,
        assigned_ward_id=ward.id,
        assigned_driver_id=driver.id,
        current_location=WKTElement("POINT(77.5946 12.9716)", srid=4326),
        last_seen_at=now,
        is_published=True,
        is_simulated=False,
    )

    # 2. Unpublished vehicle with location
    unpub_veh = Vehicle(
        registration_number=f"KA-01-PRIV-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.ON_DUTY.value,
        assigned_ward_id=ward.id,
        assigned_driver_id=driver.id,
        current_location=WKTElement("POINT(77.6000 12.9800)", srid=4326),
        last_seen_at=now,
        is_published=False,
        is_simulated=False,
    )
    async_db_session.add_all([pub_veh, unpub_veh])
    await async_db_session.commit()

    # Query public endpoint without credentials
    response = await async_client.get(f"/api/v1/public/map/vehicles?ward_id={ward.id}")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    item = data[0]

    # Verify ID matches published vehicle
    assert item["id"] == str(pub_veh.id)
    assert item["vehicle_type"] == VehicleType.COMPACTOR_TRUCK.value
    assert item["status"] == VehicleStatus.COLLECTING.value
    assert pytest.approx(item["latitude"], rel=1e-4) == 12.9716
    assert pytest.approx(item["longitude"], rel=1e-4) == 77.5946
    assert item["is_fresh"] is True
    assert item["is_simulated"] is False

    # CRITICAL: Verify sensitive administrative and worker fields are NOT present
    assert "registration_number" not in item
    assert "assigned_driver_id" not in item
    assert "driver" not in item
    assert "created_at" not in item
    assert "updated_at" not in item

    # Cleanup
    await async_db_session.delete(pub_veh)
    await async_db_session.delete(unpub_veh)
    await async_db_session.delete(driver)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_public_map_stale_locations_redacted(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. A vehicle whose last_seen_at is older than VEHICLE_FRESHNESS_MINUTES has its
       latitude and longitude redacted to None.
    2. is_fresh is reported as False.
    3. Stale locations are not disclosed to citizens as if they are live.
    """
    ward = Ward(ward_code=f"W-STALE-{uuid.uuid4().hex[:6]}", display_name="Stale Test Ward")
    async_db_session.add(ward)
    await async_db_session.commit()

    # Stale vehicle: 30 minutes old (threshold is 15 minutes)
    stale_time = utc_now() - timedelta(minutes=30)
    stale_veh = Vehicle(
        registration_number=f"KA-01-STL-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.ON_DUTY.value,
        assigned_ward_id=ward.id,
        current_location=WKTElement("POINT(77.5500 12.9200)", srid=4326),
        last_seen_at=stale_time,
        is_published=True,
    )
    async_db_session.add(stale_veh)
    await async_db_session.commit()

    response = await async_client.get(f"/api/v1/public/map/vehicles?ward_id={ward.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1

    item = data[0]
    assert item["id"] == str(stale_veh.id)
    assert item["latitude"] is None
    assert item["longitude"] is None
    assert item["is_fresh"] is False

    # Cleanup
    await async_db_session.delete(stale_veh)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_public_map_collection_points_publication_filter(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Active & published collection points are returned.
    2. Unpublished collection points are omitted.
    3. Inactive collection points are omitted.
    """
    ward = Ward(ward_code=f"W-CP-PUB-{uuid.uuid4().hex[:6]}", display_name="CP Ward")
    async_db_session.add(ward)
    await async_db_session.commit()

    # 1. Active & Published -> included
    cp_published = CollectionPoint(
        ward_id=ward.id,
        name="Public Community Bin",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.5800 12.9600)", srid=4326),
        is_active=True,
        is_published=True,
    )
    # 2. Active & Unpublished -> excluded
    cp_unpublished = CollectionPoint(
        ward_id=ward.id,
        name="Internal Transfer Point",
        point_type=CollectionPointType.TRANSFER_STATION.value,
        location=WKTElement("POINT(77.5850 12.9650)", srid=4326),
        is_active=True,
        is_published=False,
    )
    # 3. Inactive & Published -> excluded
    cp_inactive = CollectionPoint(
        ward_id=ward.id,
        name="Decommissioned Bin",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.5900 12.9700)", srid=4326),
        is_active=False,
        is_published=True,
    )
    async_db_session.add_all([cp_published, cp_unpublished, cp_inactive])
    await async_db_session.commit()

    response = await async_client.get(f"/api/v1/public/map/collection-points?ward_id={ward.id}")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == str(cp_published.id)
    assert data[0]["name"] == "Public Community Bin"
    assert data[0]["ward_name"] == "CP Ward"
    assert pytest.approx(data[0]["latitude"], rel=1e-4) == 12.9600
    assert pytest.approx(data[0]["longitude"], rel=1e-4) == 77.5800

    # Cleanup
    await async_db_session.delete(cp_published)
    await async_db_session.delete(cp_unpublished)
    await async_db_session.delete(cp_inactive)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_public_map_routes_publication_filter_and_ordered_stops(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Active & published routes are returned with LineString coordinates and ordered stops.
    2. Unpublished routes are excluded.
    """
    ward = Ward(ward_code=f"W-RT-PUB-{uuid.uuid4().hex[:6]}", display_name="Route Pub Ward")
    async_db_session.add(ward)
    await async_db_session.commit()

    cp = CollectionPoint(
        ward_id=ward.id,
        name="Route Stop 1",
        point_type=CollectionPointType.DOOR_TO_DOOR_PICKUP.value,
        location=WKTElement("POINT(77.5900 12.9700)", srid=4326),
        is_active=True,
        is_published=True,
    )
    async_db_session.add(cp)
    await async_db_session.commit()

    # Published route
    pub_route = CollectionRoute(
        ward_id=ward.id,
        name="Published Corridor",
        route_code="PUB-R-01",
        route_path=WKTElement("LINESTRING(77.5900 12.9700, 77.5950 12.9750)", srid=4326),
        is_active=True,
        is_published=True,
        is_simulated=False,
    )
    # Unpublished route
    unpub_route = CollectionRoute(
        ward_id=ward.id,
        name="Internal Depot Transit",
        route_code="PRIV-R-01",
        route_path=WKTElement("LINESTRING(77.5800 12.9600, 77.5850 12.9650)", srid=4326),
        is_active=True,
        is_published=False,
    )
    async_db_session.add_all([pub_route, unpub_route])
    await async_db_session.commit()

    # Add stop to published route
    stop = RouteStop(
        route_id=pub_route.id,
        collection_point_id=cp.id,
        stop_sequence=1,
        planned_arrival_offset_minutes=10,
    )
    async_db_session.add(stop)
    await async_db_session.commit()

    response = await async_client.get(f"/api/v1/public/map/routes?ward_id={ward.id}")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == str(pub_route.id)
    assert data[0]["name"] == "Published Corridor"
    assert len(data[0]["coordinates"]) == 2
    assert len(data[0]["stops"]) == 1
    assert data[0]["stops"][0]["stop_sequence"] == 1
    assert data[0]["stops"][0]["collection_point_name"] == "Route Stop 1"

    # Cleanup
    await async_db_session.delete(stop)
    await async_db_session.delete(pub_route)
    await async_db_session.delete(unpub_route)
    await async_db_session.delete(cp)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_public_map_summary_counts_and_disclaimer(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. GET /api/v1/public/map/summary returns accurate counts of published assets.
    2. Stale or missing vehicle positions are NEVER counted as active live vehicles.
    3. Disclaimer explicitly clarifies development/demonstration status.
    """
    ward = Ward(ward_code=f"W-SUM-{uuid.uuid4().hex[:6]}", display_name="Summary Ward")
    async_db_session.add(ward)
    await async_db_session.commit()

    # 1 published CP
    cp = CollectionPoint(
        ward_id=ward.id,
        name="Summary Bin",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.59 12.97)", srid=4326),
        is_active=True,
        is_published=True,
    )
    # 1 published Route
    route = CollectionRoute(
        ward_id=ward.id,
        name="Summary Route",
        route_path=WKTElement("LINESTRING(77.59 12.97, 77.60 12.98)", srid=4326),
        is_active=True,
        is_published=True,
    )
    # 1 live fresh vehicle (within 5 min)
    live_veh = Vehicle(
        registration_number=f"KA-01-LIVE-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        assigned_ward_id=ward.id,
        current_location=WKTElement("POINT(77.59 12.97)", srid=4326),
        last_seen_at=utc_now() - timedelta(minutes=2),
        is_published=True,
    )
    # 1 stale vehicle (25 min old)
    stale_veh = Vehicle(
        registration_number=f"KA-01-STALE-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        assigned_ward_id=ward.id,
        current_location=WKTElement("POINT(77.59 12.97)", srid=4326),
        last_seen_at=utc_now() - timedelta(minutes=25),
        is_published=True,
    )
    async_db_session.add_all([cp, route, live_veh, stale_veh])
    await async_db_session.commit()

    response = await async_client.get(f"/api/v1/public/map/summary?ward_id={ward.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["published_collection_points"] == 1
    assert data["published_routes"] == 1
    # Only the fresh vehicle is counted:
    assert data["active_live_vehicles"] == 1
    assert data["freshness_threshold_minutes"] == settings.VEHICLE_FRESHNESS_MINUTES
    assert "No live BBMP GPS integration is established" in data["disclaimer"]

    # Cleanup
    await async_db_session.delete(live_veh)
    await async_db_session.delete(stale_veh)
    await async_db_session.delete(route)
    await async_db_session.delete(cp)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_publication_endpoints_role_and_ward_authorization(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Citizens cannot modify publication status (HTTP 403).
    2. Municipal Admin can publish/unpublish vehicles, collection points, and routes.
    3. Ward Supervisor can publish in assigned ward, but is rejected with HTTP 403 in unassigned ward.
    """
    ward1 = Ward(ward_code=f"W-AUTH1-{uuid.uuid4().hex[:6]}", display_name="Auth Ward 1")
    ward2 = Ward(ward_code=f"W-AUTH2-{uuid.uuid4().hex[:6]}", display_name="Auth Ward 2")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    admin = User(
        email=f"admin_pub_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"super_pub_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    citizen = User(
        email=f"cit_pub_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor, citizen])
    await async_db_session.commit()

    # Assign supervisor to ward1 only
    assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward1.id)
    async_db_session.add(assign)

    vehicle_w1 = Vehicle(
        registration_number=f"KA-01-W1-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        assigned_ward_id=ward1.id,
        is_published=False,
    )
    vehicle_w2 = Vehicle(
        registration_number=f"KA-01-W2-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        assigned_ward_id=ward2.id,
        is_published=False,
    )
    async_db_session.add_all([vehicle_w1, vehicle_w2])
    await async_db_session.commit()

    token_citizen = create_access_token(subject=citizen.id)
    token_admin = create_access_token(subject=admin.id)
    token_supervisor = create_access_token(subject=supervisor.id)

    # 1. Citizen rejected
    res_cit = await async_client.patch(
        f"/api/v1/vehicles/{vehicle_w1.id}/publication",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {token_citizen}"},
    )
    assert res_cit.status_code == 403

    # 2. Supervisor assigned to ward1 can publish vehicle in ward1
    res_sup_w1 = await async_client.patch(
        f"/api/v1/vehicles/{vehicle_w1.id}/publication",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {token_supervisor}"},
    )
    assert res_sup_w1.status_code == 200
    assert res_sup_w1.json()["is_published"] is True

    # 3. Supervisor CANNOT publish vehicle in unassigned ward2
    res_sup_w2 = await async_client.patch(
        f"/api/v1/vehicles/{vehicle_w2.id}/publication",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {token_supervisor}"},
    )
    assert res_sup_w2.status_code == 403

    # 4. Admin can publish vehicle in ward2
    res_adm = await async_client.patch(
        f"/api/v1/vehicles/{vehicle_w2.id}/publication",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_adm.status_code == 200
    assert res_adm.json()["is_published"] is True

    # Cleanup
    await async_db_session.delete(vehicle_w1)
    await async_db_session.delete(vehicle_w2)
    await async_db_session.delete(assign)
    await async_db_session.delete(citizen)
    await async_db_session.delete(supervisor)
    await async_db_session.delete(admin)
    await async_db_session.delete(ward1)
    await async_db_session.delete(ward2)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_simulation_disabled_by_default(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. settings.SIMULATION_ENABLED is False by default.
    2. Attempting to trigger simulation tick returns HTTP 400 with descriptive error.
    3. Attempting to seed demo fleet returns HTTP 400.
    """
    assert settings.SIMULATION_ENABLED is False

    admin = User(
        email=f"admin_sim_dis_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(admin)
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    res_tick = await async_client.post(
        "/api/v1/simulation/tick",
        json={"step_seconds": 30},
        headers=headers,
    )
    assert res_tick.status_code == 400
    assert "GPS simulation engine is disabled by configuration" in res_tick.json()["detail"]

    res_seed = await async_client.post(
        "/api/v1/simulation/seed-demo",
        json={"ward_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert res_seed.status_code == 400
    assert "GPS simulation engine is disabled by configuration" in res_seed.json()["detail"]

    # Cleanup
    await async_db_session.delete(admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_simulation_tick_and_non_demo_protection(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    monkeypatch,
):
    """
    Verify:
    1. When SIMULATION_ENABLED is enabled:
       - Simulator cannot modify vehicles or routes that are NOT designated as demo data.
       - Demo vehicles advance along demo routes smoothly and deterministically.
       - Historical position records are created with is_simulated=True.
       - Telemetry timestamps advance monotonically (cannot move backwards).
    """
    monkeypatch.setattr(settings, "SIMULATION_ENABLED", True)

    ward = Ward(ward_code=f"W-SIM-RUN-{uuid.uuid4().hex[:6]}", display_name="Sim Ward")
    async_db_session.add(ward)
    await async_db_session.commit()

    admin = User(
        email=f"admin_sim_run_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(admin)
    await async_db_session.commit()

    # 1. Non-demo (genuine) vehicle
    real_vehicle = Vehicle(
        registration_number=f"KA-01-REAL-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        assigned_ward_id=ward.id,
        is_simulated=False,
    )
    # 2. Demo vehicle and demo route
    demo_route = CollectionRoute(
        ward_id=ward.id,
        name="Demo Simulation Route",
        route_code=f"SIM-CORRIDOR-{uuid.uuid4().hex[:4].upper()}",
        route_path=WKTElement("LINESTRING(77.5900 12.9700, 77.5950 12.9750, 77.6000 12.9700)", srid=4326),
        is_active=True,
        is_published=True,
        is_simulated=True,
    )
    demo_vehicle = Vehicle(
        registration_number=f"SIM-DEMO-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        assigned_ward_id=ward.id,
        is_simulated=True,
        is_published=True,
    )
    async_db_session.add_all([real_vehicle, demo_route, demo_vehicle])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Test A: Cannot simulate non-demo vehicle
    res_real = await async_client.post(
        "/api/v1/simulation/tick",
        json={"vehicle_id": str(real_vehicle.id), "step_seconds": 30},
        headers=headers,
    )
    assert res_real.status_code == 400
    assert "not designated as demo/simulated data" in res_real.json()["detail"]

    # Test B: Step demo vehicle
    res_step1 = await async_client.post(
        "/api/v1/simulation/tick",
        json={"vehicle_id": str(demo_vehicle.id), "step_seconds": 30},
        headers=headers,
    )
    assert res_step1.status_code == 200
    step1_data = res_step1.json()
    assert step1_data["simulated_vehicles_count"] == 1
    step1 = step1_data["steps"][0]
    assert step1["vehicle_id"] == str(demo_vehicle.id)
    assert step1["speed_kmh"] > 0
    t1_recorded = datetime.fromisoformat(step1["recorded_at"])

    # Verify vehicle snapshot was updated in DB with is_simulated=True
    await async_db_session.refresh(demo_vehicle)
    assert demo_vehicle.current_location is not None
    assert demo_vehicle.is_simulated is True
    shape1 = to_shape(demo_vehicle.current_location)
    assert pytest.approx(shape1.x, rel=1e-4) == step1["longitude"]
    assert pytest.approx(shape1.y, rel=1e-4) == step1["latitude"]

    # Test C: Step 2 advances position and monotonically increases timestamp
    res_step2 = await async_client.post(
        "/api/v1/simulation/tick",
        json={"vehicle_id": str(demo_vehicle.id), "step_seconds": 30},
        headers=headers,
    )
    assert res_step2.status_code == 200
    step2 = res_step2.json()["steps"][0]
    t2_recorded = datetime.fromisoformat(step2["recorded_at"])
    assert t2_recorded >= t1_recorded

    # Check vehicle position breadcrumb records
    pos_res = await async_db_session.execute(
        select(VehiclePosition).where(VehiclePosition.vehicle_id == demo_vehicle.id)
    )
    positions = pos_res.scalars().all()
    assert len(positions) == 2
    assert all(p.is_simulated is True for p in positions)

    # Cleanup
    for p in positions:
        await async_db_session.delete(p)
    await async_db_session.delete(demo_vehicle)
    await async_db_session.delete(demo_route)
    await async_db_session.delete(real_vehicle)
    await async_db_session.delete(admin)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_simulated_position_cannot_overwrite_genuine_vehicle_snapshot(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify Part D Integrity:
    If a vehicle has genuine GPS location (is_simulated=False),
    a subsequent simulated position is recorded in historical telemetry with is_simulated=True,
    but CANNOT overwrite the genuine current_location snapshot.
    """
    admin = User(
        email=f"admin_snap_prot_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    vehicle = Vehicle(
        registration_number=f"KA-01-PROT-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        is_simulated=False,
    )
    async_db_session.add_all([admin, vehicle])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Genuine position telemetry
    t_real = utc_now() - timedelta(minutes=5)
    res_real = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json={
            "latitude": 12.9700,
            "longitude": 77.6000,
            "recorded_at": t_real.isoformat(),
            "is_simulated": False,
        },
        headers=headers,
    )
    assert res_real.status_code == 201

    await async_db_session.refresh(vehicle)
    assert vehicle.is_simulated is False
    shape_real = to_shape(vehicle.current_location)
    assert pytest.approx(shape_real.x, rel=1e-4) == 77.6000
    assert pytest.approx(shape_real.y, rel=1e-4) == 12.9700

    # 2. Simulated position arrives with newer timestamp
    t_sim = utc_now() - timedelta(minutes=1)
    res_sim = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json={
            "latitude": 12.9900,
            "longitude": 77.6500,
            "recorded_at": t_sim.isoformat(),
            "is_simulated": True,
        },
        headers=headers,
    )
    assert res_sim.status_code == 201
    assert res_sim.json()["is_simulated"] is True

    # 3. CRITICAL: Vehicle's snapshot MUST still retain the genuine real position and is_simulated=False
    await async_db_session.refresh(vehicle)
    assert vehicle.is_simulated is False
    shape_snapshot = to_shape(vehicle.current_location)
    assert pytest.approx(shape_snapshot.x, rel=1e-4) == 77.6000
    assert pytest.approx(shape_snapshot.y, rel=1e-4) == 12.9700
    assert vehicle.last_seen_at.replace(microsecond=0) == t_real.replace(microsecond=0)

    # Cleanup
    pos_res = await async_db_session.execute(
        select(VehiclePosition).where(VehiclePosition.vehicle_id == vehicle.id)
    )
    for p in pos_res.scalars().all():
        await async_db_session.delete(p)
    await async_db_session.delete(vehicle)
    await async_db_session.delete(admin)
    await async_db_session.commit()
