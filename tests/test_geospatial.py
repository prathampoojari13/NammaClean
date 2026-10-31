"""
Tests for NammaClean Stage 2.8.1: Collection Areas and Collection Points.
Verifies Ward boundary geometry (MultiPolygon, SRID 4326, nullable), CollectionPoint model,
foreign key relationships, PostGIS Point geometry (X=lon, Y=lat), GiST spatial indexes,
database check constraints, and role-protected administrative API endpoints.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point, Polygon, MultiPolygon

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, CollectionPointType
from app.models.user import User
from app.models.ward import Ward
from app.models.collection_point import CollectionPoint


@pytest.mark.asyncio
async def test_ward_boundary_is_nullable(async_db_session: AsyncSession):
    """Verify: Ward boundary geometry is nullable and accepts None."""
    ward = Ward(
        ward_code=f"W-NULL-{uuid.uuid4().hex[:6]}",
        display_name="Test Null Boundary Ward",
        boundary=None,
    )
    async_db_session.add(ward)
    await async_db_session.commit()
    await async_db_session.refresh(ward)

    assert ward.id is not None
    assert ward.boundary is None

    # Cleanup
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_ward_with_multipolygon_boundary(async_db_session: AsyncSession):
    """Verify: Ward accepts a valid WGS 84 (SRID 4326) MultiPolygon geometry."""
    # Synthetic test polygon in Bengaluru region
    poly = Polygon([
        (77.580, 12.960),
        (77.600, 12.960),
        (77.600, 12.980),
        (77.580, 12.980),
        (77.580, 12.960),
    ])
    mp = MultiPolygon([poly])
    wkt_boundary = WKTElement(mp.wkt, srid=4326)

    ward = Ward(
        ward_code=f"W-GEO-{uuid.uuid4().hex[:6]}",
        display_name="Test Geo Ward",
        boundary=wkt_boundary,
    )
    async_db_session.add(ward)
    await async_db_session.commit()
    await async_db_session.refresh(ward)

    assert ward.boundary is not None
    shape = to_shape(ward.boundary)
    assert shape.geom_type == "MultiPolygon"
    assert shape.is_valid

    # Cleanup
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_collection_point_model_and_coordinate_orientation(async_db_session: AsyncSession):
    """
    Verify:
    1. CollectionPoint stores Point geometry with SRID 4326.
    2. Longitude maps to X, Latitude maps to Y.
    3. Foreign key relationship to Ward works as expected.
    """
    ward = Ward(
        ward_code=f"W-CP-{uuid.uuid4().hex[:6]}",
        display_name="Collection Point Test Ward",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    test_lon = 77.5946
    test_lat = 12.9716
    point_geom = WKTElement(f"POINT({test_lon} {test_lat})", srid=4326)

    cp = CollectionPoint(
        ward_id=ward.id,
        name="Indiranagar Community Bin #1",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=point_geom,
        is_active=True,
    )
    async_db_session.add(cp)
    await async_db_session.commit()
    await async_db_session.refresh(cp)

    assert cp.id is not None
    assert cp.ward_id == ward.id
    assert cp.is_active is True
    assert cp.created_at is not None
    assert cp.updated_at is not None

    shape = to_shape(cp.location)
    assert shape.geom_type == "Point"
    assert pytest.approx(shape.x, rel=1e-5) == test_lon
    assert pytest.approx(shape.y, rel=1e-5) == test_lat

    # Cleanup
    await async_db_session.delete(ward)  # Cascades to cp
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_collection_point_cascade_delete(async_db_session: AsyncSession):
    """Verify: Deleting a ward cascades and deletes associated collection points."""
    ward = Ward(
        ward_code=f"W-CAS-{uuid.uuid4().hex[:6]}",
        display_name="Cascade Delete Ward",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    cp = CollectionPoint(
        ward_id=ward.id,
        name="Temporary Bin",
        point_type=CollectionPointType.COMMUNITY_BIN.value,
        location=WKTElement("POINT(77.60 12.97)", srid=4326),
    )
    async_db_session.add(cp)
    await async_db_session.commit()
    cp_id = cp.id

    # Delete parent ward
    await async_db_session.delete(ward)
    await async_db_session.commit()

    # Verify collection point was deleted
    res = await async_db_session.execute(select(CollectionPoint).where(CollectionPoint.id == cp_id))
    assert res.scalars().first() is None


@pytest.mark.asyncio
async def test_collection_point_check_constraint_valid_types(async_db_session: AsyncSession):
    """Verify: Database check constraint enforces valid CollectionPointType values."""
    ward = Ward(
        ward_code=f"W-CHK-{uuid.uuid4().hex[:6]}",
        display_name="Check Constraint Ward",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    # Attempt to insert an invalid point_type
    invalid_cp = CollectionPoint(
        ward_id=ward.id,
        name="Invalid Type Point",
        point_type="INVALID_NONEXISTENT_TYPE",
        location=WKTElement("POINT(77.60 12.97)", srid=4326),
    )
    async_db_session.add(invalid_cp)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()

    await async_db_session.rollback()

    # Cleanup
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_database_spatial_indexes_exist(async_db_session: AsyncSession):
    """Verify: PostGIS GiST spatial indexes exist on wards.boundary and collection_points.location."""
    res = await async_db_session.execute(text("""
        SELECT tablename, indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename IN ('wards', 'collection_points')
          AND indexdef LIKE '%gist%';
    """))
    gist_indexes = {f"{row[0]}.{row[1]}" for row in res.fetchall()}

    assert "wards.idx_wards_boundary" in gist_indexes
    assert "collection_points.idx_collection_points_location" in gist_indexes


@pytest.mark.asyncio
async def test_admin_create_collection_point_api_success(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Municipal Admin can successfully create a collection point via API."""
    admin = User(
        email=f"admin_geo_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(
        ward_code=f"W-API-{uuid.uuid4().hex[:6]}",
        display_name="API Test Ward",
    )
    async_db_session.add_all([admin, ward])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Koramangala 5th Block Bin",
        "point_type": CollectionPointType.COMMUNITY_BIN.value,
        "latitude": 12.9352,
        "longitude": 77.6245,
        "is_active": True,
    }

    response = await async_client.post(
        f"/api/v1/wards/{ward.id}/collection-points",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["point_type"] == payload["point_type"]
    assert data["ward_id"] == str(ward.id)
    assert pytest.approx(data["latitude"], rel=1e-4) == payload["latitude"]
    assert pytest.approx(data["longitude"], rel=1e-4) == payload["longitude"]
    assert data["is_active"] is True

    # Test listing collection points
    get_res = await async_client.get(
        f"/api/v1/wards/{ward.id}/collection-points",
        headers=headers,
    )
    assert get_res.status_code == 200
    points = get_res.json()
    assert len(points) >= 1
    assert any(p["name"] == payload["name"] for p in points)

    # Cleanup
    await async_db_session.delete(admin)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_citizen_and_driver_forbidden_from_creating_collection_point(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Citizens and Drivers receive HTTP 403 when attempting to create a collection point."""
    citizen = User(
        email=f"citizen_geo_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    driver = User(
        email=f"driver_geo_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(
        ward_code=f"W-AUTH-{uuid.uuid4().hex[:6]}",
        display_name="Auth Test Ward",
    )
    async_db_session.add_all([citizen, driver, ward])
    await async_db_session.commit()

    payload = {
        "name": "Unauthorized Bin",
        "point_type": CollectionPointType.COMMUNITY_BIN.value,
        "latitude": 12.9352,
        "longitude": 77.6245,
    }

    # Citizen test (HTTP 403)
    token_c = create_access_token(subject=citizen.id)
    res_c = await async_client.post(
        f"/api/v1/wards/{ward.id}/collection-points",
        json=payload,
        headers={"Authorization": f"Bearer {token_c}"},
    )
    assert res_c.status_code == 403
    assert res_c.json()["detail"] == "Insufficient permissions for this resource."

    # Driver test (HTTP 403)
    token_d = create_access_token(subject=driver.id)
    res_d = await async_client.post(
        f"/api/v1/wards/{ward.id}/collection-points",
        json=payload,
        headers={"Authorization": f"Bearer {token_d}"},
    )
    assert res_d.status_code == 403

    # Cleanup
    await async_db_session.delete(citizen)
    await async_db_session.delete(driver)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_create_collection_point_coordinate_validation(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify: Coordinate boundaries (-90 <= lat <= 90, -180 <= lon <= 180) are strictly validated."""
    admin = User(
        email=f"admin_coord_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(
        ward_code=f"W-COORD-{uuid.uuid4().hex[:6]}",
        display_name="Coord Test Ward",
    )
    async_db_session.add_all([admin, ward])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Invalid latitude > 90
    bad_lat_res = await async_client.post(
        f"/api/v1/wards/{ward.id}/collection-points",
        json={
            "name": "Invalid Lat Point",
            "point_type": CollectionPointType.COMMUNITY_BIN.value,
            "latitude": 95.0,
            "longitude": 77.5,
        },
        headers=headers,
    )
    assert bad_lat_res.status_code == 422

    # Invalid longitude > 180
    bad_lon_res = await async_client.post(
        f"/api/v1/wards/{ward.id}/collection-points",
        json={
            "name": "Invalid Lon Point",
            "point_type": CollectionPointType.COMMUNITY_BIN.value,
            "latitude": 12.9,
            "longitude": 185.0,
        },
        headers=headers,
    )
    assert bad_lon_res.status_code == 422

    # Cleanup
    await async_db_session.delete(admin)
    await async_db_session.delete(ward)
    await async_db_session.commit()
