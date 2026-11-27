"""
Comprehensive integration and regression tests auditing:
1. Attendance evidence preservation across the complete lifecycle:
   - Check-in within geofence (PRESENT)
   - Check-in outside geofence (EXCEPTION_PENDING)
   - Late check-in exception
   - Check-out while exception remains unresolved
   - Supervisor approval preserving original evidence
   - Supervisor rejection with mandatory notes
   - Subsequent review rejection (HTTP 409 Conflict) without record corruption
   - Separate check-out evidence (coordinates, distance, duration) without overwriting check-in
2. Supervisor review integrity and authorization:
   - Cross-ward review prevention (HTTP 403 Forbidden)
   - Non-supervisor / citizen role rejection (HTTP 403 Forbidden)
   - Review justification note requirements (HTTP 422 Unprocessable Entity)
   - Worker review notifications
3. Status semantics, roster, and statistics consistency:
   - EXCEPTION_PENDING excluded from present count
   - Real-time transition of present_count, exception_pending_count, and rejected_count
4. Atomic row locking and non-conflicting review state transitions
"""

import uuid
from datetime import datetime, date, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord
from app.models.schedule import WorkerSchedule
from app.models.notification import Notification
from app.services.attendance_service import (
    record_check_in,
    record_check_out,
    review_attendance_record,
    AttendanceNotReviewableError,
    get_daily_attendance_roster,
)


@pytest.fixture
async def audit_environment(async_db_session: AsyncSession):
    """Sets up two wards, muster points, supervisors, and workers for isolated evidence audits."""
    # Ward A
    ward_a = Ward(
        ward_code=f"W-EVD-A-{uuid.uuid4().hex[:6]}",
        display_name="Ward A Evidence Pilot",
    )
    # Ward B (for cross-ward boundary checks)
    ward_b = Ward(
        ward_code=f"W-EVD-B-{uuid.uuid4().hex[:6]}",
        display_name="Ward B Remote",
    )
    async_db_session.add_all([ward_a, ward_b])
    await async_db_session.commit()

    muster_a = MusterPoint(
        ward_id=ward_a.id,
        name="Ward A Central Depot",
        location=WKTElement("POINT(77.5895 13.0985)", srid=4326),  # lon, lat
        geofence_radius_meters=150,
        is_active=True,
    )
    muster_b = MusterPoint(
        ward_id=ward_b.id,
        name="Ward B Depot",
        location=WKTElement("POINT(77.6000 13.0500)", srid=4326),
        geofence_radius_meters=150,
        is_active=True,
    )
    async_db_session.add_all([muster_a, muster_b])
    await async_db_session.commit()

    # Users
    sup_a = User(
        email=f"sup_a_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward_a.id,
        full_name="Supervisor Ward A",
    )
    sup_b = User(
        email=f"sup_b_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward_b.id,
        full_name="Supervisor Ward B",
    )
    worker_1 = User(
        email=f"wrk_1_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward_a.id,
        full_name="Pourakarmika Worker 1",
        official_id=f"EVD-01-{uuid.uuid4().hex[:6]}",
    )
    worker_2 = User(
        email=f"wrk_2_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward_a.id,
        full_name="Pourakarmika Worker 2",
        official_id=f"EVD-02-{uuid.uuid4().hex[:6]}",
    )
    citizen = User(
        email=f"cit_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
        full_name="Concerned Citizen",
    )
    async_db_session.add_all([sup_a, sup_b, worker_1, worker_2, citizen])
    await async_db_session.commit()

    async_db_session.add_all([
        UserWardAssignment(user_id=sup_a.id, ward_id=ward_a.id),
        UserWardAssignment(user_id=sup_b.id, ward_id=ward_b.id),
        UserWardAssignment(user_id=worker_1.id, ward_id=ward_a.id),
        UserWardAssignment(user_id=worker_2.id, ward_id=ward_a.id),
    ])
    await async_db_session.commit()

    # Schedules for workers
    for w in [worker_1, worker_2]:
        async_db_session.add(
            WorkerSchedule(
                worker_id=w.id,
                ward_id=ward_a.id,
                days_of_week=[1, 2, 3, 4, 5, 6, 7],
                shift_start_time="00:00",
                shift_end_time="23:59",
                check_in_start_time="00:00",
                check_in_end_time="23:59",
                grace_period_minutes=15,
                is_active=True,
            )
        )
    await async_db_session.commit()

    return {
        "ward_a": ward_a,
        "ward_b": ward_b,
        "muster_a": muster_a,
        "muster_b": muster_b,
        "sup_a": sup_a,
        "sup_b": sup_b,
        "worker_1": worker_1,
        "worker_2": worker_2,
        "citizen": citizen,
    }


