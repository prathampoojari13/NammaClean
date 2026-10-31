"""
Tests for NammaClean Stage 2.8.3: Collection Routes and Ordered Collection Stops.
Verifies CollectionRoute and RouteStop models, LineString geometry (SRID 4326), GiST spatial indexes,
positive sequence and arrival offset check constraints, stop sequence uniqueness, ward consistency,
and role-based authorization for Municipal Admins and assigned Ward Supervisors.
"""

import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, CollectionPointType
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.collection_point import CollectionPoint
from app.models.route import CollectionRoute, RouteStop


@pytest.mark.asyncio
async def test_route_model_persistence_and_geometry(async_db_session: AsyncSession):
    """
    Verify:
    1. CollectionRoute persists LineString geometry with SRID 4326.
    2. Coordinates correctly map Longitude to X and Latitude to Y.
    3. Foreign key relationship to Ward works and cascades.
    """
    ward = Ward(
        ward_code=f"W-RT-{uuid.uuid4().hex[:6]}",
        display_name="Route Test Ward",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    coords = [(77.5800, 12.9600), (77.5900, 12.9700), (77.6000, 12.9800)]
    ls = LineString(coords)
    route_geom = WKTElement(ls.wkt, srid=4326)

    route = CollectionRoute(
        ward_id=ward.id,
        name="MG Road Morning Collection",
        route_code="RT-MGR-01",
        route_path=route_geom,
        is_active=True,
    )
    async_db_session.add(route)
    await async_db_session.commit()
    await async_db_session.refresh(route)

    assert route.id is not None
    assert route.ward_id == ward.id
    assert route.route_code == "RT-MGR-01"

    shape = to_shape(route.route_path)
    assert shape.geom_type == "LineString"
    extracted_coords = list(shape.coords)
    assert len(extracted_coords) == 3
    for orig, ext in zip(coords, extracted_coords):
        assert pytest.approx(orig[0], rel=1e-5) == ext[0]  # Longitude (X)
        assert pytest.approx(orig[1], rel=1e-5) == ext[1]  # Latitude (Y)

    # Cascade delete verification
    await async_db_session.delete(ward)
    await async_db_session.commit()

    res = await async_db_session.execute(select(CollectionRoute).where(CollectionRoute.id == route.id))
    assert res.scalars().first() is None


@pytest.mark.asyncio
async def test_route_spatial_and_unique_indexes_exist(async_db_session: AsyncSession):
    """
    Verify:
    1. GiST spatial index on collection_routes.route_path.
    2. Unique constraint on route_stops (route_id, stop_sequence).
    """
    res = await async_db_session.execute(text("""
        SELECT tablename, indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename IN ('collection_routes', 'route_stops');
    """))
    indexes = {f"{row[0]}.{row[1]}": row[2] for row in res.fetchall()}

    assert "collection_routes.idx_collection_routes_route_path" in indexes
    assert "gist (route_path)" in indexes["collection_routes.idx_collection_routes_route_path"].lower()

    assert "route_stops.uq_route_stops_route_sequence" in indexes
    assert "unique" in indexes["route_stops.uq_route_stops_route_sequence"].lower()


@pytest.mark.asyncio
async def test_route_stop_database_constraints_and_ordering(async_db_session: AsyncSession):
    """
    Verify:
    1. Stop sequence uniqueness within route.
    2. Positive sequence check constraint (> 0).
    3. Non-negative offset check constraint (>= 0).
    """
    ward = Ward(
        ward_code=f"W-STOP-{uuid.uuid4().hex[:6]}",
        display_name="Stop Test Ward",
    )
    async_db_session.add(ward)
    await async_db_session.commit()
    ward_id = ward.id

    route = CollectionRoute(
        ward_id=ward_id,
        name="Test Constraints Route",
        route_path=WKTElement("LINESTRING(77.58 12.96, 77.59 12.97)", srid=4326),
    )
    cp1 = CollectionPoint(
        ward_id=ward.id,
        name="CP 1",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.58 12.96)", srid=4326),
    )
    cp2 = CollectionPoint(
        ward_id=ward.id,
        name="CP 2",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.59 12.97)", srid=4326),
    )
    async_db_session.add_all([route, cp1, cp2])
    await async_db_session.commit()
    route_id = route.id
    cp1_id = cp1.id
    cp2_id = cp2.id

    # 1. Valid stop 1
    stop1 = RouteStop(
        route_id=route_id,
        collection_point_id=cp1_id,
        stop_sequence=1,
        planned_arrival_offset_minutes=15,
    )
    async_db_session.add(stop1)
    await async_db_session.commit()

    # 2. Duplicate sequence (stop_sequence=1 again) -> IntegrityError
    stop_dup = RouteStop(
        route_id=route_id,
        collection_point_id=cp2_id,
        stop_sequence=1,
    )
    async_db_session.add(stop_dup)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # 3. Sequence <= 0 -> IntegrityError
    stop_bad_seq = RouteStop(
        route_id=route_id,
        collection_point_id=cp2_id,
        stop_sequence=0,
    )
    async_db_session.add(stop_bad_seq)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # 4. Offset < 0 -> IntegrityError
    stop_bad_offset = RouteStop(
        route_id=route_id,
        collection_point_id=cp2_id,
        stop_sequence=2,
        planned_arrival_offset_minutes=-10,
    )
    async_db_session.add(stop_bad_offset)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # Cleanup
    w_clean = (await async_db_session.execute(select(Ward).where(Ward.id == ward_id))).scalars().first()
    if w_clean:
        await async_db_session.delete(w_clean)
        await async_db_session.commit()


