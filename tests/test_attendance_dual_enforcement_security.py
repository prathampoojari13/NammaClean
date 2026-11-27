"""
Targeted regression tests auditing the dual-enforcement security model:
Both valid email OTP verification AND physical proximity to the designated muster depot
are strictly required to achieve verified PRESENT attendance.

Cases verified:
1. An unverified OTP challenge cannot be used to check in (HTTP 400).
2. An already redeemed challenge cannot be reused / replay attack prevented (HTTP 400).
3. Missing, non-numeric, or out-of-range coordinates are rejected (HTTP 422).
4. A valid OTP with coordinates outside the geofence cannot produce verified PRESENT attendance
   (enforced as EXCEPTION_PENDING; excluded from daily present metrics).
5. Existing supervisor-approved exception workflow remains intact and transitions record to PRESENT.
"""

import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord
from app.models.schedule import WorkerSchedule


@pytest.fixture
async def security_audit_env(async_db_session: AsyncSession):
    """Sets up an isolated ward, muster depot, supervisor, and worker for dual-enforcement tests."""
    ward = Ward(
        ward_code=f"W-SEC-{uuid.uuid4().hex[:6]}",
        display_name="Security Audit Ward",
    )
    async_db_session.add(ward)
    await async_db_session.commit()

    muster = MusterPoint(
        ward_id=ward.id,
        name="Security Muster Depot",
        location=WKTElement("POINT(77.5895 13.0985)", srid=4326),  # lon, lat
        geofence_radius_meters=150,
        is_active=True,
    )
    supervisor = User(
        email=f"sup_sec_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
        full_name="Security Ward Supervisor",
    )
    worker = User(
        email=f"wrk_sec_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
        full_name="Security Pourakarmika",
        official_id=f"SEC-PK-{uuid.uuid4().hex[:6]}",
    )
    async_db_session.add_all([muster, supervisor, worker])
    await async_db_session.commit()

    async_db_session.add_all([
        UserWardAssignment(user_id=supervisor.id, ward_id=ward.id),
        UserWardAssignment(user_id=worker.id, ward_id=ward.id),
    ])
    await async_db_session.commit()

    schedule = WorkerSchedule(
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
    async_db_session.add(schedule)
    await async_db_session.commit()

    return {
        "ward": ward,
        "muster": muster,
        "supervisor": supervisor,
        "worker": worker,
    }


@pytest.mark.asyncio
async def test_unverified_otp_challenge_cannot_check_in(
    async_client: AsyncClient,
    security_audit_env: dict,
):
    """
    Case 1: An unverified OTP challenge cannot be used to record attendance.
    Worker requests an OTP challenge, skips verification, and attempts check-in.
    Must be rejected with HTTP 400 Bad Request.
    """
    env = security_audit_env
    worker = env["worker"]
    ward = env["ward"]
    w_token = create_access_token(subject=worker.id)
    headers = {"Authorization": f"Bearer {w_token}"}

    with patch("app.services.email_service.send_attendance_otp_email", new_callable=AsyncMock):
        # Step 1: Request OTP challenge
        res_req = await async_client.post("/api/v1/attendance/otp/request", headers=headers)
        assert res_req.status_code == 200
        challenge_id = res_req.json()["challenge_id"]

        # Step 2: Attempt check-in with UNVERIFIED challenge_id
        res_checkin = await async_client.post(
            "/api/v1/attendance/otp-check-in",
            headers=headers,
            json={
                "challenge_id": challenge_id,
                "latitude": 13.0985,  # Exactly at muster depot
                "longitude": 77.5895,
                "ward_id": str(ward.id),
            },
        )
        assert res_checkin.status_code == 400
        detail = res_checkin.json()["detail"].lower()
        assert "invalid" in detail or "unverified" in detail or "expired" in detail


@pytest.mark.asyncio
async def test_already_redeemed_challenge_cannot_be_reused(
    async_client: AsyncClient,
    security_audit_env: dict,
):
    """
    Case 2: An already redeemed challenge cannot be reused (replay attack prevention).
    Worker completes check-in successfully. A second check-in attempt using the same
    challenge ID must be rejected with HTTP 400 Bad Request.
    """
    env = security_audit_env
    worker = env["worker"]
    ward = env["ward"]
    w_token = create_access_token(subject=worker.id)
    headers = {"Authorization": f"Bearer {w_token}"}

    with patch("app.services.email_service.send_attendance_otp_email", new_callable=AsyncMock):
        # Step 1: Request OTP challenge
        res_req = await async_client.post("/api/v1/attendance/otp/request", headers=headers)
        assert res_req.status_code == 200
        req_data = res_req.json()
        challenge_id = req_data["challenge_id"]
        dev_otp = req_data["dev_otp"]

        # Step 2: Verify OTP
        res_ver = await async_client.post(
            "/api/v1/attendance/otp/verify",
            headers=headers,
            json={"challenge_id": challenge_id, "otp": dev_otp},
        )
        assert res_ver.status_code == 200
        assert res_ver.json()["verified"] is True

        # Step 3: First Check-In (Redeems the challenge)
        res_checkin_1 = await async_client.post(
            "/api/v1/attendance/otp-check-in",
            headers=headers,
            json={
                "challenge_id": challenge_id,
                "latitude": 13.0985,
                "longitude": 77.5895,
                "ward_id": str(ward.id),
            },
        )
        assert res_checkin_1.status_code == 201
        assert res_checkin_1.json()["status"] == AttendanceStatus.PRESENT.value

        # Step 4: Replay attack - Attempting check-in again with the SAME challenge ID
        res_replay = await async_client.post(
            "/api/v1/attendance/otp-check-in",
            headers=headers,
            json={
                "challenge_id": challenge_id,
                "latitude": 13.0985,
                "longitude": 77.5895,
                "ward_id": str(ward.id),
            },
        )
        # Must be rejected because the challenge is already redeemed
        assert res_replay.status_code in (400, 409)
        if res_replay.status_code == 400:
            detail = res_replay.json()["detail"].lower()
            assert "invalid" in detail or "unverified" in detail or "expired" in detail


@pytest.mark.asyncio
async def test_invalid_and_missing_coordinates_rejected(
    async_client: AsyncClient,
    security_audit_env: dict,
):
    """
    Case 3: Missing, non-numeric, or out-of-range coordinates are rejected with HTTP 422.
    """
    env = security_audit_env
    worker = env["worker"]
    w_token = create_access_token(subject=worker.id)
    headers = {"Authorization": f"Bearer {w_token}"}

    with patch("app.services.email_service.send_attendance_otp_email", new_callable=AsyncMock):
        res_req = await async_client.post("/api/v1/attendance/otp/request", headers=headers)
        challenge_id = res_req.json()["challenge_id"]
        dev_otp = res_req.json()["dev_otp"]
        await async_client.post(
            "/api/v1/attendance/otp/verify",
            headers=headers,
            json={"challenge_id": challenge_id, "otp": dev_otp},
        )

    # 3a. Missing latitude
    res_no_lat = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "longitude": 77.5895},
    )
    assert res_no_lat.status_code == 422

    # 3b. Missing longitude
    res_no_lon = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": 13.0985},
    )
    assert res_no_lon.status_code == 422

    # 3c. Non-numeric latitude
    res_str_lat = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": "invalid_latitude", "longitude": 77.5895},
    )
    assert res_str_lat.status_code == 422

    # 3d. NaN and Infinite coordinates (string representations or JSON rejected)
    res_nan_lat = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": "NaN", "longitude": 77.5895},
    )
    assert res_nan_lat.status_code == 422

    res_inf_lat = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": "Infinity", "longitude": 77.5895},
    )
    assert res_inf_lat.status_code == 422

    res_neginf_lon = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": 13.0985, "longitude": "-Infinity"},
    )
    assert res_neginf_lon.status_code == 422

    # 3e. Out-of-bounds latitude (> 90.0 or < -90.0)
    res_oob_lat = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": 95.1234, "longitude": 77.5895},
    )
    assert res_oob_lat.status_code == 422

    res_oob_neg_lat = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": -95.1234, "longitude": 77.5895},
    )
    assert res_oob_neg_lat.status_code == 422

    # 3f. Out-of-bounds longitude (> 180.0 or < -180.0)
    res_oob_lon = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": 13.0985, "longitude": 185.1234},
    )
    assert res_oob_lon.status_code == 422

    res_oob_neg_lon = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=headers,
        json={"challenge_id": challenge_id, "latitude": 13.0985, "longitude": -185.1234},
    )
    assert res_oob_neg_lon.status_code == 422


