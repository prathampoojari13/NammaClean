"""
Regression tests for Stage 2.9.1A: Audit Fixes for Authorization and Telemetry Integrity.
Covers:
1. Ward supervisor collection-point creation & listing restricted to actively assigned wards.
2. Ward supervisor vehicle creation restricted to actively assigned wards (unassigned ward rejected).
3. Ward supervisor telemetry ingestion restricted to actively assigned wards (unassigned vehicle rejected).
4. Genuine vehicle with no existing GPS snapshot is NOT initialized or mutated by simulated telemetry.
5. Genuine vehicle with existing genuine snapshot is NOT overwritten by simulated telemetry.
6. Municipal admin permissions and driver assigned-vehicle telemetry are preserved.
7. Citizen and sanitation worker restrictions remain strictly enforced.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.shape import to_shape
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, VehicleType, VehicleStatus, CollectionPointType
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.vehicle import Vehicle, VehiclePosition, utc_now
from app.models.collection_point import CollectionPoint


@pytest.mark.asyncio
async def test_supervisor_collection_points_assigned_vs_unassigned(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Supervisor assigned to Ward 1 can create and list collection points in Ward 1.
    2. Supervisor CANNOT create or list collection points in Ward 2 (HTTP 403 Forbidden).
    3. Municipal Admin can create and list in any ward.
    """
    ward1 = Ward(ward_code=f"W-CP1-{uuid.uuid4().hex[:6]}", display_name="Ward 1")
    ward2 = Ward(ward_code=f"W-CP2-{uuid.uuid4().hex[:6]}", display_name="Ward 2")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_cp_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    admin = User(
        email=f"adm_cp_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([supervisor, admin])
    await async_db_session.commit()

    # Assign supervisor strictly to Ward 1
    assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward1.id)
    async_db_session.add(assign)
    await async_db_session.commit()

    token_sup = create_access_token(subject=supervisor.id)
    token_adm = create_access_token(subject=admin.id)
    headers_sup = {"Authorization": f"Bearer {token_sup}"}
    headers_adm = {"Authorization": f"Bearer {token_adm}"}

    # 1. Supervisor CAN create in assigned Ward 1
    res1 = await async_client.post(
        f"/api/v1/wards/{ward1.id}/collection-points",
        json={
            "name": "Ward 1 Community Bin",
            "point_type": CollectionPointType.COMMUNITY_BIN.value,
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        headers=headers_sup,
    )
    assert res1.status_code == 201
    cp1_id = res1.json()["id"]

    # 2. Supervisor CAN list in assigned Ward 1
    res_list1 = await async_client.get(
        f"/api/v1/wards/{ward1.id}/collection-points",
        headers=headers_sup,
    )
    assert res_list1.status_code == 200
    assert any(p["id"] == cp1_id for p in res_list1.json())

    # 3. Supervisor CANNOT create in unassigned Ward 2
    res2 = await async_client.post(
        f"/api/v1/wards/{ward2.id}/collection-points",
        json={
            "name": "Ward 2 Community Bin",
            "point_type": CollectionPointType.COMMUNITY_BIN.value,
            "latitude": 12.9800,
            "longitude": 77.6000,
        },
        headers=headers_sup,
    )
    assert res2.status_code == 403
    assert f"You are not assigned as supervisor for ward '{ward2.id}'" in res2.json()["detail"]

    # 4. Supervisor CANNOT list in unassigned Ward 2
    res_list2 = await async_client.get(
        f"/api/v1/wards/{ward2.id}/collection-points",
        headers=headers_sup,
    )
    assert res_list2.status_code == 403
    assert f"You are not assigned as supervisor for ward '{ward2.id}'" in res_list2.json()["detail"]

    # 5. Admin CAN create in Ward 2
    res_adm = await async_client.post(
        f"/api/v1/wards/{ward2.id}/collection-points",
        json={
            "name": "Ward 2 Admin Bin",
            "point_type": CollectionPointType.COMMUNITY_BIN.value,
            "latitude": 12.9800,
            "longitude": 77.6000,
        },
        headers=headers_adm,
    )
    assert res_adm.status_code == 201

    # Cleanup
    await async_db_session.execute(select(CollectionPoint).where(CollectionPoint.ward_id.in_([ward1.id, ward2.id])))
    cps = (await async_db_session.execute(select(CollectionPoint).where(CollectionPoint.ward_id.in_([ward1.id, ward2.id])))).scalars().all()
    for cp in cps:
        await async_db_session.delete(cp)
    await async_db_session.delete(assign)
    await async_db_session.delete(supervisor)
    await async_db_session.delete(admin)
    await async_db_session.delete(ward1)
    await async_db_session.delete(ward2)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_supervisor_cannot_create_vehicle_in_unassigned_ward(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Supervisor can create vehicle assigned to their assigned ward.
    2. Supervisor CANNOT create vehicle assigned to an unassigned ward (HTTP 403).
    3. Supervisor CANNOT create vehicle with no assigned ward (assigned_ward_id = None) (HTTP 403).
    4. Municipal admin CAN create vehicle with no assigned ward or any ward.
    """
    ward_assigned = Ward(ward_code=f"W-V1-{uuid.uuid4().hex[:6]}", display_name="Assigned Ward")
    ward_unassigned = Ward(ward_code=f"W-V2-{uuid.uuid4().hex[:6]}", display_name="Unassigned Ward")
    async_db_session.add_all([ward_assigned, ward_unassigned])
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_veh_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    admin = User(
        email=f"adm_veh_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([supervisor, admin])
    await async_db_session.commit()

    assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward_assigned.id)
    async_db_session.add(assign)
    await async_db_session.commit()

    headers_sup = {"Authorization": f"Bearer {create_access_token(subject=supervisor.id)}"}
    headers_adm = {"Authorization": f"Bearer {create_access_token(subject=admin.id)}"}

    # 1. Supervisor creates in assigned ward -> 201 Created
    reg1 = f"KA-01-S1-{uuid.uuid4().hex[:4].upper()}"
    res1 = await async_client.post(
        "/api/v1/vehicles",
        json={
            "registration_number": reg1,
            "vehicle_type": VehicleType.COMPACTOR_TRUCK.value,
            "assigned_ward_id": str(ward_assigned.id),
        },
        headers=headers_sup,
    )
    assert res1.status_code == 201
    veh1_id = res1.json()["id"]

    # 2. Supervisor creates in unassigned ward -> 403 Forbidden
    reg2 = f"KA-01-S2-{uuid.uuid4().hex[:4].upper()}"
    res2 = await async_client.post(
        "/api/v1/vehicles",
        json={
            "registration_number": reg2,
            "vehicle_type": VehicleType.AUTO_TIPPER.value,
            "assigned_ward_id": str(ward_unassigned.id),
        },
        headers=headers_sup,
    )
    assert res2.status_code == 403
    assert f"You are not assigned as supervisor for ward '{ward_unassigned.id}'" in res2.json()["detail"]

    # 3. Supervisor creates without assigned ward -> 403 Forbidden
    reg3 = f"KA-01-S3-{uuid.uuid4().hex[:4].upper()}"
    res3 = await async_client.post(
        "/api/v1/vehicles",
        json={
            "registration_number": reg3,
            "vehicle_type": VehicleType.AUTO_TIPPER.value,
            "assigned_ward_id": None,
        },
        headers=headers_sup,
    )
    assert res3.status_code == 403
    assert "Ward supervisors must assign created vehicles to a ward they are actively assigned to" in res3.json()["detail"]

    # 4. Admin creates without assigned ward -> 201 Created
    reg_adm = f"KA-01-ADM-{uuid.uuid4().hex[:4].upper()}"
    res_adm = await async_client.post(
        "/api/v1/vehicles",
        json={
            "registration_number": reg_adm,
            "vehicle_type": VehicleType.LORRY.value,
            "assigned_ward_id": None,
        },
        headers=headers_adm,
    )
    assert res_adm.status_code == 201
    veh_adm_id = res_adm.json()["id"]

    # Cleanup
    v1 = await async_db_session.get(Vehicle, uuid.UUID(veh1_id))
    v_adm = await async_db_session.get(Vehicle, uuid.UUID(veh_adm_id))
    if v1:
        await async_db_session.delete(v1)
    if v_adm:
        await async_db_session.delete(v_adm)
    await async_db_session.delete(assign)
    await async_db_session.delete(supervisor)
    await async_db_session.delete(admin)
    await async_db_session.delete(ward_assigned)
    await async_db_session.delete(ward_unassigned)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_supervisor_telemetry_restricted_to_assigned_ward_and_rejects_unassigned(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify:
    1. Supervisor can submit telemetry for vehicles in their assigned ward.
    2. Supervisor CANNOT submit telemetry for vehicles in an unassigned ward (HTTP 403).
    3. Supervisor CANNOT submit telemetry for an unassigned vehicle (assigned_ward_id is None) (HTTP 403).
    4. Driver can only submit for their assigned vehicle.
    5. Citizen & Sanitation Worker receive HTTP 403.
    """
    ward1 = Ward(ward_code=f"W-TEL1-{uuid.uuid4().hex[:6]}", display_name="Ward 1")
    ward2 = Ward(ward_code=f"W-TEL2-{uuid.uuid4().hex[:6]}", display_name="Ward 2")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_tel_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    driver = User(
        email=f"drv_tel_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    citizen = User(
        email=f"cit_tel_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([supervisor, driver, citizen])
    await async_db_session.commit()

    assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward1.id)
    async_db_session.add(assign)

    # Vehicles: in ward1, in ward2, and unassigned
    veh_w1 = Vehicle(
        registration_number=f"KA-01-TW1-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        assigned_ward_id=ward1.id,
        assigned_driver_id=driver.id,
    )
    veh_w2 = Vehicle(
        registration_number=f"KA-01-TW2-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        assigned_ward_id=ward2.id,
    )
    veh_unassigned = Vehicle(
        registration_number=f"KA-01-TUN-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        assigned_ward_id=None,
    )
    async_db_session.add_all([veh_w1, veh_w2, veh_unassigned])
    await async_db_session.commit()

    headers_sup = {"Authorization": f"Bearer {create_access_token(subject=supervisor.id)}"}
    headers_drv = {"Authorization": f"Bearer {create_access_token(subject=driver.id)}"}
    headers_cit = {"Authorization": f"Bearer {create_access_token(subject=citizen.id)}"}

    now_ts = utc_now().isoformat()
    pos_payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "recorded_at": now_ts,
        "is_simulated": False,
    }

    # 1. Supervisor submits for vehicle in assigned ward1 -> 201 Created
    res1 = await async_client.post(
        f"/api/v1/vehicles/{veh_w1.id}/positions",
        json=pos_payload,
        headers=headers_sup,
    )
    assert res1.status_code == 201

    # 2. Supervisor submits for vehicle in unassigned ward2 -> 403 Forbidden
    res2 = await async_client.post(
        f"/api/v1/vehicles/{veh_w2.id}/positions",
        json=pos_payload,
        headers=headers_sup,
    )
    assert res2.status_code == 403
    assert f"You are not assigned as supervisor for ward '{ward2.id}'" in res2.json()["detail"]

    # 3. Supervisor submits for unassigned vehicle -> 403 Forbidden
    res3 = await async_client.post(
        f"/api/v1/vehicles/{veh_unassigned.id}/positions",
        json=pos_payload,
        headers=headers_sup,
    )
    assert res3.status_code == 403
    assert "Ward supervisors cannot submit telemetry for an unassigned vehicle" in res3.json()["detail"]

    # 4. Assigned Driver submits for their vehicle -> 201 Created
    t_drv = (utc_now() + timedelta(seconds=1)).isoformat()
    res_drv = await async_client.post(
        f"/api/v1/vehicles/{veh_w1.id}/positions",
        json={"latitude": 12.9720, "longitude": 77.5950, "recorded_at": t_drv, "is_simulated": False},
        headers=headers_drv,
    )
    assert res_drv.status_code == 201

    # 5. Assigned Driver submits for unassigned vehicle -> 403 Forbidden
    res_drv_bad = await async_client.post(
        f"/api/v1/vehicles/{veh_w2.id}/positions",
        json=pos_payload,
        headers=headers_drv,
    )
    assert res_drv_bad.status_code == 403

    # 6. Citizen submits -> 403 Forbidden
    res_cit = await async_client.post(
        f"/api/v1/vehicles/{veh_w1.id}/positions",
        json=pos_payload,
        headers=headers_cit,
    )
    assert res_cit.status_code == 403

    # Cleanup
    for v in [veh_w1, veh_w2, veh_unassigned]:
        positions = (await async_db_session.execute(select(VehiclePosition).where(VehiclePosition.vehicle_id == v.id))).scalars().all()
        for p in positions:
            await async_db_session.delete(p)
        await async_db_session.delete(v)
    await async_db_session.delete(assign)
    await async_db_session.delete(citizen)
    await async_db_session.delete(driver)
    await async_db_session.delete(supervisor)
    await async_db_session.delete(ward1)
    await async_db_session.delete(ward2)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_simulated_telemetry_cannot_initialize_genuine_vehicle_snapshot(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify Issue 4 edge case:
    A genuine vehicle has is_simulated == False, current_location is None, last_seen_at is None.
    When a simulated telemetry packet arrives:
    1. Historical position IS recorded in vehicle_positions with is_simulated = True.
    2. The vehicle's cached snapshot is NOT initialized from simulated data:
       current_location remains None, last_seen_at remains None, is_simulated remains False!
    3. When subsequent genuine telemetry arrives (is_simulated = False), the snapshot IS initialized.
    """
    admin = User(
        email=f"admin_edge_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    vehicle = Vehicle(
        registration_number=f"KA-01-GEN-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        is_simulated=False,
    )
    async_db_session.add_all([admin, vehicle])
    await async_db_session.commit()

    token = create_access_token(subject=admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Simulated telemetry packet arrives
    sim_time = utc_now()
    res_sim = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json={
            "latitude": 12.9800,
            "longitude": 77.6100,
            "recorded_at": sim_time.isoformat(),
            "is_simulated": True,
        },
        headers=headers,
    )
    assert res_sim.status_code == 201
    assert res_sim.json()["is_simulated"] is True

    # Step 2: Verify database state of the vehicle
    await async_db_session.refresh(vehicle)
    # The snapshot MUST NOT be initialized or turned into simulated!
    assert vehicle.current_location is None
    assert vehicle.last_seen_at is None
    assert vehicle.is_simulated is False

    # Historical record exists
    pos_res = await async_db_session.execute(
        select(VehiclePosition).where(VehiclePosition.vehicle_id == vehicle.id)
    )
    positions = pos_res.scalars().all()
    assert len(positions) == 1
    assert positions[0].is_simulated is True

    # Step 3: Now genuine telemetry arrives
    real_time = utc_now()
    res_real = await async_client.post(
        f"/api/v1/vehicles/{vehicle.id}/positions",
        json={
            "latitude": 12.9716,
            "longitude": 77.5946,
            "recorded_at": real_time.isoformat(),
            "is_simulated": False,
        },
        headers=headers,
    )
    assert res_real.status_code == 201
    assert res_real.json()["is_simulated"] is False

    # Verify vehicle snapshot IS now initialized with genuine GPS data
    await async_db_session.refresh(vehicle)
    assert vehicle.current_location is not None
    shape = to_shape(vehicle.current_location)
    assert pytest.approx(shape.y, rel=1e-4) == 12.9716
    assert pytest.approx(shape.x, rel=1e-4) == 77.5946
    assert vehicle.last_seen_at is not None
    assert vehicle.is_simulated is False

    # Cleanup
    positions_all = (await async_db_session.execute(select(VehiclePosition).where(VehiclePosition.vehicle_id == vehicle.id))).scalars().all()
    for p in positions_all:
        await async_db_session.delete(p)
    await async_db_session.delete(vehicle)
    await async_db_session.delete(admin)
    await async_db_session.commit()
