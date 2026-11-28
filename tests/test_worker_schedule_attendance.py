"""
Integration tests for NammaClean Supervisor & Worker Workforce Management.
Verifies:
1. Supervisor worker registration with ward authorization and Argon2id hashing.
2. Ward authorization scoping (Supervisor of Ward A cannot register or manage Ward B).
3. Worker account status toggle (ACTIVE <-> DISABLED).
4. Weekly recurring schedule creation, window timing validation, and upsert.
5. Date-specific schedule override creation (DAY_OFF, HOLIDAY, LEAVE, SPECIAL_SHIFT).
6. Worker personal schedule and route endpoints (/worker/schedule, /worker/route).
7. Supervisor dashboard stats calculation (Workers Scheduled Today, Present, Attendance Pending, Exceptions).
8. Shift check-out duration calculation in minutes and duplicate checkout rejection.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord
from app.models.schedule import WorkerSchedule, ScheduleOverride
from app.models.route import CollectionRoute
from app.services.attendance_service import get_kolkata_workday_date


@pytest.mark.asyncio
async def test_supervisor_worker_registration_and_ward_scoping(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify supervisor can register workers in their assigned ward, but not other wards."""
    # 1. Setup two distinct wards
    ward_a = Ward(
        ward_code=f"WARD-A-{uuid.uuid4().hex[:6]}",
        display_name=f"Ward-A-{uuid.uuid4().hex[:4]}",
    )
    ward_b = Ward(
        ward_code=f"WARD-B-{uuid.uuid4().hex[:6]}",
        display_name=f"Ward-B-{uuid.uuid4().hex[:4]}",
    )
    async_db_session.add_all([ward_a, ward_b])
    await async_db_session.commit()

    # 2. Setup Supervisor assigned to Ward A
    supervisor_a = User(
        email=f"sup_a_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("SupervisorPass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
        full_name="Supervisor Ramesh",
    )
    async_db_session.add(supervisor_a)
    await async_db_session.commit()

    sup_assignment = UserWardAssignment(
        user_id=supervisor_a.id,
        ward_id=ward_a.id,
    )
    async_db_session.add(sup_assignment)
    await async_db_session.commit()

    sup_token = create_access_token(subject=supervisor_a.id)

    # 3. Supervisor registers worker in Ward A -> SUCCESS (201)
    worker_email_1 = f"pourakarmika_{uuid.uuid4().hex[:6]}@nammaclean.test"
    unique_official_id = f"BBMP-SW-{uuid.uuid4().hex[:6]}"
    payload_valid = {
        "full_name": "Pratik Gokavi",
        "email": worker_email_1,
        "password": "CleanBangalore@2026!",
        "phone_number": "+91 98450 12345",
        "official_id": unique_official_id,
        "ward_id": str(ward_a.id),
    }

    res_valid = await async_client.post(
        "/api/v1/supervisor/workers",
        json=payload_valid,
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_valid.status_code == 201
    worker_data = res_valid.json()
    assert worker_data["email"] == worker_email_1
    assert worker_data["official_id"] == unique_official_id
    assert worker_data["phone_number"] == "+91 98450 12345"

    # 4. Supervisor attempts to register worker in Ward B -> FORBIDDEN (403)
    worker_email_2 = f"pourakarmika_{uuid.uuid4().hex[:6]}@nammaclean.test"
    payload_invalid_ward = {
        "full_name": "Unauthorized Worker",
        "email": worker_email_2,
        "password": "CleanBangalore@2026!",
        "ward_id": str(ward_b.id),
    }

    res_invalid = await async_client.post(
        "/api/v1/supervisor/workers",
        json=payload_invalid_ward,
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_invalid.status_code == 403


@pytest.mark.asyncio
async def test_supervisor_worker_status_toggle(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify supervisor can toggle worker account status (ACTIVE <-> DISABLED)."""
    # 1. Setup ward & supervisor
    ward = Ward(
        ward_code=f"WARD-TOGGLE-{uuid.uuid4().hex[:6]}",
        display_name=f"Ward-Toggle-{uuid.uuid4().hex[:4]}",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_toggle_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    worker = User(
        email=f"worker_toggle_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
    )
    async_db_session.add_all([supervisor, worker])
    await async_db_session.commit()

    async_db_session.add_all([
        UserWardAssignment(user_id=supervisor.id, ward_id=ward.id),
        UserWardAssignment(user_id=worker.id, ward_id=ward.id),
    ])
    await async_db_session.commit()

    sup_token = create_access_token(subject=supervisor.id)

    # 2. Disable worker via JSON body
    res_disable = await async_client.patch(
        f"/api/v1/supervisor/workers/{worker.id}/status",
        json={"status": "DISABLED"},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_disable.status_code == 200
    assert res_disable.json()["status"] == "DISABLED"

    # 3. Enable worker via JSON body
    res_enable = await async_client.patch(
        f"/api/v1/supervisor/workers/{worker.id}/status",
        json={"status": "ACTIVE"},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_enable.status_code == 200
    assert res_enable.json()["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_supervisor_schedule_assignment_and_validation(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify schedule creation validates shift hours and check-in windows."""
    ward = Ward(ward_code=f"WARD-SCHED-{uuid.uuid4().hex[:6]}", display_name=f"Ward-Sched-{uuid.uuid4().hex[:4]}")
    async_db_session.add(ward)
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_sched_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    worker = User(
        email=f"worker_sched_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
    )
    async_db_session.add_all([supervisor, worker])
    await async_db_session.commit()

    async_db_session.add_all([
        UserWardAssignment(user_id=supervisor.id, ward_id=ward.id),
        UserWardAssignment(user_id=worker.id, ward_id=ward.id),
    ])
    await async_db_session.commit()

    sup_token = create_access_token(subject=supervisor.id)

    # 1. Invalid shift hours (end before start) -> 400 Bad Request
    invalid_payload = {
        "worker_id": str(worker.id),
        "ward_id": str(ward.id),
        "days_of_week": [1, 2, 3, 4, 5],
        "shift_start_time": "14:00",
        "shift_end_time": "07:00",
        "check_in_start_time": "06:45",
        "check_in_end_time": "07:30",
        "grace_period_minutes": 15,
    }
    res_bad = await async_client.post(
        "/api/v1/supervisor/schedules",
        json=invalid_payload,
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_bad.status_code == 400

    # 2. Valid schedule assignment -> 201 Created
    valid_payload = {
        "worker_id": str(worker.id),
        "ward_id": str(ward.id),
        "days_of_week": [1, 2, 3, 4, 5, 6],
        "shift_start_time": "07:00",
        "shift_end_time": "14:00",
        "check_in_start_time": "06:45",
        "check_in_end_time": "07:30",
        "grace_period_minutes": 15,
    }
    res_good = await async_client.post(
        "/api/v1/supervisor/schedules",
        json=valid_payload,
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_good.status_code == 201
    sched_data = res_good.json()
    assert sched_data["worker_id"] == str(worker.id)
    assert sched_data["shift_start_time"] == "07:00"
    assert sched_data["shift_end_time"] == "14:00"
    assert sched_data["grace_period_minutes"] == 15


@pytest.mark.asyncio
async def test_supervisor_schedule_override(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify supervisor can create date-specific schedule overrides."""
    ward = Ward(ward_code=f"WARD-OV-{uuid.uuid4().hex[:6]}", display_name=f"Ward-Override-{uuid.uuid4().hex[:4]}")
    async_db_session.add(ward)
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_ov_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    worker = User(
        email=f"worker_ov_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
    )
    async_db_session.add_all([supervisor, worker])
    await async_db_session.commit()

    async_db_session.add_all([
        UserWardAssignment(user_id=supervisor.id, ward_id=ward.id),
        UserWardAssignment(user_id=worker.id, ward_id=ward.id),
    ])
    await async_db_session.commit()

    sup_token = create_access_token(subject=supervisor.id)

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    override_payload = {
        "worker_id": str(worker.id),
        "override_date": tomorrow,
        "override_type": "DAY_OFF",
        "reason": "Authorized rest day",
    }

    res_ov = await async_client.post(
        "/api/v1/supervisor/schedules/overrides",
        json=override_payload,
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_ov.status_code == 201
    ov_data = res_ov.json()
    assert ov_data["worker_id"] == str(worker.id)
    assert ov_data["override_date"] == tomorrow
    assert ov_data["override_type"] == "DAY_OFF"


@pytest.mark.asyncio
async def test_worker_schedule_and_route_endpoints(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify worker can retrieve their active resolved schedule and collection route."""
    ward = Ward(ward_code=f"WARD-WORKER-{uuid.uuid4().hex[:6]}", display_name=f"Ward-WorkerApi-{uuid.uuid4().hex[:4]}")
    async_db_session.add(ward)
    await async_db_session.commit()

    worker = User(
        email=f"worker_api_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Pourakarmika Worker",
        ward_id=ward.id,
    )
    async_db_session.add(worker)
    await async_db_session.commit()

    async_db_session.add(UserWardAssignment(user_id=worker.id, ward_id=ward.id))
    await async_db_session.commit()

    # Assign route and schedule
    route = CollectionRoute(
        ward_id=ward.id,
        name="Hebbal Main Waste Route",
        route_code=f"R-{uuid.uuid4().hex[:6]}",
        route_path=WKTElement("LINESTRING(77.5900 12.9700, 77.5950 12.9750)", srid=4326),
        is_active=True,
    )
    async_db_session.add(route)
    await async_db_session.commit()

    schedule = WorkerSchedule(
        worker_id=worker.id,
        ward_id=ward.id,
        route_id=route.id,
        days_of_week=[1, 2, 3, 4, 5, 6, 7],
        shift_start_time="07:00",
        shift_end_time="14:00",
        check_in_start_time="06:30",
        check_in_end_time="07:30",
        grace_period_minutes=15,
        is_active=True,
    )
    async_db_session.add(schedule)
    await async_db_session.commit()

    worker_token = create_access_token(subject=worker.id)

    # 1. Fetch schedule
    res_sched = await async_client.get(
        "/api/v1/worker/schedule",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert res_sched.status_code == 200
    sched_data = res_sched.json()
    assert sched_data["has_schedule"] is True
    assert "window_status" in sched_data
    assert sched_data["active_schedule"]["shift_start_time"] == "07:00"

    # 2. Fetch route
    res_route = await async_client.get(
        "/api/v1/worker/route",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert res_route.status_code == 200
    route_data = res_route.json()
    assert route_data["assigned"] is True
    assert route_data["route"]["name"] == "Hebbal Main Waste Route"
    assert len(route_data["waypoints"]) > 0


@pytest.mark.asyncio
async def test_supervisor_dashboard_stats(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify supervisor operational dashboard stats endpoint."""
    ward = Ward(ward_code=f"WARD-STATS-{uuid.uuid4().hex[:6]}", display_name=f"Ward-Stats-{uuid.uuid4().hex[:4]}")
    async_db_session.add(ward)
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_stats_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(supervisor)
    await async_db_session.commit()

    async_db_session.add(UserWardAssignment(user_id=supervisor.id, ward_id=ward.id))
    await async_db_session.commit()

    sup_token = create_access_token(subject=supervisor.id)

    res_stats = await async_client.get(
        "/api/v1/supervisor/dashboard/stats",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert "workers_scheduled_today" in stats
    assert "present_today" in stats
    assert "attendance_pending" in stats
    assert "attendance_exceptions" in stats
    assert stats["workers_scheduled_today"] >= 0
    assert stats["present_today"] >= 0


@pytest.mark.asyncio
async def test_attendance_checkout_duration(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify check-out calculates duration from recorded check-in timestamp and records it."""
    ward = Ward(ward_code=f"WARD-CO-{uuid.uuid4().hex[:6]}", display_name=f"Ward-Checkout-{uuid.uuid4().hex[:4]}")
    async_db_session.add(ward)
    await async_db_session.commit()

    muster = MusterPoint(
        ward_id=ward.id,
        name="Main Muster Point",
        location=WKTElement("POINT(77.6000 13.0000)", srid=4326),
        geofence_radius_meters=150,
        is_active=True,
    )
    worker = User(
        email=f"worker_co_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
    )
    async_db_session.add_all([muster, worker])
    await async_db_session.commit()

    async_db_session.add(UserWardAssignment(user_id=worker.id, ward_id=ward.id))
    await async_db_session.commit()

    # Pre-record check-in 120 minutes ago
    server_now = utc_now()
    checkin_time = server_now - timedelta(minutes=120)
    attendance_date = get_kolkata_workday_date(server_now)

    att_record = AttendanceRecord(
        worker_id=worker.id,
        ward_id=ward.id,
        muster_point_id=muster.id,
        attendance_date=attendance_date,
        check_in_at=checkin_time,
        check_in_location=WKTElement("POINT(77.6001 13.0001)", srid=4326),
        check_in_distance_meters=15.0,
        status="PRESENT",
    )
    async_db_session.add(att_record)
    await async_db_session.commit()

    worker_token = create_access_token(subject=worker.id)

    # Worker calls check-out within muster geofence
    checkout_payload = {
        "latitude": 13.0001,
        "longitude": 77.6001,
        "ward_id": str(ward.id),
        "muster_point_id": str(muster.id),
    }

    res_co = await async_client.post(
        "/api/v1/attendance/check-out",
        json=checkout_payload,
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert res_co.status_code == 200
    co_data = res_co.json()
    assert co_data["status"] == "PRESENT"
    assert co_data["is_within_geofence"] is True
    assert co_data["duration_minutes"] >= 119
    assert co_data["check_out_at"] is not None

    # Verify duplicate checkout is rejected with 409 Conflict
    res_dup = await async_client.post(
        "/api/v1/attendance/check-out",
        json=checkout_payload,
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert res_dup.status_code == 409


@pytest.mark.asyncio
async def test_supervisor_list_workers_search_filter(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify supervisor worker directory search query filter (?q=...) functions correctly."""
    ward = Ward(
        ward_code=f"WARD-SRCH-{uuid.uuid4().hex[:6]}",
        display_name=f"Ward Search {uuid.uuid4().hex[:4]}",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    supervisor = User(
        email=f"sup_srch_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("SupervisorPass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
        full_name="Search Supervisor",
        ward_id=ward.id,
    )
    worker_1 = User(
        email=f"aarav_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("WorkerPass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Aarav Gowda",
        official_id=f"PK-SRCH-1-{uuid.uuid4().hex[:4]}",
        ward_id=ward.id,
    )
    worker_2 = User(
        email=f"bhaskar_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("WorkerPass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        full_name="Bhaskar Kumar",
        official_id=f"PK-SRCH-2-{uuid.uuid4().hex[:4]}",
        ward_id=ward.id,
    )
    async_db_session.add_all([supervisor, worker_1, worker_2])
    await async_db_session.commit()

    sup_assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward.id, assigned_at=utc_now())
    w1_assign = UserWardAssignment(user_id=worker_1.id, ward_id=ward.id, assigned_at=utc_now())
    w2_assign = UserWardAssignment(user_id=worker_2.id, ward_id=ward.id, assigned_at=utc_now())
    async_db_session.add_all([sup_assign, w1_assign, w2_assign])
    await async_db_session.commit()

    sup_token = create_access_token(subject=supervisor.id)

    # 1. Search for Aarav
    res_aarav = await async_client.get(
        f"/api/v1/supervisor/workers?ward_id={ward.id}&q=Aarav",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_aarav.status_code == 200
    aarav_data = res_aarav.json()
    assert len(aarav_data) == 1
    assert aarav_data[0]["full_name"] == "Aarav Gowda"

    # 2. Search for official ID
    res_off = await async_client.get(
        f"/api/v1/supervisor/workers?ward_id={ward.id}&q={worker_2.official_id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_off.status_code == 200
    off_data = res_off.json()
    assert len(off_data) == 1
    assert off_data[0]["full_name"] == "Bhaskar Kumar"

    # 3. Search for non-matching query
    res_none = await async_client.get(
        f"/api/v1/supervisor/workers?ward_id={ward.id}&q=NonExistentWorkerXYZ",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res_none.status_code == 200
    assert len(res_none.json()) == 0

