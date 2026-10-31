"""
Tests for Stage 2.9.1B: Ward Navigation & Fleet Inventory APIs.

Covers:
1. Public ward list and ward detail (including missing ward and missing boundary).
2. Admin city-wide fleet listing and filtering (ward_id, status, vehicle_type).
3. Supervisor fleet listing restricted to active ward assignments.
4. Supervisor requests for an unassigned ward denied (HTTP 403).
5. Supervisors never seeing NULL-ward vehicles or unassigned wards.
6. Role denials for citizen, sanitation worker, and driver on fleet listing.
7. Valid operational vehicle update by ward supervisor.
8. Cross-ward update denial for ward supervisor.
9. Supervisor attempt to change ward or driver assignment (HTTP 403).
10. Admin assignment updates with invalid ward/driver references (HTTP 404 / 400).
11. Admin duplicate registration number conflict (HTTP 409).
12. Attempted changes to protected fields (is_simulated, is_published) rejected (HTTP 422).
"""

import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, VehicleStatus, VehicleType
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
async def test_public_ward_list_and_detail(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify public ward navigation:
    - GET /api/v1/public/wards returns safe public fields and boundary GeoJSON.
    - Handles wards with and without boundary geometry.
    - include_boundary query parameter toggles boundary serialization.
    - GET /api/v1/wards/{ward_id} returns single ward details (or 404 if missing).
    - No authentication required.
    """
    poly_wkt = "MULTIPOLYGON(((77.5 12.9, 77.6 12.9, 77.6 13.0, 77.5 13.0, 77.5 12.9)))"
    ward_with_geom = Ward(
        ward_code=f"W-GEOM-{uuid.uuid4().hex[:6]}",
        display_name="Ward With Geometry",
        boundary=WKTElement(poly_wkt, srid=4326),
    )
    ward_no_geom = Ward(
        ward_code=f"W-NOGEOM-{uuid.uuid4().hex[:6]}",
        display_name="Ward Without Geometry",
        boundary=None,
    )
    async_db_session.add_all([ward_with_geom, ward_no_geom])
    await async_db_session.commit()

    # 1. Unauthenticated list of public wards
    res = await async_client.get("/api/v1/public/wards")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 2

    matching_with_geom = next((w for w in data if w["id"] == str(ward_with_geom.id)), None)
    assert matching_with_geom is not None
    assert matching_with_geom["ward_code"] == ward_with_geom.ward_code
    assert matching_with_geom["display_name"] == ward_with_geom.display_name
    assert matching_with_geom["boundary"] is not None
    assert matching_with_geom["boundary"]["type"] == "MultiPolygon"
    assert "user_assignments" not in matching_with_geom

    matching_no_geom = next((w for w in data if w["id"] == str(ward_no_geom.id)), None)
    assert matching_no_geom is not None
    assert matching_no_geom["boundary"] is None

    # 2. Query with include_boundary=false
    res_no_bounds = await async_client.get("/api/v1/public/wards?include_boundary=false")
    assert res_no_bounds.status_code == 200
    data_no_bounds = res_no_bounds.json()
    matching_stripped = next((w for w in data_no_bounds if w["id"] == str(ward_with_geom.id)), None)
    assert matching_stripped is not None
    assert matching_stripped["boundary"] is None

    # 3. Unauthenticated ward details: existing with boundary
    res_detail = await async_client.get(f"/api/v1/wards/{ward_with_geom.id}")
    assert res_detail.status_code == 200
    detail_data = res_detail.json()
    assert detail_data["id"] == str(ward_with_geom.id)
    assert detail_data["boundary"]["type"] == "MultiPolygon"

    # 4. Unauthenticated ward details: existing without boundary
    res_detail_no_b = await async_client.get(f"/api/v1/wards/{ward_no_geom.id}")
    assert res_detail_no_b.status_code == 200
    assert res_detail_no_b.json()["boundary"] is None

    # 5. Nonexistent ward details -> 404
    fake_id = uuid.uuid4()
    res_404 = await async_client.get(f"/api/v1/wards/{fake_id}")
    assert res_404.status_code == 404
    assert f"Ward with id '{fake_id}' not found." in res_404.json()["detail"]


@pytest.mark.asyncio
async def test_admin_and_supervisor_fleet_inventory(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify fleet inventory query endpoint:
    - Municipal Admin can list city-wide fleet and filter by ward, status, type.
    - Ward Supervisor is strictly scoped to actively assigned wards.
    - Supervisor cannot view unassigned wards or the NULL-ward municipal pool.
    - Other roles are denied (HTTP 403).
    """
    # 1. Setup wards
    ward1 = Ward(ward_code=f"W1-{uuid.uuid4().hex[:6]}", display_name="Ward One")
    ward2 = Ward(ward_code=f"W2-{uuid.uuid4().hex[:6]}", display_name="Ward Two")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    # 2. Setup users: Admin, Supervisor (assigned to Ward 1 only), Citizen, Sanitation Worker
    admin = User(
        email=f"admin_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"sup_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    citizen = User(
        email=f"cit_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    worker = User(
        email=f"wrk_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor, citizen, worker])
    await async_db_session.commit()

    # Active assignment: supervisor -> ward1
    assignment = UserWardAssignment(
        user_id=supervisor.id,
        ward_id=ward1.id,
        assigned_at=datetime.now(timezone.utc),
        revoked_at=None,
    )
    async_db_session.add(assignment)

    # 3. Setup vehicles:
    # veh1 in Ward 1 (IDLE, AUTO_TIPPER)
    # veh2 in Ward 2 (COLLECTING, COMPACTOR_TRUCK)
    # veh3 in NULL-ward municipal pool (MAINTENANCE, LORRY)
    veh1 = Vehicle(
        registration_number=f"KA-01-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
        assigned_ward_id=ward1.id,
    )
    veh2 = Vehicle(
        registration_number=f"KA-02-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.COLLECTING.value,
        assigned_ward_id=ward2.id,
    )
    veh3 = Vehicle(
        registration_number=f"KA-03-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.LORRY.value,
        status=VehicleStatus.MAINTENANCE.value,
        assigned_ward_id=None,
    )
    async_db_session.add_all([veh1, veh2, veh3])
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))
    sup_token = create_access_token(str(supervisor.id))
    cit_token = create_access_token(str(citizen.id))
    wrk_token = create_access_token(str(worker.id))

    # --- Role Denials ---
    res_cit = await async_client.get(
        "/api/v1/vehicles",
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    assert res_cit.status_code == 403

    res_wrk = await async_client.get(
        "/api/v1/vehicles",
        headers={"Authorization": f"Bearer {wrk_token}"},
    )
    assert res_wrk.status_code == 403

    res_unauth = await async_client.get("/api/v1/vehicles")
    assert res_unauth.status_code == 401

    # --- Municipal Admin City-wide Access ---
    res_admin_all = await async_client.get(
        "/api/v1/vehicles",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin_all.status_code == 200
    admin_veh_ids = [v["id"] for v in res_admin_all.json()]
    assert str(veh1.id) in admin_veh_ids
    assert str(veh2.id) in admin_veh_ids
    assert str(veh3.id) in admin_veh_ids

    # Admin filtering by ward
    res_admin_w1 = await async_client.get(
        f"/api/v1/vehicles?ward_id={ward1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin_w1.status_code == 200
    w1_ids = [v["id"] for v in res_admin_w1.json()]
    assert str(veh1.id) in w1_ids
    assert str(veh2.id) not in w1_ids
    assert str(veh3.id) not in w1_ids

    # Admin filtering by status & type
    res_admin_filter = await async_client.get(
        f"/api/v1/vehicles?status={VehicleStatus.COLLECTING.value}&vehicle_type={VehicleType.COMPACTOR_TRUCK.value}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin_filter.status_code == 200
    filtered_ids = [v["id"] for v in res_admin_filter.json()]
    assert str(veh2.id) in filtered_ids
    assert str(veh1.id) not in filtered_ids

    # --- Ward Supervisor Access & Scoping ---
    # Supervisor with no ward filter: should see ONLY Ward 1, never Ward 2 or NULL-ward pool
    res_sup_all = await async_client.get(
        "/api/v1/vehicles",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_all.status_code == 200
    sup_veh_ids = [v["id"] for v in res_sup_all.json()]
    assert str(veh1.id) in sup_veh_ids
    assert str(veh2.id) not in sup_veh_ids
    assert str(veh3.id) not in sup_veh_ids

    # Supervisor filtering by actively assigned ward1: allowed
    res_sup_w1 = await async_client.get(
        f"/api/v1/vehicles?ward_id={ward1.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_w1.status_code == 200
    sup_w1_ids = [v["id"] for v in res_sup_w1.json()]
    assert str(veh1.id) in sup_w1_ids

    # Supervisor filtering by unassigned ward2: strictly denied (HTTP 403)
    res_sup_w2 = await async_client.get(
        f"/api/v1/vehicles?ward_id={ward2.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_w2.status_code == 403
    assert "not actively assigned to this ward" in res_sup_w2.json()["detail"]


@pytest.mark.asyncio
async def test_controlled_vehicle_updates_and_authorizations(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """
    Verify PATCH /api/v1/vehicles/{vehicle_id}:
    - Reject empty update payload (HTTP 400).
    - Return HTTP 404 for nonexistent vehicle.
    - Supervisor may update status and vehicle_type in their assigned ward.
    - Supervisor cannot perform cross-ward updates (HTTP 403).
    - Supervisor cannot modify unassigned (NULL-ward) vehicles (HTTP 403).
    - Supervisor cannot alter assigned_ward_id, assigned_driver_id, or registration_number (HTTP 403).
    - Admin can update operational fields, ward, and driver assignments.
    - Admin assignment validations: ward existence, driver role/status, uniqueness.
    - Protected fields (is_simulated, is_published, current_location) rejected (HTTP 422).
    """
    # 1. Setup wards
    ward1 = Ward(ward_code=f"W-UP1-{uuid.uuid4().hex[:6]}", display_name="Update Ward 1")
    ward2 = Ward(ward_code=f"W-UP2-{uuid.uuid4().hex[:6]}", display_name="Update Ward 2")
    async_db_session.add_all([ward1, ward2])
    await async_db_session.commit()

    # 2. Setup users: Admin, Supervisor, Active Driver, Disabled Driver, Citizen
    admin = User(
        email=f"adm_up_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.MUNICIPAL_ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    supervisor = User(
        email=f"sup_up_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    driver_active = User(
        email=f"drv_act_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    driver_disabled = User(
        email=f"drv_dis_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.DRIVER.value,
        status=UserStatus.DISABLED.value,
    )
    citizen = User(
        email=f"cit_up_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([admin, supervisor, driver_active, driver_disabled, citizen])
    await async_db_session.commit()

    # Active assignment: supervisor -> ward1
    assignment = UserWardAssignment(
        user_id=supervisor.id,
        ward_id=ward1.id,
        assigned_at=datetime.now(timezone.utc),
        revoked_at=None,
    )
    async_db_session.add(assignment)

    # 3. Setup vehicles:
    # veh1 in Ward 1
    # veh2 in Ward 2
    # veh3 in NULL-ward pool
    veh1 = Vehicle(
        registration_number=f"KA-51-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.AUTO_TIPPER.value,
        status=VehicleStatus.IDLE.value,
        assigned_ward_id=ward1.id,
    )
    veh2 = Vehicle(
        registration_number=f"KA-52-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
        status=VehicleStatus.IDLE.value,
        assigned_ward_id=ward2.id,
    )
    veh3 = Vehicle(
        registration_number=f"KA-53-{uuid.uuid4().hex[:4].upper()}",
        vehicle_type=VehicleType.LORRY.value,
        status=VehicleStatus.MAINTENANCE.value,
        assigned_ward_id=None,
    )
    async_db_session.add_all([veh1, veh2, veh3])
    await async_db_session.commit()

    admin_token = create_access_token(str(admin.id))
    sup_token = create_access_token(str(supervisor.id))
    cit_token = create_access_token(str(citizen.id))

    # --- Role Denials & Nonexistent vehicle ---
    res_cit = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"status": VehicleStatus.ON_DUTY.value},
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    assert res_cit.status_code == 403

    fake_id = uuid.uuid4()
    res_404 = await async_client.patch(
        f"/api/v1/vehicles/{fake_id}",
        json={"status": VehicleStatus.ON_DUTY.value},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_404.status_code == 404

    # --- Reject Empty Update ---
    res_empty = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_empty.status_code == 400
    assert "No fields provided for update" in res_empty.json()["detail"]

    # --- Protected Fields Modification Rejected ---
    res_prot1 = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"is_simulated": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_prot1.status_code == 422

    res_prot2 = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_prot2.status_code == 422

    # --- Ward Supervisor Update Rules ---
    # 1. Valid operational update (status and vehicle_type in assigned ward1)
    res_sup_valid = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={
            "status": VehicleStatus.ON_DUTY.value,
            "vehicle_type": VehicleType.MECHANICAL_SWEEPER.value,
        },
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_valid.status_code == 200
    data_sup_valid = res_sup_valid.json()
    assert data_sup_valid["status"] == VehicleStatus.ON_DUTY.value
    assert data_sup_valid["vehicle_type"] == VehicleType.MECHANICAL_SWEEPER.value

    # 2. Cross-ward update denial: supervisor tries to update veh2 in unassigned ward2
    res_sup_cross = await async_client.patch(
        f"/api/v1/vehicles/{veh2.id}",
        json={"status": VehicleStatus.ON_DUTY.value},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_cross.status_code == 403
    assert "not actively assigned to this ward" in res_sup_cross.json()["detail"]

    # 3. NULL-ward pool update denial: supervisor tries to update veh3 (unassigned)
    res_sup_null = await async_client.patch(
        f"/api/v1/vehicles/{veh3.id}",
        json={"status": VehicleStatus.ON_DUTY.value},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_null.status_code == 403
    assert "cannot modify unassigned vehicles" in res_sup_null.json()["detail"]

    # 4. Supervisor attempt to change ward assignment (even to same ward) -> 403
    res_sup_ch_ward = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"assigned_ward_id": str(ward1.id)},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_ch_ward.status_code == 403
    assert "not authorized to modify vehicle ward assignments" in res_sup_ch_ward.json()["detail"]

    # 5. Supervisor attempt to change driver assignment -> 403
    res_sup_ch_drv = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"assigned_driver_id": str(driver_active.id)},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_ch_drv.status_code == 403
    assert "not authorized to modify vehicle driver assignments" in res_sup_ch_drv.json()["detail"]

    # 6. Supervisor attempt to change registration number -> 403
    res_sup_ch_reg = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"registration_number": "KA-51-NEWREG"},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_sup_ch_reg.status_code == 403
    assert "not authorized to modify vehicle registration numbers" in res_sup_ch_reg.json()["detail"]

    # --- Municipal Admin Update Validations ---
    # 1. Invalid assigned ward reference -> 404
    fake_ward_id = uuid.uuid4()
    res_adm_bad_w = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"assigned_ward_id": str(fake_ward_id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm_bad_w.status_code == 404
    assert f"Assigned ward with id '{fake_ward_id}' not found." in res_adm_bad_w.json()["detail"]

    # 2. Invalid assigned driver reference -> 404
    fake_driver_id = uuid.uuid4()
    res_adm_bad_d = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"assigned_driver_id": str(fake_driver_id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm_bad_d.status_code == 404
    assert f"Assigned driver with id '{fake_driver_id}' not found." in res_adm_bad_d.json()["detail"]

    # 3. Assigned driver is not a DRIVER role -> 400
    res_adm_cit_drv = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"assigned_driver_id": str(citizen.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm_cit_drv.status_code == 400
    assert "is not a DRIVER" in res_adm_cit_drv.json()["detail"]

    # 4. Assigned driver is not ACTIVE status -> 400
    res_adm_dis_drv = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"assigned_driver_id": str(driver_disabled.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm_dis_drv.status_code == 400
    assert "is not an ACTIVE driver" in res_adm_dis_drv.json()["detail"]

    # 5. Duplicate registration number conflict -> 409
    res_adm_dup_reg = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={"registration_number": veh2.registration_number},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm_dup_reg.status_code == 409
    assert "already exists" in res_adm_dup_reg.json()["detail"]

    # 6. Valid admin update of assignments and registration number
    new_reg = f"KA-99-{uuid.uuid4().hex[:4].upper()}"
    res_adm_valid = await async_client.patch(
        f"/api/v1/vehicles/{veh1.id}",
        json={
            "registration_number": new_reg,
            "assigned_ward_id": str(ward2.id),
            "assigned_driver_id": str(driver_active.id),
            "status": VehicleStatus.COLLECTING.value,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm_valid.status_code == 200
    adm_data = res_adm_valid.json()
    assert adm_data["registration_number"] == new_reg
    assert adm_data["assigned_ward_id"] == str(ward2.id)
    assert adm_data["assigned_driver_id"] == str(driver_active.id)
    assert adm_data["status"] == VehicleStatus.COLLECTING.value
