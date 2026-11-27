"""
Worker endpoints for personal schedule, assigned route, and attendance history.
Restricted to authenticated Sanitation Workers.
"""

import uuid
import logging
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.enums import UserRole, AttendanceStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.route import CollectionRoute
from app.models.attendance import AttendanceRecord, MusterPoint
from app.models.schedule import WorkerSchedule, ScheduleOverride
from app.schemas.schedule import (
    WorkerScheduleResponse,
    ScheduleOverrideResponse,
    ResolvedDailySchedule,
)
from app.schemas.attendance import AttendanceDailyItemResponse
from app.services.schedule_service import (
    get_resolved_worker_schedule,
    get_kolkata_today,
    get_kolkata_now,
    validate_check_in_window,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/worker", tags=["Worker Operations"])


@router.get(
    "/schedule",
    summary="Get Worker Recurring Schedule & Today's Shift Status",
)
async def get_my_schedule(
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
):
    today = get_kolkata_today()

    # 1. Active recurring schedule
    stmt_sched = (
        select(WorkerSchedule, CollectionRoute, Ward)
        .outerjoin(CollectionRoute, WorkerSchedule.route_id == CollectionRoute.id)
        .join(Ward, WorkerSchedule.ward_id == Ward.id)
        .where(
            WorkerSchedule.worker_id == current_user.id,
            WorkerSchedule.is_active == True,
        )
        .order_by(WorkerSchedule.created_at.desc())
    )
    res_sched = await db.execute(stmt_sched)
    row = res_sched.first()

    active_schedule_data = None
    if row:
        ws, cr, w = row
        active_schedule_data = WorkerScheduleResponse(
            id=ws.id,
            worker_id=ws.worker_id,
            worker_name=current_user.full_name,
            worker_email=current_user.email,
            ward_id=ws.ward_id,
            ward_name=w.display_name if w else None,
            route_id=ws.route_id,
            route_name=cr.name if cr else None,
            route_code=cr.route_code if cr else None,
            days_of_week=ws.days_of_week,
            shift_start_time=ws.shift_start_time,
            shift_end_time=ws.shift_end_time,
            check_in_start_time=ws.check_in_start_time,
            check_in_end_time=ws.check_in_end_time,
            check_out_start_time=ws.check_out_start_time,
            check_out_end_time=ws.check_out_end_time,
            grace_period_minutes=ws.grace_period_minutes,
            timezone=ws.timezone,
            effective_from=ws.effective_from,
            effective_to=ws.effective_to,
            is_active=ws.is_active,
            created_at=ws.created_at,
            updated_at=ws.updated_at,
        )

    # 2. Resolved status for today (including overrides & window check)
    today_resolved = await get_resolved_worker_schedule(db, current_user.id, today)

    window_status = "UNKNOWN"
    window_message = ""
    can_check_in = False

    if today_resolved.is_scheduled_workday:
        can_check_in, window_status, window_message = validate_check_in_window(
            today_resolved, get_kolkata_now()
        )
    else:
        window_status = "NOT_SCHEDULED"
        window_message = today_resolved.reason or "No shift scheduled for today."

    # 3. Upcoming overrides in next 30 days
    stmt_over = (
        select(ScheduleOverride)
        .where(
            ScheduleOverride.worker_id == current_user.id,
            ScheduleOverride.override_date >= today,
        )
        .order_by(ScheduleOverride.override_date.asc())
        .limit(10)
    )
    res_over = await db.execute(stmt_over)
    overrides = [ScheduleOverrideResponse.model_validate(o) for o in res_over.scalars().all()]

    return {
        "has_schedule": active_schedule_data is not None,
        "today_is_workday": today_resolved.is_scheduled_workday,
        "today_reason": today_resolved.reason,
        "is_override": today_resolved.is_override,
        "override_type": today_resolved.override_type,
        "shift_start_time": today_resolved.shift_start_time or (active_schedule_data.shift_start_time if active_schedule_data else None),
        "shift_end_time": today_resolved.shift_end_time or (active_schedule_data.shift_end_time if active_schedule_data else None),
        "check_in_start_time": today_resolved.check_in_start_time or (active_schedule_data.check_in_start_time if active_schedule_data else None),
        "check_in_end_time": today_resolved.check_in_end_time or (active_schedule_data.check_in_end_time if active_schedule_data else None),
        "check_out_start_time": today_resolved.check_out_start_time,
        "check_out_end_time": today_resolved.check_out_end_time,
        "grace_period_minutes": today_resolved.grace_period_minutes if today_resolved.grace_period_minutes is not None else (active_schedule_data.grace_period_minutes if active_schedule_data else 10),
        "window_status": window_status,
        "window_message": window_message,
        "can_check_in": can_check_in,
        "can_check_in_now": can_check_in,
        "route_id": today_resolved.route_id or (active_schedule_data.route_id if active_schedule_data else None),
        "route_name": active_schedule_data.route_name if active_schedule_data else None,
        "days_of_week": active_schedule_data.days_of_week if active_schedule_data else [],
        "active_schedule": active_schedule_data,
        "today_resolved": today_resolved,
        "upcoming_overrides": overrides,
    }


@router.get(
    "/route",
    summary="Get Assigned Collection Route",
)
async def get_my_route(
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
):
    # Find active schedule with route
    stmt = (
        select(CollectionRoute)
        .join(WorkerSchedule, WorkerSchedule.route_id == CollectionRoute.id)
        .where(
            WorkerSchedule.worker_id == current_user.id,
            WorkerSchedule.is_active == True,
        )
        .order_by(WorkerSchedule.created_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    route = res.scalars().first()

    if not route:
        return {
            "assigned": False,
            "route_id": None,
            "route": None,
            "waypoints": [],
            "message": "No collection route currently assigned.",
        }

    from geoalchemy2.shape import to_shape
    coords = []
    if route.route_path:
        shape = to_shape(route.route_path)
        coords = list(shape.coords)  # [(lon, lat), ...]

    return {
        "assigned": True,
        "route_id": route.id,
        "route": {
            "id": route.id,
            "name": route.name,
            "route_code": route.route_code,
            "ward_id": route.ward_id,
            "coordinates": coords,
            "waypoints": coords,
        },
        "waypoints": coords,
        "message": f"Assigned to {route.name}.",
    }


@router.get(
    "/attendance/history",
    response_model=List[AttendanceDailyItemResponse],
    summary="Get Worker Attendance History",
)
async def get_my_attendance_history(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
) -> List[AttendanceDailyItemResponse]:
    stmt = (
        select(AttendanceRecord, MusterPoint.name.label("mp_name"))
        .outerjoin(MusterPoint, AttendanceRecord.muster_point_id == MusterPoint.id)
        .where(AttendanceRecord.worker_id == current_user.id)
        .order_by(AttendanceRecord.attendance_date.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)

    items = []
    for record, mp_name in res.all():
        items.append(
            AttendanceDailyItemResponse(
                id=record.id,
                worker_id=record.worker_id,
                worker_email=current_user.email,
                worker_name=current_user.full_name,
                official_id=current_user.official_id,
                ward_id=record.ward_id,
                muster_point_id=record.muster_point_id,
                muster_point_name=mp_name,
                attendance_date=record.attendance_date,
                check_in_at=record.check_in_at,
                check_out_at=record.check_out_at,
                status=record.status,
                check_in_distance_meters=record.check_in_distance_meters,
                check_out_distance_meters=record.check_out_distance_meters,
                check_in_accuracy_meters=record.check_in_accuracy_meters,
                check_out_accuracy_meters=record.check_out_accuracy_meters,
                duration_minutes=record.duration_minutes,
                exception_reason=record.exception_reason,
                reviewed_by=record.reviewed_by,
                reviewed_at=record.reviewed_at,
                review_notes=record.review_notes,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
    return items