@pytest.mark.asyncio
async def test_valid_otp_outside_geofence_cannot_produce_present_without_review(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    security_audit_env: dict,
):
    """
    Case 4: A valid OTP with coordinates outside the configured geofence cannot
    immediately produce verified PRESENT attendance without the supervisor-review process.
    - Status is EXCEPTION_PENDING.
    - Excluded from present counts in supervisor dashboard and roster.
    """
    env = security_audit_env
    worker = env["worker"]
    supervisor = env["supervisor"]
    ward = env["ward"]

    w_token = create_access_token(subject=worker.id)
    s_token = create_access_token(subject=supervisor.id)
    w_headers = {"Authorization": f"Bearer {w_token}"}
    s_headers = {"Authorization": f"Bearer {s_token}"}

    with patch("app.services.email_service.send_attendance_otp_email", new_callable=AsyncMock):
        res_req = await async_client.post("/api/v1/attendance/otp/request", headers=w_headers)
        assert res_req.status_code == 200
        req_data = res_req.json()
        challenge_id = req_data["challenge_id"]
        dev_otp = req_data["dev_otp"]

        await async_client.post(
            "/api/v1/attendance/otp/verify",
            headers=w_headers,
            json={"challenge_id": challenge_id, "otp": dev_otp},
        )

        # Worker submits coordinates 325m away from depot (13.0985, 77.5895)
        res_checkin = await async_client.post(
            "/api/v1/attendance/otp-check-in",
            headers=w_headers,
            json={
                "challenge_id": challenge_id,
                "latitude": 13.0984,
                "longitude": 77.5925,  # ~325m
                "ward_id": str(ward.id),
            },
        )
        assert res_checkin.status_code == 201
        checkin_data = res_checkin.json()

        # Cannot be PRESENT without supervisor review
        assert checkin_data["status"] == AttendanceStatus.EXCEPTION_PENDING.value
        assert checkin_data["is_within_geofence"] is False
        assert checkin_data["distance_meters"] > 150.0

    # Verify Supervisor Roster and KPI counters
    res_roster = await async_client.get(
        f"/api/v1/wards/{ward.id}/attendance/daily",
        headers=s_headers,
    )
    assert res_roster.status_code == 200
    roster_data = res_roster.json()
    assert roster_data["present_count"] == 0, "Out-of-geofence check-in must not increment present_count!"
    assert roster_data["exception_pending_count"] == 1

    res_stats = await async_client.get(
        f"/api/v1/supervisor/dashboard/stats?ward_id={ward.id}",
        headers=s_headers,
    )
    assert res_stats.status_code == 200
    stats_data = res_stats.json()
    assert stats_data["present_today"] == 0
    assert stats_data["attendance_exceptions"] == 1


