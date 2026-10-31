"""
Tests for Stage 2.9.2: Collection Asset Lifecycle & Complete Demo Seeding.

Covers:
1. Collection-point update by a municipal administrator.
2. Collection-point update by an authorized ward supervisor.
3. Cross-ward collection-point update denial (HTTP 403).
4. Unauthorized publication-field changes rejected in generic PATCH (HTTP 422).
5. Collection-point deactivation (setting is_active=False).
6. Route update and deactivation authorization (admin city-wide, supervisor scoped).
7. Route-stop creation with valid collection points.
8. Rejection of collection points from another ward (HTTP 400).
9. Safe stop removal (HTTP 204) and update.
10. Atomic stop reordering without violating unique sequence constraints.
11. Demo fleet seeding creates vehicle, route, 4 collection points, and 4 ordered stops.
12. Repeated demo seeding is strictly idempotent (no duplicate assets created).
"""

import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, CollectionPointType, VehicleType, VehicleStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.collection_point import CollectionPoint
from app.models.route import CollectionRoute, RouteStop
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
async def test_collection_point_update_and_deactivation(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify collection point update and deactivation lifecycle:
    - Municipal Admin can update collection point name, type, and coordinates.
    - Ward Supervisor can update collection points in actively assigned ward.
    - Supervisor cannot update collection points in unassigned ward (HTTP 403).
    - Supervisor cannot reassign collection point to unassigned ward (HTTP 403).
    - Protected publication status cannot be updated through generic patch (HTTP 422).
    - Empty updates are rejected (HTTP 400).
    - Deactivation sets is_active=False.
    """
    ward1 = Ward(ward_code=f"W-CPU1-{uuid.uuid4().hex[:6]}", display_name="CP Ward 1")
    ward2 = Ward(ward_code=f"W-CPU2-{uuid.uuid4().hex[:6]}", display_name="CP Ward 2")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    admin = User(
        email=f"admin_cp_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"sup_cp_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor])
    await async_db_session.commit()

    # Assign supervisor to ward1 only
    assignment = UserWardAssignment(
        user_id=supervisor.id,
        ward_id=ward1.id,
        assigned_at=datetime.now(timezone.utc),
        revoked_at=None,
    )
    async_db_session.add(assignment)

    # Collection point in ward 1
    cp1 = CollectionPoint(
        ward_id=ward1.id,
        name="CP Original Name",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.5900 12.9700)", srid=4326),
        is_active=True,
        is_published=False,
    )
    # Collection point in ward 2
    cp2 = CollectionPoint(
        ward_id=ward2.id,
        name="CP Ward 2 Name",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.6000 12.9800)", srid=4326),
        is_active=True,
        is_published=False,
    )
    async_db_session.add_all([cp1, cp2])
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))
    sup_token = create_access_token(str(supervisor.id))

    # 1. Admin updates collection point name, type, and coordinates
    res_admin_up = await async_client.patch(
        f"/api/v1/wards/{ward1.id}/collection-points/{cp1.id}",
        json={
            "name": "CP Updated by Admin",
            "point_type": CollectionPointType.COMMERCIAL_POINT.value,
            "latitude": 12.9710,
            "longitude": 77.5910,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin_up.status_code == 200
    data_adm = res_admin_up.json()
    assert data_adm["name"] == "CP Updated by Admin"
    assert data_adm["point_type"] == CollectionPointType.COMMERCIAL_POINT.value
    assert data_adm["latitude"] == 12.9710
    assert data_adm["longitude"] == 77.5910

    # 2. Supervisor updates collection point in assigned ward
    res_sup_up = await async_client.patch(
        f"/api/v1/wards/{ward1.id}/collection-points/{cp1.id}",
        json={
            "name": "CP Updated by Supervisor",
            "point_type": CollectionPointType.DOOR_TO_DOOR_PICKUP.value,
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_up.status_code == 200
    assert res_sup_up.json()["name"] == "CP Updated by Supervisor"

    # 3. Supervisor denied cross-ward update on collection point in ward2 (HTTP 403)
    res_sup_cross = await async_client.patch(
        f"/api/v1/wards/{ward2.id}/collection-points/{cp2.id}",
        json={"name": "Illegal Cross Update"},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_cross.status_code == 403

    # 4. Supervisor denied reassigning collection point to unassigned ward2 (HTTP 403)
    res_sup_reassign = await async_client.patch(
        f"/api/v1/wards/{ward1.id}/collection-points/{cp1.id}",
        json={"ward_id": str(ward2.id)},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_reassign.status_code == 403

    # 5. Generic update cannot alter is_published (HTTP 422)
    res_prot = await async_client.patch(
        f"/api/v1/wards/{ward1.id}/collection-points/{cp1.id}",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_prot.status_code == 422

    # 6. Empty update rejected (HTTP 400)
    res_empty = await async_client.patch(
        f"/api/v1/wards/{ward1.id}/collection-points/{cp1.id}",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_empty.status_code == 400

    # 7. Deactivation sets is_active=False
    res_deact = await async_client.delete(
        f"/api/v1/wards/{ward1.id}/collection-points/{cp1.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_deact.status_code == 200
    assert res_deact.json()["is_active"] is False


@pytest.mark.asyncio
async def test_route_and_stop_lifecycle(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify collection route and stop management:
    - Route update and deactivation (Admin city-wide, Supervisor scoped).
    - Stop addition with collection point ward consistency.
    - Rejection of collection point belonging to another ward (HTTP 400).
    - Rejection of duplicate sequence numbers (HTTP 409).
    - Reordering stops atomically without constraint violations.
    - Safe stop removal (HTTP 204).
    """
    ward1 = Ward(ward_code=f"W-RT1-{uuid.uuid4().hex[:6]}", display_name="Route Ward 1")
    ward2 = Ward(ward_code=f"W-RT2-{uuid.uuid4().hex[:6]}", display_name="Route Ward 2")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    admin = User(
        email=f"admin_rt_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"sup_rt_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor])
    await async_db_session.commit()

    # Assign supervisor to ward1 only
    assignment = UserWardAssignment(
        user_id=supervisor.id,
        ward_id=ward1.id,
        assigned_at=datetime.now(timezone.utc),
        revoked_at=None,
    )
    async_db_session.add(assignment)

    # Collection points in ward1
    cp1 = CollectionPoint(
        ward_id=ward1.id,
        name="CP Alpha",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.5900 12.9700)", srid=4326),
        is_active=True,
    )
    cp2 = CollectionPoint(
        ward_id=ward1.id,
        name="CP Beta",
        point_type=CollectionPointType.DOOR_TO_DOOR_PICKUP.value,
        location=WKTElement("POINT(77.5950 12.9750)", srid=4326),
        is_active=True,
    )
    # Collection point in ward2
    cp_w2 = CollectionPoint(
        ward_id=ward2.id,
        name="CP Other Ward",
        point_type=CollectionPointType.COMMERCIAL_POINT.value,
        location=WKTElement("POINT(77.6000 12.9800)", srid=4326),
        is_active=True,
    )
    async_db_session.add_all([cp1, cp2, cp_w2])
    await async_db_session.commit()

    # Route in ward1
    route1 = CollectionRoute(
        ward_id=ward1.id,
        name="Route Alpha",
        route_code="RT-ALPHA",
        route_path=WKTElement("LINESTRING(77.5900 12.9700, 77.5950 12.9750)", srid=4326),
        is_active=True,
    )
    # Route in ward2
    route2 = CollectionRoute(
        ward_id=ward2.id,
        name="Route Beta",
        route_code="RT-BETA",
        route_path=WKTElement("LINESTRING(77.6000 12.9800, 77.6050 12.9850)", srid=4326),
        is_active=True,
    )
    async_db_session.add_all([route1, route2])
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))
    sup_token = create_access_token(str(supervisor.id))

    # 1. Route update by Admin
    res_rt_adm = await async_client.patch(
        f"/api/v1/routes/{route1.id}",
        json={
            "name": "Route Alpha Renamed",
            "coordinates": [[77.5900, 12.9700], [77.5920, 12.9720], [77.5950, 12.9750]],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_rt_adm.status_code == 200
    assert res_rt_adm.json()["name"] == "Route Alpha Renamed"
    assert len(res_rt_adm.json()["coordinates"]) == 3

    # 2. Supervisor cannot update route in unassigned ward2 (HTTP 403)
    res_rt_sup_cross = await async_client.patch(
        f"/api/v1/routes/{route2.id}",
        json={"name": "Illegal Route Update"},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_rt_sup_cross.status_code == 403

    # 3. Generic route update cannot modify is_published or is_simulated (HTTP 422)
    res_rt_prot = await async_client.patch(
        f"/api/v1/routes/{route1.id}",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_rt_prot.status_code == 422

    # 4. Deactivate route
    res_deact_rt = await async_client.delete(
        f"/api/v1/routes/{route1.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_deact_rt.status_code == 200
    assert res_deact_rt.json()["is_active"] is False

    # 5. Add Stop 1 with CP1 (valid, ward1)
    res_stop1 = await async_client.post(
        f"/api/v1/routes/{route1.id}/stops",
        json={
            "collection_point_id": str(cp1.id),
            "stop_sequence": 1,
            "planned_arrival_offset_minutes": 0,
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_stop1.status_code == 201
    stop1_data = res_stop1.json()
    stop1_id = stop1_data["id"]

    # 6. Add Stop 2 with CP2 (valid, ward1)
    res_stop2 = await async_client.post(
        f"/api/v1/routes/{route1.id}/stops",
        json={
            "collection_point_id": str(cp2.id),
            "stop_sequence": 2,
            "planned_arrival_offset_minutes": 15,
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_stop2.status_code == 201
    stop2_id = res_stop2.json()["id"]

    # 7. Add Stop with collection point from different ward (Ward 2 CP into Ward 1 Route) -> HTTP 400
    res_mismatched_cp = await async_client.post(
        f"/api/v1/routes/{route1.id}/stops",
        json={
            "collection_point_id": str(cp_w2.id),
            "stop_sequence": 3,
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_mismatched_cp.status_code == 400
    assert "belongs to ward" in res_mismatched_cp.json()["detail"]

    # 8. Duplicate stop sequence on creation -> HTTP 409
    res_dup_seq = await async_client.post(
        f"/api/v1/routes/{route1.id}/stops",
        json={
            "collection_point_id": str(cp2.id),
            "stop_sequence": 1,
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_dup_seq.status_code == 409

    # 9. Update stop sequence collision -> HTTP 409
    res_up_seq_coll = await async_client.patch(
        f"/api/v1/routes/{route1.id}/stops/{stop2_id}",
        json={"stop_sequence": 1},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_up_seq_coll.status_code == 409

    # 10. Reorder stops atomically: swap stop 1 (seq 1 -> 2) and stop 2 (seq 2 -> 1)
    res_reorder = await async_client.post(
        f"/api/v1/routes/{route1.id}/stops/reorder",
        json={
            "stops": [
                {"stop_id": stop1_id, "stop_sequence": 2},
                {"stop_id": stop2_id, "stop_sequence": 1},
            ]
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_reorder.status_code == 200
    reordered_data = res_reorder.json()
    assert len(reordered_data) == 2
    assert reordered_data[0]["id"] == stop2_id
    assert reordered_data[0]["stop_sequence"] == 1
    assert reordered_data[1]["id"] == stop1_id
    assert reordered_data[1]["stop_sequence"] == 2

    # 11. Delete stop safely
    res_del_stop = await async_client.delete(
        f"/api/v1/routes/{route1.id}/stops/{stop1_id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_del_stop.status_code == 204

    # Verify route details reflect single remaining stop
    res_rt_details = await async_client.get(
        f"/api/v1/routes/{route1.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_rt_details.status_code == 200
    assert len(res_rt_details.json()["stops"]) == 1
    assert res_rt_details.json()["stops"][0]["id"] == stop2_id


@pytest.mark.asyncio
async def test_demo_fleet_seeding_idempotence(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    monkeypatch,
):
    """
    Verify complete demo fleet seeding and idempotence:
    - Seeding creates demo vehicle, demo route, 4 collection points, and 4 ordered stops.
    - All collection points belong to the same ward.
    - Stops are ordered sequentially along the route.
    - Repeated calls to seed-demo are strictly idempotent (no duplicates created).
    """
    monkeypatch.setattr(settings, "SIMULATION_ENABLED", True)

    ward = Ward(ward_code=f"W-SEED-{uuid.uuid4().hex[:6]}", display_name="Seed Ward")
    admin = User(
        email=f"admin_seed_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([ward, admin])
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))

    # 1. First seeding execution
    res_seed1 = await async_client.post(
        "/api/v1/simulation/seed-demo",
        json={"ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_seed1.status_code == 201
    data1 = res_seed1.json()
    assert data1["ward_id"] == str(ward.id)
    assert data1["stop_count"] == 4
    assert len(data1["collection_point_ids"]) == 4

    # Verify database state after initial seeding
    route_stmt = select(CollectionRoute).where(CollectionRoute.id == uuid.UUID(data1["route_id"]))
    route = (await async_db_session.execute(route_stmt)).scalars().first()
    assert route is not None
    assert route.is_simulated is True
    assert route.is_published is True

    stops_stmt = (
        select(RouteStop)
        .where(RouteStop.route_id == route.id)
        .order_by(RouteStop.stop_sequence.asc())
    )
    stops = (await async_db_session.execute(stops_stmt)).scalars().all()
    assert len(stops) == 4
    for idx, s in enumerate(stops, start=1):
        assert s.stop_sequence == idx

    # 2. Second seeding execution (must be completely idempotent)
    res_seed2 = await async_client.post(
        "/api/v1/simulation/seed-demo",
        json={"ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_seed2.status_code == 201
    data2 = res_seed2.json()
    assert data2["vehicle_id"] == data1["vehicle_id"]
    assert data2["route_id"] == data1["route_id"]
    assert data2["collection_point_ids"] == data1["collection_point_ids"]

    # Verify counts in database remain exactly identical
    all_routes = (
        await async_db_session.execute(
            select(CollectionRoute).where(CollectionRoute.ward_id == ward.id)
        )
    ).scalars().all()
    assert len(all_routes) == 1

    all_vehicles = (
        await async_db_session.execute(
            select(Vehicle).where(Vehicle.assigned_ward_id == ward.id)
        )
    ).scalars().all()
    assert len(all_vehicles) == 1

    all_points = (
        await async_db_session.execute(
            select(CollectionPoint).where(CollectionPoint.ward_id == ward.id)
        )
    ).scalars().all()
    assert len(all_points) == 4

    all_stops = (
        await async_db_session.execute(
            select(RouteStop).where(RouteStop.route_id == route.id)
        )
    ).scalars().all()
    assert len(all_stops) == 4