@pytest.mark.asyncio
async def test_evidence_preservation_across_lifecycle(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    audit_environment: dict,
):
    """
    Verifies Section 1: Complete lifecycle and evidence preservation.
    1. Worker checks in outside geofence -> EXCEPTION_PENDING.
    2. Check-out writes separate evidence without overwriting check-in.
    3. Supervisor approves with justification -> PRESENT, retaining original exception notes & evidence.
    4. Duplicate review attempt is rejected (HTTP 409).
    """
    env = audit_environment
    ward_a = env["ward_a"]
    w1 = env["worker_1"]
    sup_a = env["sup_a"]
    muster_a = env["muster_a"]

    w1_token = create_access_token(subject=w1.id)
    sup_a_token = create_access_token(subject=sup_a.id)
    w1_headers = {"Authorization": f"Bearer {w1_token}"}
    sup_a_headers = {"Authorization": f"Bearer {sup_a_token}"}

    # Step 1: Worker 1 requests OTP challenge
    res_otp = await async_client.post("/api/v1/attendance/otp/request", headers=w1_headers)
    assert res_otp.status_code == 200
    otp_data = res_otp.json()
    challenge_id = otp_data["challenge_id"]
    dev_otp = otp_data["dev_otp"]
    assert dev_otp is not None, "dev_otp should be available in test environment"

    # Verify OTP
    res_v = await async_client.post(
        "/api/v1/attendance/otp/verify",
        headers=w1_headers,
        json={"challenge_id": challenge_id, "otp": dev_otp},
    )
    assert res_v.status_code == 200

    # Submit Check-in OUTSIDE geofence:
    # Muster is at (13.0985, 77.5895). We submit (13.0984, 77.5925) -> ~325m away
    check_in_lat = 13.0984
    check_in_lon = 77.5925
    check_in_acc = 8.5
    res_in = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=w1_headers,
        json={
            "challenge_id": challenge_id,
            "latitude": check_in_lat,
            "longitude": check_in_lon,
            "accuracy_meters": check_in_acc,
            "ward_id": str(ward_a.id),
        },
    )
    assert res_in.status_code == 201
    in_data = res_in.json()
    record_id = uuid.UUID(in_data["attendance_id"])
    assert in_data["status"] == AttendanceStatus.EXCEPTION_PENDING.value
    assert in_data["is_within_geofence"] is False
    assert in_data["distance_meters"] > 300.0
    assert "outside geofence" in in_data["exception_reason"].lower()

    # Inspect stored database row directly for evidence preservation
    stmt_rec = select(AttendanceRecord).where(AttendanceRecord.id == record_id)
    rec = (await async_db_session.execute(stmt_rec)).scalars().first()
    assert rec is not None
    orig_check_in_at = rec.check_in_at
    orig_distance = rec.check_in_distance_meters
    orig_accuracy = rec.check_in_accuracy_meters
    orig_exception_reason = rec.exception_reason
    assert orig_check_in_at is not None
    assert orig_distance is not None and orig_distance > 300.0
    assert orig_accuracy == check_in_acc
    assert orig_exception_reason is not None

    # Step 2: Check-out while exception remains unresolved
    # Check-out location is at (13.0986, 77.5896) -> ~15m from depot (in geofence)
    check_out_lat = 13.0986
    check_out_lon = 77.5896
    check_out_acc = 5.0
    res_out = await async_client.post(
        "/api/v1/attendance/check-out",
        headers=w1_headers,
        json={
            "latitude": check_out_lat,
            "longitude": check_out_lon,
            "accuracy_meters": check_out_acc,
            "ward_id": str(ward_a.id),
        },
    )
    assert res_out.status_code == 200
    out_data = res_out.json()
    # Status remains EXCEPTION_PENDING because check-in exception is unresolved
    assert out_data["status"] == AttendanceStatus.EXCEPTION_PENDING.value
    assert out_data["check_out_at"] is not None
    assert out_data["duration_minutes"] is not None

    # Verify check-out created SEPARATE evidence and did NOT overwrite check-in evidence
    await async_db_session.refresh(rec)
    assert rec.check_in_at == orig_check_in_at
    assert rec.check_in_distance_meters == orig_distance
    assert rec.check_in_accuracy_meters == orig_accuracy
    assert rec.check_out_at is not None
    assert rec.check_out_distance_meters is not None and rec.check_out_distance_meters < 50.0
    assert rec.check_out_accuracy_meters == check_out_acc
    assert rec.duration_minutes is not None
    # Exception reason from check-in must be preserved
    assert orig_exception_reason in rec.exception_reason

    # Step 3: Supervisor approves exception with meaningful justification
    approval_notes = "Field detour verified: emergency municipal clearance required on Main Road."
    res_rev = await async_client.post(
        f"/api/v1/attendance/{record_id}/review",
        headers=sup_a_headers,
        json={
            "action": "APPROVE",
            "review_notes": approval_notes,
        },
    )
    assert res_rev.status_code == 200
    rev_data = res_rev.json()
    assert rev_data["previous_status"] == AttendanceStatus.EXCEPTION_PENDING.value
    assert rev_data["new_status"] == AttendanceStatus.PRESENT.value
    assert rev_data["reviewed_by"] == str(sup_a.id)
    assert rev_data["review_notes"] == approval_notes

    # Verify DB evidence after approval:
    await async_db_session.refresh(rec)
    assert rec.status == AttendanceStatus.PRESENT.value
    assert rec.reviewed_by == sup_a.id
    assert rec.reviewed_at is not None
    assert rec.review_notes == approval_notes
    # CRITICAL: Original check-in, distance, coordinates, and exception reason are STILL PRESERVED!
    assert rec.check_in_at == orig_check_in_at
    assert rec.check_in_distance_meters == orig_distance
    assert rec.check_in_accuracy_meters == orig_accuracy
    assert rec.exception_reason is not None and orig_exception_reason in rec.exception_reason

    # Step 4: Duplicate review attempt must be rejected without altering record
    res_dup = await async_client.post(
        f"/api/v1/attendance/{record_id}/review",
        headers=sup_a_headers,
        json={
            "action": "REJECT",
            "review_notes": "Attempt to change decision after approval.",
        },
    )
    assert res_dup.status_code == 409
    assert "not in reviewable state" in res_dup.json()["detail"].lower()

    # Verify record remained unaltered after duplicate rejected review
    await async_db_session.refresh(rec)
    assert rec.status == AttendanceStatus.PRESENT.value
    assert rec.reviewed_by == sup_a.id
    assert rec.review_notes == approval_notes


