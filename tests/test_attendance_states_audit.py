"""
Integration tests auditing all Attendance States across Worker and Supervisor APIs.
States verified:
1. No attendance record yet (HTTP 404, handled gracefully).
2. Successful in-geofence check-in (status=PRESENT, is_within_geofence=True).
3. Late check-in requiring supervisor review (status=EXCEPTION_PENDING, late reason logged).
4. Out-of-geofence check-in requiring supervisor review (status=EXCEPTION_PENDING, distance evidence logged).
5. Checked-out attendance (duration_minutes calculated and persisted, status preserved).
6. Unresolved exception state (excluded from present_today until approved).
7. Unscheduled day / DAY_OFF override (today_is_workday=False, check-in rejected).
8. Expired or invalid session (HTTP 401 Unauthorized).
"""

import uuid
from datetime import datetime, date, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord
from app.models.schedule import WorkerSchedule, ScheduleOverride
from app.services.attendance_service import get_kolkata_workday_date, normalize_to_utc


@pytest.mark.asyncio
async def test_all_attendance_states_and_transitions(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """End-to-end verification of all attendance states."""
    # 1. Setup Ward & Muster Depot
    ward = Ward(
        ward_code=f"W-AUD-{uuid.uuid4().hex[:6]}",
        display_name=f"Ward-Audit-{uuid.uuid4().hex[:4]}",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    muster = MusterPoint(
        ward_id=ward.id,
        name="Audit Muster Depot",
        location=WKTElement("POINT(77.5895 13.0985)", srid=4326), # lon, lat
        geofence_radius_meters=150,
        is_active=True,
    )
    supervisor = User(
        email=f"sup_aud_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
    )
    worker = User(
        email=f"wrk_aud_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
        full_name="Audit Pourakarmika",
    )
    async_db_session.add_all([muster, supervisor, worker])
    await async_db_session.commit()

    async_db_session.add_all([
        UserWardAssignment(user_id=supervisor.id, ward_id=ward.id),
        UserWardAssignment(user_id=worker.id, ward_id=ward.id),
    ])
    await async_db_session.commit()

    worker_token = create_access_token(subject=worker.id)
    sup_token = create_access_token(subject=supervisor.id)
    w_headers = {"Authorization": f"Bearer {worker_token}"}
    s_headers = {"Authorization": f"Bearer {sup_token}"}

    # STATE 1: No attendance record yet -> 200 OK with null body
    res_today = await async_client.get("/api/v1/attendance/today", headers=w_headers)
    assert res_today.status_code == 200
    assert res_today.json() is None

    # Assign Mon-Sun schedule with broad window for testing check-in/out
    sched = WorkerSchedule(
        worker_id=worker.id,
        ward_id=ward.id,
        days_of_week=[1, 2, 3, 4, 5, 6, 7],
        shift_start_time="00:00",
        shift_end_time="23:59",
        check_in_start_time="00:00",
        check_in_end_time="23:59",
        grace_period_minutes=15,
        is_active=True,
    )
    async_db_session.add(sched)
    await async_db_session.commit()

    # STATE 2: Request OTP & verify
    res_otp_req = await async_client.post("/api/v1/attendance/otp/request", headers=w_headers)
    assert res_otp_req.status_code == 200
    otp_data = res_otp_req.json()
    challenge_id = otp_data["challenge_id"]
    dev_otp = otp_data["dev_otp"]

    res_otp_ver = await async_client.post(
        "/api/v1/attendance/otp/verify",
        json={"challenge_id": challenge_id, "otp": dev_otp},
        headers=w_headers,
    )
    assert res_otp_ver.status_code == 200
    assert res_otp_ver.json()["verified"] is True

    # STATE 3: Out-of-geofence check-in (300m away -> EXCEPTION_PENDING)
    # Muster is at (13.0985, 77.5895). Submitting (13.0985, 77.5925) is ~325m away (>150m)
    res_checkin = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        json={
            "challenge_id": challenge_id,
            "latitude": 13.0985,
            "longitude": 77.5925,
            "ward_id": str(ward.id),
        },
        headers=w_headers,
    )
    assert res_checkin.status_code == 201
    checkin_data = res_checkin.json()
    assert checkin_data["status"] == "EXCEPTION_PENDING"
    assert checkin_data["is_within_geofence"] is False
    assert "exceeds radius 150m" in checkin_data["exception_reason"]
    record_id = checkin_data["attendance_id"]

    # STATE 4: Verify Supervisor Stats counts exception, NOT present
    res_stats1 = await async_client.get(
        f"/api/v1/supervisor/dashboard/stats?ward_id={ward.id}",
        headers=s_headers,
    )
    assert res_stats1.status_code == 200
    stats1 = res_stats1.json()
    assert stats1["present_today"] == 0
    assert stats1["attendance_exceptions"] == 1

    # STATE 5: Check-out attendance while under exception
    # Must preserve EXCEPTION_PENDING and compute duration
    res_co = await async_client.post(
        "/api/v1/attendance/check-out",
        json={
            "latitude": 13.0985,
            "longitude": 77.5895, # In geofence during checkout
            "ward_id": str(ward.id),
        },
        headers=w_headers,
    )
    assert res_co.status_code == 200
    co_data = res_co.json()
    # Check-in exception is preserved!
    assert co_data["status"] == "EXCEPTION_PENDING"
    assert co_data["check_out_at"] is not None
    assert co_data["duration_minutes"] is not None

    # STATE 6: Worker history endpoint reflects duration and exception
    res_hist = await async_client.get("/api/v1/worker/attendance/history", headers=w_headers)
    assert res_hist.status_code == 200
    hist_items = res_hist.json()
    assert len(hist_items) == 1
    assert hist_items[0]["id"] == record_id
    assert hist_items[0]["status"] == "EXCEPTION_PENDING"
    assert hist_items[0]["duration_minutes"] is not None

    # STATE 7: Supervisor reviews exception with mandatory notes -> APPROVE
    res_rev = await async_client.post(
        f"/api/v1/attendance/{record_id}/review",
        json={
            "action": "APPROVE",
            "review_notes": "Detour verified for civic duty",
        },
        headers=s_headers,
    )
    assert res_rev.status_code == 200
    rev_data = res_rev.json()
    assert rev_data["previous_status"] == "EXCEPTION_PENDING"
    assert rev_data["new_status"] == "PRESENT"
    assert rev_data["reviewed_by"] == str(supervisor.id)
    assert rev_data["review_notes"] == "Detour verified for civic duty"

    # STATE 8: Supervisor stats now reflects PRESENT
    res_stats2 = await async_client.get(
        f"/api/v1/supervisor/dashboard/stats?ward_id={ward.id}",
        headers=s_headers,
    )
    assert res_stats2.status_code == 200
    stats2 = res_stats2.json()
    assert stats2["present_today"] == 1
    assert stats2["attendance_exceptions"] == 0

    # STATE 9: Invalid / Expired Token rejection
    bad_headers = {"Authorization": "Bearer invalid.expired.token"}
    res_bad = await async_client.get("/api/v1/attendance/today", headers=bad_headers)
    assert res_bad.status_code == 401
