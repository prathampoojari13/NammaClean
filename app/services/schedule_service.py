"""
Core business logic for Worker Schedules, Overrides, Attendance Window Validation,
and Supervisor Operational Metrics in Asia/Kolkata timezone.
"""

import uuid
from datetime import datetime, date, timezone, timedelta
from typing import Optional, List, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.route import CollectionRoute
from app.models.attendance import AttendanceRecord
from app.models.schedule import WorkerSchedule, ScheduleOverride
from app.schemas.schedule import ResolvedDailySchedule

# Asia/Kolkata timezone
try:
    KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def get_kolkata_now() -> datetime:
    """Returns the current timezone-aware datetime in Asia/Kolkata."""
    return datetime.now(KOLKATA_TZ)


def get_kolkata_today() -> date:
    """Returns today's date in Asia/Kolkata."""
    return get_kolkata_now().date()


def parse_time_minutes(time_str: str) -> int:
    """Converts 'HH:MM' string to minutes since midnight."""
    parts = time_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def format_12hr(time_str: str) -> str:
    """Converts 'HH:MM' 24-hr format to 'h:mm AM/PM'."""
    try:
        parts = time_str.strip().split(":")
        hr = int(parts[0])
        mn = int(parts[1])
        period = "AM" if hr < 12 else "PM"
        display_hr = hr % 12
        if display_hr == 0:
            display_hr = 12
        return f"{display_hr}:{mn:02d} {period}"
    except Exception:
        return time_str


async def get_resolved_worker_schedule(
    db: AsyncSession,
    worker_id: uuid.UUID,
    target_date: date,
) -> ResolvedDailySchedule:
    """
    Resolves the authoritative working schedule for a worker on a specific date.
    Precedence:
    1. Date-specific ScheduleOverride (DAY_OFF, HOLIDAY, LEAVE -> not a working day; SPECIAL_SHIFT -> custom hours).
    2. Recurring active WorkerSchedule (effective_from <= date <= effective_to, weekday in days_of_week).
    """
    # 1. Check date-specific overrides
    stmt_override = select(ScheduleOverride).where(
        ScheduleOverride.worker_id == worker_id,
        ScheduleOverride.override_date == target_date,
    )
    res_override = await db.execute(stmt_override)
    override = res_override.scalars().first()

    if override:
        if override.override_type in ("DAY_OFF", "HOLIDAY", "LEAVE"):
            return ResolvedDailySchedule(
                is_scheduled_workday=False,
                is_override=True,
                override_type=override.override_type,
                reason=override.reason or f"Scheduled {override.override_type.replace('_', ' ').title()}",
            )
        elif override.override_type == "SPECIAL_SHIFT":
            return ResolvedDailySchedule(
                is_scheduled_workday=True,
                shift_start_time=override.shift_start_time or "07:00",
                shift_end_time=override.shift_end_time or "14:00",
                check_in_start_time=override.check_in_start_time or "06:45",
                check_in_end_time=override.check_in_end_time or "07:30",
                is_override=True,
                override_type=override.override_type,
                reason=override.reason or "Special Shift Override",
            )

    # 2. Check recurring active schedule
    stmt_sched = (
        select(WorkerSchedule)
        .where(
            WorkerSchedule.worker_id == worker_id,
            WorkerSchedule.is_active == True,
            WorkerSchedule.effective_from <= target_date,
            or_(
                WorkerSchedule.effective_to.is_(None),
                WorkerSchedule.effective_to >= target_date,
            ),
        )
        .order_by(WorkerSchedule.created_at.desc())
    )
    res_sched = await db.execute(stmt_sched)
    sched = res_sched.scalars().first()

    if not sched:
        return ResolvedDailySchedule(
            is_scheduled_workday=False,
            reason="No active work schedule assigned.",
        )

    # ISO weekday: Monday=1, ..., Sunday=7
    weekday_iso = target_date.isoweekday()
    if weekday_iso not in sched.days_of_week:
        return ResolvedDailySchedule(
            is_scheduled_workday=False,
            schedule_id=sched.id,
            ward_id=sched.ward_id,
            route_id=sched.route_id,
            reason=f"Day of week ({target_date.strftime('%A')}) is not a scheduled working day.",
        )

    return ResolvedDailySchedule(
        is_scheduled_workday=True,
        schedule_id=sched.id,
        ward_id=sched.ward_id,
        route_id=sched.route_id,
        shift_start_time=sched.shift_start_time,
        shift_end_time=sched.shift_end_time,
        check_in_start_time=sched.check_in_start_time,
        check_in_end_time=sched.check_in_end_time,
        check_out_start_time=sched.check_out_start_time,
        check_out_end_time=sched.check_out_end_time,
        grace_period_minutes=sched.grace_period_minutes,
    )