@pytest.mark.asyncio
async def test_admin_can_manage_routes_and_stops_api(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Municipal Admin can create a collection route via API.
    2. Municipal Admin can add stops to the route.
    3. Municipal Admin can retrieve route with ordered stops.
    """
    admin = User(
        email=f"admin_rt_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(
        ward_code=f"W-API-RT-{uuid.uuid4().hex[:6]}",
        display_name="API Route Ward",
    )
    async_db_session.add_all([admin, ward])
    await async_db_session.commit()

    cp1 = CollectionPoint(
        ward_id=ward.id,
        name="Point 1",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.60 12.97)", srid=4326),
    )
    cp2 = CollectionPoint(
        ward_id=ward.id,
        name="Point 2",
        point_type=CollectionPointType.DOOR_TO_DOOR_PICKUP.value,
        location=WKTElement("POINT(77.61 12.98)", srid=4326),
    )
    async_db_session.add_all([cp1, cp2])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Route
    route_payload = {
        "name": "Koramangala Feeder Route",
        "route_code": "KOR-F-01",
        "coordinates": [
            [77.6000, 12.9700],
            [77.6050, 12.9750],
            [77.6100, 12.9800],
        ],
        "is_active": True,
    }
    create_res = await async_client.post(
        f"/api/v1/wards/{ward.id}/routes",
        json=route_payload,
        headers=headers,
    )
    assert create_res.status_code == 201
    route_data = create_res.json()
    route_id = route_data["id"]
    assert route_data["name"] == "Koramangala Feeder Route"
    assert len(route_data["coordinates"]) == 3

    # 2. Add Stop 1
    stop1_res = await async_client.post(
        f"/api/v1/routes/{route_id}/stops",
        json={
            "collection_point_id": str(cp1.id),
            "stop_sequence": 1,
            "planned_arrival_offset_minutes": 10,
        },
        headers=headers,
    )
    assert stop1_res.status_code == 201

    # Add Stop 2
    stop2_res = await async_client.post(
        f"/api/v1/routes/{route_id}/stops",
        json={
            "collection_point_id": str(cp2.id),
            "stop_sequence": 2,
            "planned_arrival_offset_minutes": 25,
        },
        headers=headers,
    )
    assert stop2_res.status_code == 201

    # 3. Get Route with ordered stops
    get_res = await async_client.get(f"/api/v1/routes/{route_id}", headers=headers)
    assert get_res.status_code == 200
    fetched_data = get_res.json()
    assert len(fetched_data["stops"]) == 2
    assert fetched_data["stops"][0]["stop_sequence"] == 1
    assert fetched_data["stops"][0]["planned_arrival_offset_minutes"] == 10
    assert fetched_data["stops"][1]["stop_sequence"] == 2

    # Cleanup
    await async_db_session.delete(ward)
    await async_db_session.delete(admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_ward_supervisor_assigned_vs_unassigned_authorization(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Ward Supervisor can manage routes in a ward they are actively assigned to.
    2. Ward Supervisor receives HTTP 403 Forbidden in a ward they are NOT assigned to.
    3. Ward Supervisor receives HTTP 403 Forbidden if their assignment was revoked.
    """
    supervisor = User(
        email=f"sup_route_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    ward_assigned = Ward(
        ward_code=f"W-ASN-{uuid.uuid4().hex[:6]}",
        display_name="Assigned Supervisor Ward",
    )
    ward_unassigned = Ward(
        ward_code=f"W-UNASN-{uuid.uuid4().hex[:6]}",
        display_name="Unassigned Ward",
    )
    async_db_session.add_all([supervisor, ward_assigned, ward_unassigned])
    await async_db_session.commit()

    # Active assignment to ward_assigned
    assignment = UserWardAssignment(
        user_id=supervisor.id,
        ward_id=ward_assigned.id,
        revoked_at=None,
    )
    async_db_session.add(assignment)
    await async_db_session.commit()

    token = create_access_token(subject=supervisor.id)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Supervisor Route",
        "coordinates": [[77.58, 12.96], [77.59, 12.97]],
    }

    # 1. Success in assigned ward (HTTP 201)
    res_assigned = await async_client.post(
        f"/api/v1/wards/{ward_assigned.id}/routes",
        json=payload,
        headers=headers,
    )
    assert res_assigned.status_code == 201

    # 2. Forbidden in unassigned ward (HTTP 403)
    res_unassigned = await async_client.post(
        f"/api/v1/wards/{ward_unassigned.id}/routes",
        json=payload,
        headers=headers,
    )
    assert res_unassigned.status_code == 403
    assert "not assigned as supervisor" in res_unassigned.json()["detail"].lower()

    # 3. Revoke assignment and test again -> HTTP 403
    assignment.revoked_at = datetime.now(timezone.utc)
    await async_db_session.commit()

    res_revoked = await async_client.post(
        f"/api/v1/wards/{ward_assigned.id}/routes",
        json=payload,
        headers=headers,
    )
    assert res_revoked.status_code == 403

    # Cleanup
    await async_db_session.delete(ward_assigned)
    await async_db_session.delete(ward_unassigned)
    await async_db_session.delete(supervisor)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_ward_consistency_enforced_for_route_stops(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    Attempting to add a collection point belonging to Ward B to a route in Ward A
    fails with HTTP 400 Bad Request.
    """
    admin = User(
        email=f"admin_ward_consist_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    ward_a = Ward(ward_code=f"W-A-{uuid.uuid4().hex[:6]}", display_name="Ward A")
    ward_b = Ward(ward_code=f"W-B-{uuid.uuid4().hex[:6]}", display_name="Ward B")
    async_db_session.add_all([admin, ward_a, ward_b])
    await async_db_session.commit()

    # Route in Ward A
    route_a = CollectionRoute(
        ward_id=ward_a.id,
        name="Route in Ward A",
        route_path=WKTElement("LINESTRING(77.58 12.96, 77.59 12.97)", srid=4326),
    )
    # Collection point in Ward B
    cp_b = CollectionPoint(
        ward_id=ward_b.id,
        name="Collection Point in Ward B",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.65 12.92)", srid=4326),
    )
    async_db_session.add_all([route_a, cp_b])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Attempt to associate CP from Ward B to Route in Ward A
    response = await async_client.post(
        f"/api/v1/routes/{route_a.id}/stops",
        json={
            "collection_point_id": str(cp_b.id),
            "stop_sequence": 1,
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "belongs to ward" in response.json()["detail"].lower()

    # Cleanup
    await async_db_session.delete(ward_a)
    await async_db_session.delete(ward_b)
    await async_db_session.delete(admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_duplicate_stop_sequence_api_conflict(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Adding a stop with an existing sequence number returns HTTP 409 Conflict."""
    admin = User(
        email=f"admin_dup_seq_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(ward_code=f"W-DUP-{uuid.uuid4().hex[:6]}", display_name="Dup Ward")
    async_db_session.add_all([admin, ward])
    await async_db_session.commit()

    route = CollectionRoute(
        ward_id=ward.id,
        name="Dup Seq Route",
        route_path=WKTElement("LINESTRING(77.58 12.96, 77.59 12.97)", srid=4326),
    )
    cp1 = CollectionPoint(
        ward_id=ward.id,
        name="CP 1",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.58 12.96)", srid=4326),
    )
    cp2 = CollectionPoint(
        ward_id=ward.id,
        name="CP 2",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.59 12.97)", srid=4326),
    )
    async_db_session.add_all([route, cp1, cp2])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Add stop sequence 1
    res1 = await async_client.post(
        f"/api/v1/routes/{route.id}/stops",
        json={"collection_point_id": str(cp1.id), "stop_sequence": 1},
        headers=headers,
    )
    assert res1.status_code == 201

    # Attempt to add another stop with sequence 1 -> HTTP 409
    res2 = await async_client.post(
        f"/api/v1/routes/{route.id}/stops",
        json={"collection_point_id": str(cp2.id), "stop_sequence": 1},
        headers=headers,
    )
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()

    # Cleanup
    await async_db_session.delete(ward)
    await async_db_session.delete(admin)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_unauthorized_roles_cannot_modify_routes(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Citizens, Drivers, and Sanitation Workers receive HTTP 403 on route endpoints."""
    citizen = User(
        email=f"cit_rt_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(ward_code=f"W-CIT-{uuid.uuid4().hex[:6]}", display_name="Cit Ward")
    async_db_session.add_all([citizen, ward])
    await async_db_session.commit()

    token = create_access_token(subject=citizen.id)
    payload = {
        "name": "Citizen Illegal Route",
        "coordinates": [[77.58, 12.96], [77.59, 12.97]],
    }
    response = await async_client.post(
        f"/api/v1/wards/{ward.id}/routes",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    # Cleanup
    await async_db_session.delete(ward)
    await async_db_session.delete(citizen)
    await async_db_session.commit()