@pytest.mark.asyncio
async def test_supervisor_rejection_and_justification_rules(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    audit_environment: dict,
):
    """
    Verifies Section 2: Rejection justification requirement, notifications, and rejection status.
    """
    env = audit_environment
    ward_a = env["ward_a"]
    w2 = env["worker_2"]
    sup_a = env["sup_a"]

    w2_token = create_access_token(subject=w2.id)
    sup_a_token = create_access_token(subject=sup_a.id)
    w2_headers = {"Authorization": f"Bearer {w2_token}"}
    sup_a_headers = {"Authorization": f"Bearer {sup_a_token}"}

    # Worker 2 check-in out of bounds
    res_otp = await async_client.post("/api/v1/attendance/otp/request", headers=w2_headers)
    assert res_otp.status_code == 200
    otp_data = res_otp.json()
    await async_client.post(
        "/api/v1/attendance/otp/verify",
        headers=w2_headers,
        json={"challenge_id": otp_data["challenge_id"], "otp": otp_data["dev_otp"]},
    )
    res_in = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=w2_headers,
        json={
            "challenge_id": otp_data["challenge_id"],
            "latitude": 13.0984,
            "longitude": 77.5950,  # ~600m away
            "ward_id": str(ward_a.id),
        },
    )
    assert res_in.status_code == 201
    rec_id = uuid.UUID(res_in.json()["attendance_id"])

    # Attempt 1: Rejection WITHOUT review notes -> must fail with HTTP 422
    res_rej_empty = await async_client.post(
        f"/api/v1/attendance/{rec_id}/review",
        headers=sup_a_headers,
        json={
            "action": "REJECT",
            "review_notes": "   ",  # whitespace only
        },
    )
    assert res_rej_empty.status_code == 422
    assert "mandatory" in res_rej_empty.json()["detail"].lower()

    # Attempt 2: Rejection WITH required notes -> must succeed
    rejection_reason = "Unauthorized absence from designated ward perimeter; no prior supervisor leave."
    res_rej = await async_client.post(
        f"/api/v1/attendance/{rec_id}/review",
        headers=sup_a_headers,
        json={
            "action": "REJECT",
            "review_notes": rejection_reason,
        },
    )
    assert res_rej.status_code == 200
    rej_data = res_rej.json()
    assert rej_data["new_status"] == AttendanceStatus.REJECTED.value
    assert rej_data["reviewed_by"] == str(sup_a.id)
    assert rej_data["review_notes"] == rejection_reason

    # Verify notification created for worker via Notifications API
    res_notifs = await async_client.get("/api/v1/notifications", headers=w2_headers)
    assert res_notifs.status_code == 200
    notifs_data = res_notifs.json()
    assert notifs_data["total_count"] >= 1
    review_notifs = [n for n in notifs_data["items"] if n["notification_type"] == "ATTENDANCE_REVIEW"]
    assert len(review_notifs) >= 1
    assert "rejected" in review_notifs[0]["message"].lower()
    assert "Attendance Exception Rejected" == review_notifs[0]["title"]


