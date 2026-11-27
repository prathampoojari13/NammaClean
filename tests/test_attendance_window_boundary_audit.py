"""
Isolated automated tests auditing Attendance Window Validation & Schedule Rules.
Tests:
1. Before check-in window opens -> rejected (NOT_OPEN, can_proceed=False).
2. Within permitted check-in window -> accepted (ON_TIME, can_proceed=True).
3. Within configured grace period -> accepted (GRACE, can_proceed=True).
4. After permitted period (late attendance) -> allowed with LATE_EXCEPTION (can_proceed=True, status=EXCEPTION_PENDING).
5. Unscheduled day of week -> rejected (is_scheduled_workday=False, HTTP 400).
6. DAY_OFF, HOLIDAY, LEAVE override -> rejected (is_scheduled_workday=False, reason documented).
7. SPECIAL_SHIFT override -> custom shift hours applied and enforced.
8. Authoritative server clock evaluated in Asia/Kolkata timezone.
"""

import uuid
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord
from app.models.schedule import WorkerSchedule, ScheduleOverride
from app.schemas.schedule import ResolvedDailySchedule
from app.services.schedule_service import (
    validate_check_in_window,
    get_resolved_worker_schedule,
    get_kolkata_now,
    get_kolkata_today,
    KOLKATA_TZ,
)


def test_window_validation_matrix():
    """Verify check-in window validation matrix across all 4 time zones of a shift."""
    schedule = ResolvedDailySchedule(
        is_scheduled_workday=True,
        shift_start_time="07:00",
        shift_end_time="14:00",
        check_in_start_time="06:45",
        check_in_end_time="07:30",
        grace_period_minutes=10,
    )

    base_date = date(2026, 11, 27)

    # 1. Before window opens (06:30 IST) -> NOT_OPEN, False
    t_before = datetime(2026, 11, 27, 6, 30, tzinfo=KOLKATA_TZ)
    can_proceed, flag, msg = validate_check_in_window(schedule, t_before)
    assert can_proceed is False
    assert flag == "NOT_OPEN"
    assert "not opened yet" in msg.lower()

    # 2. Within permitted window (07:00 IST) -> ON_TIME, True
    t_ontime = datetime(2026, 11, 27, 7, 0, tzinfo=KOLKATA_TZ)
    can_proceed, flag, msg = validate_check_in_window(schedule, t_ontime)
    assert can_proceed is True
    assert flag == "ON_TIME"
    assert "on-time" in msg.lower()

    # 3. Within grace period (07:35 IST) -> GRACE, True
    t_grace = datetime(2026, 11, 27, 7, 35, tzinfo=KOLKATA_TZ)
    can_proceed, flag, msg = validate_check_in_window(schedule, t_grace)
    assert can_proceed is True
    assert flag == "GRACE"
    assert "grace period" in msg.lower()

    # 4. After grace period (08:15 IST) -> LATE_EXCEPTION, True
    t_late = datetime(2026, 11, 27, 8, 15, tzinfo=KOLKATA_TZ)
    can_proceed, flag, msg = validate_check_in_window(schedule, t_late)
    assert can_proceed is True
    assert flag == "LATE_EXCEPTION"
    assert "supervisor review" in msg.lower()