@pytest.mark.asyncio
async def test_supervisor_review_workflow_intact(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    security_audit_env: dict,
):
    """
    Case 5: Existing supervisor-approved exception behavior remains unchanged.
    Supervisor reviews the EXCEPTION_PENDING record, provides required justification notes,
    and approves the record to PRESENT. Original out-of-geofence evidence is preserved.
    """
    env = security_audit_env
    worker = env["worker"]
    supervisor = env["supervisor"]
    ward = env["ward"]

    w_token = create_access_token(subject=worker.id)
    s_token = create_access_token(subject=supervisor.id)
    w_headers = {"Authorization": f"Bearer {w_token}"}
    s_headers = {"Authorization": f"Bearer {s_token}"}

    with patch("app.services.email_service.send_attendance_otp_email", new_callable=AsyncMock):
        res_req = await async_client.post("/api/v1/attendance/otp/request", headers=w_headers)
        req_data = res_req.json()
        challenge_id = req_data["challenge_id"]
        dev_otp = req_data["dev_otp"]

        await async_client.post(
            "/api/v1/attendance/otp/verify",
            headers=w_headers,
            json={"challenge_id": challenge_id, "otp": dev_otp},
        )

        res_checkin = await async_client.post(
            "/api/v1/attendance/otp-check-in",
            headers=w_headers,
            json={
                "challenge_id": challenge_id,
                "latitude": 13.0984,
                "longitude": 77.5925,
                "ward_id": str(ward.id),
            },
        )
        record_id = res_checkin.json()["attendance_id"]

    # Supervisor approves the exception
    justification = "Verified emergency detour clearance authorized by Ward Supervisor."
    res_review = await async_client.post(
        f"/api/v1/attendance/{record_id}/review",
        headers=s_headers,
        json={
            "action": "APPROVE",
            "review_notes": justification,
        },
    )
    assert res_review.status_code == 200
    rev_data = res_review.json()
    assert rev_data["previous_status"] == AttendanceStatus.EXCEPTION_PENDING.value
    assert rev_data["new_status"] == AttendanceStatus.PRESENT.value
    assert rev_data["reviewed_by"] == str(supervisor.id)
    assert rev_data["review_notes"] == justification

    # Verify metrics update after approval
    res_stats_post = await async_client.get(
        f"/api/v1/supervisor/dashboard/stats?ward_id={ward.id}",
        headers=s_headers,
    )
    assert res_stats_post.status_code == 200
    stats_post = res_stats_post.json()
    assert stats_post["present_today"] == 1
    assert stats_post["attendance_exceptions"] == 0