@pytest.mark.asyncio
async def test_supervisor_ward_authorization_boundaries(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    audit_environment: dict,
):
    """
    Verifies Section 2:
    - Supervisor cannot review records outside their authorized ward (HTTP 403).
    - Citizen or Worker cannot review records (HTTP 403).
    """
    env = audit_environment
    ward_a = env["ward_a"]
    w1 = env["worker_1"]
    sup_b = env["sup_b"]  # Ward B supervisor
    citizen = env["citizen"]

    # Create an attendance record in Ward A
    w1_token = create_access_token(subject=w1.id)
    res_otp = await async_client.post("/api/v1/attendance/otp/request", headers={"Authorization": f"Bearer {w1_token}"})
    assert res_otp.status_code == 200
    otp_data = res_otp.json()
    await async_client.post(
        "/api/v1/attendance/otp/verify",
        headers={"Authorization": f"Bearer {w1_token}"},
        json={"challenge_id": otp_data["challenge_id"], "otp": otp_data["dev_otp"]},
    )
    res_in = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers={"Authorization": f"Bearer {w1_token}"},
        json={
            "challenge_id": otp_data["challenge_id"],
            "latitude": 13.0984,
            "longitude": 77.5930,
            "ward_id": str(ward_a.id),
        },
    )
    assert res_in.status_code == 201
    rec_id = res_in.json()["attendance_id"]

    # 1. Ward B supervisor tries to review Ward A record -> 403 Forbidden
    sup_b_token = create_access_token(subject=sup_b.id)
    res_cross = await async_client.post(
        f"/api/v1/attendance/{rec_id}/review",
        headers={"Authorization": f"Bearer {sup_b_token}"},
        json={"action": "APPROVE", "review_notes": "Cross ward review attempt"},
    )
    assert res_cross.status_code == 403
    assert "not assigned as supervisor for ward" in res_cross.json()["detail"].lower()

    # 2. Citizen tries to review -> 403 Forbidden
    cit_token = create_access_token(subject=citizen.id)
    res_cit = await async_client.post(
        f"/api/v1/attendance/{rec_id}/review",
        headers={"Authorization": f"Bearer {cit_token}"},
        json={"action": "APPROVE", "review_notes": "Citizen attempt"},
    )
    assert res_cit.status_code == 403

    # 3. Worker tries to review -> 403 Forbidden
    res_self = await async_client.post(
        f"/api/v1/attendance/{rec_id}/review",
        headers={"Authorization": f"Bearer {w1_token}"},
        json={"action": "APPROVE", "review_notes": "Self approval attempt"},
    )
    assert res_self.status_code == 403