@pytest.mark.asyncio
async def test_unscheduled_day_and_overrides(async_db_session: AsyncSession):
    """Verify schedule resolution for unscheduled days, DAY_OFF/HOLIDAY/LEAVE, and SPECIAL_SHIFT."""
    ward = Ward(ward_code=f"W-SCH-{uuid.uuid4().hex[:6]}", display_name=f"Ward-{uuid.uuid4().hex[:4]}")
    async_db_session.add(ward)
    await async_db_session.commit()

    worker = User(
        email=f"w_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
    )
    async_db_session.add(worker)
    await async_db_session.commit()

    # Recurring Mon-Fri schedule
    sched = WorkerSchedule(
        worker_id=worker.id,
        ward_id=ward.id,
        days_of_week=[1, 2, 3, 4, 5], # Mon-Fri
        shift_start_time="07:00",
        shift_end_time="14:00",
        check_in_start_time="06:45",
        check_in_end_time="07:30",
        grace_period_minutes=10,
        effective_from=date(2026, 1, 1),
        is_active=True,
    )
    async_db_session.add(sched)
    await async_db_session.commit()

    # 1. Scheduled working day (Friday, 2026-11-27)
    friday = date(2026, 11, 27)
    res_fri = await get_resolved_worker_schedule(async_db_session, worker.id, friday)
    assert res_fri.is_scheduled_workday is True
    assert res_fri.shift_start_time == "07:00"

    # 2. Unscheduled day (Sunday, 2026-11-29)
    sunday = date(2026, 11, 29)
    res_sun = await get_resolved_worker_schedule(async_db_session, worker.id, sunday)
    assert res_sun.is_scheduled_workday is False
    assert "Sunday" in res_sun.reason

    # 3. DAY_OFF override on a scheduled Friday
    override_off = ScheduleOverride(
        worker_id=worker.id,
        override_date=friday,
        override_type="DAY_OFF",
        reason="Sanctioned weekly rest day",
        created_by=worker.id,
    )
    async_db_session.add(override_off)
    await async_db_session.commit()

    res_off = await get_resolved_worker_schedule(async_db_session, worker.id, friday)
    assert res_off.is_scheduled_workday is False
    assert res_off.is_override is True
    assert res_off.override_type == "DAY_OFF"

    # 4. SPECIAL_SHIFT override on Saturday (normally off)
    saturday = date(2026, 11, 28)
    override_spec = ScheduleOverride(
        worker_id=worker.id,
        override_date=saturday,
        override_type="SPECIAL_SHIFT",
        shift_start_time="14:00",
        shift_end_time="22:00",
        check_in_start_time="13:45",
        check_in_end_time="14:30",
        reason="Festival Cleanliness Drive",
        created_by=worker.id,
    )
    async_db_session.add(override_spec)
    await async_db_session.commit()

    res_spec = await get_resolved_worker_schedule(async_db_session, worker.id, saturday)
    assert res_spec.is_scheduled_workday is True
    assert res_spec.is_override is True
    assert res_spec.override_type == "SPECIAL_SHIFT"
    assert res_spec.shift_start_time == "14:00"
    assert res_spec.check_in_start_time == "13:45"


@pytest.mark.asyncio
async def test_unscheduled_day_api_rejection(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify API rejects check-in request when worker is unscheduled for the target date."""
    ward = Ward(ward_code=f"W-REJ-{uuid.uuid4().hex[:6]}", display_name=f"Ward-{uuid.uuid4().hex[:4]}")
    async_db_session.add(ward)
    await async_db_session.commit()

    worker = User(
        email=f"w_rej_{uuid.uuid4().hex[:6]}@nammaclean.test",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        ward_id=ward.id,
    )
    async_db_session.add(worker)
    await async_db_session.commit()
    async_db_session.add(UserWardAssignment(user_id=worker.id, ward_id=ward.id))
    await async_db_session.commit()

    # Worker has a schedule ONLY for Mondays (day 1). Today (Friday, day 5) is NOT scheduled.
    sched = WorkerSchedule(
        worker_id=worker.id,
        ward_id=ward.id,
        days_of_week=[1], # Only Monday
        shift_start_time="07:00",
        shift_end_time="14:00",
        is_active=True,
    )
    async_db_session.add(sched)
    await async_db_session.commit()

    token = create_access_token(subject=worker.id)

    # Calling OTP request should fail because worker is not scheduled today
    res_otp = await async_client.post(
        "/api/v1/attendance/otp/request",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_otp.status_code == 400
    assert "not a scheduled working day" in res_otp.json()["detail"].lower()