def validate_check_in_window(
    schedule: ResolvedDailySchedule,
    now_kolkata: Optional[datetime] = None,
) -> Tuple[bool, str, str]:
    """
    Validates server time against check-in window and grace period.
    Returns:
    (can_proceed, status_flag, user_message)
    status_flag: 'ON_TIME' | 'GRACE' | 'LATE_EXCEPTION' | 'CLOSED' | 'NOT_OPEN'
    """
    now = now_kolkata or get_kolkata_now()
    now_minutes = now.hour * 60 + now.minute

    start_str = schedule.check_in_start_time or "06:45"
    end_str = schedule.check_in_end_time or "07:30"
    grace = schedule.grace_period_minutes or 10

    start_m = parse_time_minutes(start_str)
    end_m = parse_time_minutes(end_str)
    grace_end_m = end_m + grace

    if now_minutes < start_m:
        diff = start_m - now_minutes
        hrs, mins = divmod(diff, 60)
        time_hint = f"{hrs}h {mins}m" if hrs else f"{mins}m"
        return (
            False,
            "NOT_OPEN",
            f"Check-in has not opened yet. Your permitted check-in window opens at {format_12hr(start_str)} IST (in {time_hint}).",
        )

    if start_m <= now_minutes <= end_m:
        return (
            True,
            "ON_TIME",
            f"On-time check-in verified ({format_12hr(start_str)}–{format_12hr(end_str)} IST).",
        )

    if end_m < now_minutes <= grace_end_m:
        return (
            True,
            "GRACE",
            f"Check-in verified within {grace}-minute grace period (window closed at {format_12hr(end_str)} IST).",
        )

    # Outside normal window + grace period: requires supervisor approval flow
    return (
        True,
        "LATE_EXCEPTION",
        f"Check-in outside permitted window ({format_12hr(start_str)}–{format_12hr(end_str)} IST). Recorded as pending supervisor review.",
    )


async def calculate_supervisor_dashboard_stats(
    db: AsyncSession,
    ward_id: uuid.UUID,
    target_date: Optional[date] = None,
) -> Tuple[int, int, int, int, int]:
    """
    Computes real, non-fabricated supervisor dashboard operational statistics:
    1. workers_scheduled_today: active workers with a valid schedule for target_date.
    2. present_today: scheduled workers with accepted check-in.
    3. attendance_pending: scheduled workers whose check-in window has EXPIRED without check-in.
       (Workers are NOT marked pending before their window closes).
    4. attendance_exceptions: records with EXCEPTION_PENDING status.
    5. total_registered_workers: all registered active sanitation workers in the ward.
    """
    date_val = target_date or get_kolkata_today()
    now_kolkata = get_kolkata_now()
    now_minutes = now_kolkata.hour * 60 + now_kolkata.minute
    is_today = date_val == now_kolkata.date()

    # 1. Total registered active workers assigned to this ward
    stmt_workers = (
        select(User)
        .join(UserWardAssignment, User.id == UserWardAssignment.user_id)
        .where(
            User.role == UserRole.SANITATION_WORKER.value,
            User.status == UserStatus.ACTIVE.value,
            UserWardAssignment.ward_id == ward_id,
            UserWardAssignment.revoked_at.is_(None),
        )
    )
    res_workers = await db.execute(stmt_workers)
    workers = res_workers.scalars().all()
    total_registered = len(workers)

    # 2. Daily attendance records for target_date
    stmt_att = select(AttendanceRecord).where(
        AttendanceRecord.ward_id == ward_id,
        AttendanceRecord.attendance_date == date_val,
    )
    res_att = await db.execute(stmt_att)
    att_records = res_att.scalars().all()
    att_by_worker = {r.worker_id: r for r in att_records}

    workers_scheduled_today = 0
    present_today = 0
    attendance_pending = 0
    attendance_exceptions = 0

    for w in workers:
        sched = await get_resolved_worker_schedule(db, w.id, date_val)
        if not sched.is_scheduled_workday:
            continue

        workers_scheduled_today += 1
        att = att_by_worker.get(w.id)

        if att:
            if att.status in (AttendanceStatus.PRESENT.value, AttendanceStatus.HALF_DAY.value):
                present_today += 1
            elif att.status == AttendanceStatus.EXCEPTION_PENDING.value:
                attendance_exceptions += 1
        else:
            # Worker has not checked in.
            # Crucial requirement: Check if the check-in window has expired!
            end_m = parse_time_minutes(sched.check_in_end_time or "07:30")
            grace = sched.grace_period_minutes or 10
            cutoff_m = end_m + grace

            if not is_today or (is_today and now_minutes > cutoff_m):
                # Permitted check-in window has expired without an accepted check-in
                attendance_pending += 1

    # Also count exceptions from any record in this ward on this date
    attendance_exceptions = sum(1 for r in att_records if r.status == AttendanceStatus.EXCEPTION_PENDING.value)

    return (
        workers_scheduled_today,
        present_today,
        attendance_pending,
        attendance_exceptions,
        total_registered,
    )