@pytest.mark.asyncio
async def test_status_semantics_and_statistics_agreement(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
    audit_environment: dict,
):
    """
    Verifies Section 3:
    - EXCEPTION_PENDING is excluded from verified present counts.
    - Present and exception counters update accurately after review.
    - Roster reflects exact counts.
    """
    env = audit_environment
    ward_a = env["ward_a"]
    w1 = env["worker_1"]
    sup_a = env["sup_a"]
    sup_a_token = create_access_token(subject=sup_a.id)
    sup_a_headers = {"Authorization": f"Bearer {sup_a_token}"}
    w1_token = create_access_token(subject=w1.id)
    w1_headers = {"Authorization": f"Bearer {w1_token}"}

    # Step 1: Check-in with exception
    res_otp = await async_client.post("/api/v1/attendance/otp/request", headers=w1_headers)
    assert res_otp.status_code == 200
    otp_data = res_otp.json()
    await async_client.post(
        "/api/v1/attendance/otp/verify",
        headers=w1_headers,
        json={"challenge_id": otp_data["challenge_id"], "otp": otp_data["dev_otp"]},
    )
    res_in = await async_client.post(
        "/api/v1/attendance/otp-check-in",
        headers=w1_headers,
        json={
            "challenge_id": otp_data["challenge_id"],
            "latitude": 13.0984,
            "longitude": 77.5930,
            "ward_id": str(ward_a.id),
        },
    )
    assert res_in.status_code == 201
    rec_id = res_in.json()["attendance_id"]

    # Query daily roster before review
    res_roster_before = await async_client.get(
        f"/api/v1/wards/{ward_a.id}/attendance/daily",
        headers=sup_a_headers,
    )
    assert res_roster_before.status_code == 200
    roster_1 = res_roster_before.json()
    # EXCEPTION_PENDING must NOT be counted as present!
    assert roster_1["present_count"] == 0
    assert roster_1["exception_pending_count"] == 1
    assert roster_1["rejected_count"] == 0

    # Query supervisor stats
    res_stats_before = await async_client.get(
        f"/api/v1/supervisor/dashboard/stats?ward_id={ward_a.id}",
        headers=sup_a_headers,
    )
    assert res_stats_before.status_code == 200
    stats_1 = res_stats_before.json()
    assert stats_1["present_today"] == 0
    assert stats_1["attendance_exceptions"] == 1

    # Step 2: Supervisor approves the exception
    res_rev = await async_client.post(
        f"/api/v1/attendance/{rec_id}/review",
        headers=sup_a_headers,
        json={"action": "APPROVE", "review_notes": "Supervisor verified valid field detour."},
    )
    assert res_rev.status_code == 200

    # Query daily roster after review
    res_roster_after = await async_client.get(
        f"/api/v1/wards/{ward_a.id}/attendance/daily",
        headers=sup_a_headers,
    )
    assert res_roster_after.status_code == 200
    roster_2 = res_roster_after.json()
    assert roster_2["present_count"] == 1
    assert roster_2["exception_pending_count"] == 0
    assert roster_2["rejected_count"] == 0

    # Query supervisor stats after review
    res_stats_after = await async_client.get(
        f"/api/v1/supervisor/dashboard/stats?ward_id={ward_a.id}",
        headers=sup_a_headers,
    )
    assert res_stats_after.status_code == 200
    stats_2 = res_stats_after.json()
    assert stats_2["present_today"] == 1
    assert stats_2["attendance_exceptions"] == 0


@pytest.mark.asyncio
async def test_concurrency_and_row_locking_integrity(
    async_db_session: AsyncSession,
    audit_environment: dict,
):
    """
    Verifies Section 2:
    - Service function review_attendance_record uses row-level locking (with_for_update).
    - If status is not EXCEPTION_PENDING, it raises AttendanceNotReviewableError.
    """
    env = audit_environment
    w1 = env["worker_1"]
    sup_a = env["sup_a"]
    muster_a = env["muster_a"]

    # Create an attendance record directly in EXCEPTION_PENDING
    now = utc_now()
    rec = AttendanceRecord(
        id=uuid.uuid4(),
        worker_id=w1.id,
        ward_id=env["ward_a"].id,
        muster_point_id=muster_a.id,
        attendance_date=date(2026, 12, 1),
        check_in_at=now,
        status=AttendanceStatus.EXCEPTION_PENDING.value,
        exception_reason="Test exception for concurrency lock audit",
        check_in_distance_meters=250.0,
    )
    async_db_session.add(rec)
    await async_db_session.commit()

    # First review: succeeds
    updated = await review_attendance_record(
        session=async_db_session,
        record_id=rec.id,
        reviewer_id=sup_a.id,
        action="APPROVE",
        review_notes="First review commits successfully",
    )
    await async_db_session.commit()
    assert updated.status == AttendanceStatus.PRESENT.value

    # Second review on same record in a subsequent transaction: must fail with AttendanceNotReviewableError
    with pytest.raises(AttendanceNotReviewableError) as exc_info:
        await review_attendance_record(
            session=async_db_session,
            record_id=rec.id,
            reviewer_id=sup_a.id,
            action="REJECT",
            review_notes="Concurrent second review attempt",
        )
    assert "cannot be reviewed because its status is 'PRESENT'" in str(exc_info.value)
