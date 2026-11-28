"""
Supervisor endpoints for Ward Workforce Management, Recurring Schedules,
Operational Metrics, and Worker Registration.
Restricted to Ward Supervisors (within authorized ward) and Municipal Admins.
"""

import uuid
import logging
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_, and_, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles, verify_ward_access
from app.core.database import get_db
from app.core.security import hash_password
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User, normalize_email, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.models.route import CollectionRoute
from app.models.attendance import AttendanceRecord
from app.models.schedule import WorkerSchedule, ScheduleOverride
from app.schemas.schedule import (
    WorkerStatusUpdateRequest,
    WorkerScheduleCreateRequest,
    WorkerScheduleResponse,
    ScheduleOverrideCreateRequest,
    ScheduleOverrideResponse,
    SupervisorWorkerRegisterRequest,
    SupervisorWorkerSummary,
    SupervisorDashboardStatsResponse,
)
from app.services.schedule_service import (
    get_resolved_worker_schedule,
    calculate_supervisor_dashboard_stats,
    get_kolkata_today,
    parse_time_minutes,
)
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supervisor", tags=["Supervisor Management"])


async def _get_supervisor_ward_id(user: User, explicit_ward_id: Optional[uuid.UUID], db: AsyncSession) -> uuid.UUID:
    """Resolves authorized ward for supervisor, enforcing ward-level access."""
    if user.role == UserRole.MUNICIPAL_ADMIN.value:
        if explicit_ward_id:
            return explicit_ward_id
        # Fall back to user's assigned ward or first active ward
        if user.ward_id:
            return user.ward_id
        stmt = select(Ward.id).order_by(Ward.created_at.asc()).limit(1)
        res = await db.execute(stmt)
        first_ward = res.scalar_one_or_none()
        if not first_ward:
            raise HTTPException(status_code=400, detail="No municipal wards exist in the system.")
        return first_ward

    # WARD_SUPERVISOR
    ward_id = explicit_ward_id or user.ward_id
    if not ward_id:
        # Check UserWardAssignment
        stmt = select(UserWardAssignment.ward_id).where(
            UserWardAssignment.user_id == user.id,
            UserWardAssignment.revoked_at.is_(None),
        ).limit(1)
        res = await db.execute(stmt)
        ward_id = res.scalar_one_or_none()

    if not ward_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Supervisor is not assigned to any administrative ward.",
        )

    await verify_ward_access(user, ward_id, db)
    return ward_id


@router.get(
    "/dashboard/stats",
    response_model=SupervisorDashboardStatsResponse,
    summary="Get Real Supervisor Operational Metrics",
)
async def get_dashboard_stats(
    ward_id: Optional[uuid.UUID] = Query(default=None),
    attendance_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SupervisorDashboardStatsResponse:
    resolved_ward_id = await _get_supervisor_ward_id(current_user, ward_id, db)
    target_date = attendance_date or get_kolkata_today()

    sched_count, pres_count, pend_count, exc_count, total_count = await calculate_supervisor_dashboard_stats(
        db=db,
        ward_id=resolved_ward_id,
        target_date=target_date,
    )

    return SupervisorDashboardStatsResponse(
        ward_id=resolved_ward_id,
        attendance_date=target_date,
        workers_scheduled_today=sched_count,
        present_today=pres_count,
        attendance_pending=pend_count,
        attendance_exceptions=exc_count,
        total_registered_workers=total_count,
    )


@router.get(
    "/workers",
    response_model=List[SupervisorWorkerSummary],
    summary="List Ward Sanitation Workers Directory",
)
async def list_ward_workers(
    ward_id: Optional[uuid.UUID] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Search by name, email, or official ID"),
    status_filter: Optional[str] = Query(default="ALL", description="Filter by status: ACTIVE, DISABLED, or ALL"),
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> List[SupervisorWorkerSummary]:
    resolved_ward_id = await _get_supervisor_ward_id(current_user, ward_id, db)
    today = get_kolkata_today()

    # Query ward name
    stmt_ward = select(Ward).where(Ward.id == resolved_ward_id)
    res_ward = await db.execute(stmt_ward)
    ward_obj = res_ward.scalars().first()
    ward_name = ward_obj.name if ward_obj else "Ward"

    # Query sanitation workers assigned to this ward
    stmt = (
        select(User)
        .join(UserWardAssignment, User.id == UserWardAssignment.user_id)
        .where(
            User.role == UserRole.SANITATION_WORKER.value,
            UserWardAssignment.ward_id == resolved_ward_id,
            UserWardAssignment.revoked_at.is_(None),
        )
    )

    if status_filter and status_filter.upper() != "ALL":
        stmt = stmt.where(User.status == status_filter.upper())

    if q and q.strip():
        search_term = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.full_name).ilike(search_term),
                func.lower(User.email).ilike(search_term),
                func.lower(User.official_id).ilike(search_term),
            )
        )

    stmt = stmt.order_by(User.full_name.asc(), User.created_at.desc())
    res = await db.execute(stmt)
    workers = res.scalars().all()

    # Pre-fetch today's attendance for these workers
    stmt_att = select(AttendanceRecord).where(
        AttendanceRecord.ward_id == resolved_ward_id,
        AttendanceRecord.attendance_date == today,
    )
    res_att = await db.execute(stmt_att)
    att_map = {r.worker_id: r for r in res_att.scalars().all()}

    # Pre-fetch active schedules
    stmt_sched = (
        select(WorkerSchedule, CollectionRoute)
        .outerjoin(CollectionRoute, WorkerSchedule.route_id == CollectionRoute.id)
        .where(
            WorkerSchedule.ward_id == resolved_ward_id,
            WorkerSchedule.is_active == True,
        )
    )
    res_sched = await db.execute(stmt_sched)
    sched_map = {}
    route_map = {}
    for ws, cr in res_sched.all():
        sched_map[ws.worker_id] = ws
        if cr:
            route_map[ws.worker_id] = cr

    items: List[SupervisorWorkerSummary] = []
    for w in workers:
        active_sched = sched_map.get(w.id)
        assigned_route = route_map.get(w.id)
        att_record = att_map.get(w.id)

        sched_response = None
        if active_sched:
            sched_response = WorkerScheduleResponse(
                id=active_sched.id,
                worker_id=w.id,
                worker_name=w.full_name,
                worker_email=w.email,
                ward_id=resolved_ward_id,
                ward_name=ward_name,
                route_id=active_sched.route_id,
                route_name=assigned_route.name if assigned_route else None,
                route_code=assigned_route.route_code if assigned_route else None,
                days_of_week=active_sched.days_of_week,
                shift_start_time=active_sched.shift_start_time,
                shift_end_time=active_sched.shift_end_time,
                check_in_start_time=active_sched.check_in_start_time,
                check_in_end_time=active_sched.check_in_end_time,
                check_out_start_time=active_sched.check_out_start_time,
                check_out_end_time=active_sched.check_out_end_time,
                grace_period_minutes=active_sched.grace_period_minutes,
                timezone=active_sched.timezone,
                effective_from=active_sched.effective_from,
                effective_to=active_sched.effective_to,
                is_active=active_sched.is_active,
                created_at=active_sched.created_at,
                updated_at=active_sched.updated_at,
            )

        today_status = "NOT_SCHEDULED"
        today_in = None
        today_out = None

        if att_record:
            today_status = att_record.status
            today_in = att_record.check_in_at
            today_out = att_record.check_out_at
        elif active_sched and today.isoweekday() in active_sched.days_of_week:
            today_status = "PENDING"

        items.append(
            SupervisorWorkerSummary(
                id=w.id,
                email=w.email,
                full_name=w.full_name,
                phone_number=w.phone_number,
                official_id=w.official_id,
                status=w.status,
                ward_id=resolved_ward_id,
                ward_name=ward_name,
                assigned_route_id=assigned_route.id if assigned_route else None,
                assigned_route_name=assigned_route.name if assigned_route else None,
                active_schedule=sched_response,
                today_attendance_status=today_status,
                today_check_in_at=today_in,
                today_check_out_at=today_out,
                created_at=w.created_at,
            )
        )

    return items


@router.post(
    "/workers",
    response_model=SupervisorWorkerSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Register Sanitation Worker",
)
async def register_worker(
    payload: SupervisorWorkerRegisterRequest,
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SupervisorWorkerSummary:
    resolved_ward_id = await _get_supervisor_ward_id(current_user, payload.ward_id, db)
    clean_email = normalize_email(payload.email)

    # 1. Email uniqueness check
    stmt_dup = select(User).where(User.email == clean_email)
    res_dup = await db.execute(stmt_dup)
    if res_dup.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # 2. Official ID uniqueness check
    clean_off_id = payload.official_id.strip() if payload.official_id and payload.official_id.strip() else None
    if clean_off_id:
        stmt_off = select(User).where(User.official_id == clean_off_id)
        res_off = await db.execute(stmt_off)
        if res_off.scalars().first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Official employee ID '{clean_off_id}' is already registered to another personnel account.",
            )

    # 3. Create user record with SANITATION_WORKER role
    worker = User(
        email=clean_email,
        password_hash=hash_password(payload.password),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value if payload.status == "ACTIVE" else UserStatus.DISABLED.value,
        full_name=payload.full_name.strip(),
        phone_number=payload.phone_number.strip() if payload.phone_number else None,
        official_id=clean_off_id,
        ward_id=resolved_ward_id,
    )
    db.add(worker)
    await db.flush()

    # 4. Create active ward assignment
    assignment = UserWardAssignment(
        user_id=worker.id,
        ward_id=resolved_ward_id,
        assigned_at=utc_now(),
    )
    db.add(assignment)

    # 5. Send persistent welcome notification
    await create_notification(
        db=db,
        user_id=worker.id,
        title="Pourakarmika Account Registered",
        message=f"Welcome to NammaClean, {worker.full_name}! Your sanitation worker profile is active.",
        notification_type="SYSTEM",
    )

    await db.commit()
    await db.refresh(worker)

    # Resolve ward name
    stmt_ward = select(Ward.display_name).where(Ward.id == resolved_ward_id)
    res_ward = await db.execute(stmt_ward)
    ward_name = res_ward.scalar_one_or_none()

    return SupervisorWorkerSummary(
        id=worker.id,
        email=worker.email,
        full_name=worker.full_name,
        phone_number=worker.phone_number,
        official_id=worker.official_id,
        status=worker.status,
        ward_id=resolved_ward_id,
        ward_name=ward_name,
        assigned_route_id=None,
        assigned_route_name=None,
        active_schedule=None,
        today_attendance_status="NOT_SCHEDULED",
        today_check_in_at=None,
        today_check_out_at=None,
        created_at=worker.created_at,
    )


@router.patch(
    "/workers/{worker_id}/status",
    response_model=SupervisorWorkerSummary,
    summary="Toggle Worker Active Status",
)
async def toggle_worker_status(
    worker_id: uuid.UUID,
    payload: Optional[WorkerStatusUpdateRequest] = None,
    status_val: Optional[str] = Query(None, pattern=r"^(ACTIVE|DISABLED)$"),
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SupervisorWorkerSummary:
    new_status = (payload.status if payload else None) or status_val
    if not new_status:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status must be provided via request body or query parameter.",
        )
    stmt = select(User).where(User.id == worker_id, User.role == UserRole.SANITATION_WORKER.value)
    res = await db.execute(stmt)
    worker = res.scalars().first()
    if not worker:
        raise HTTPException(status_code=404, detail="Sanitation worker not found.")

    if worker.ward_id:
        await verify_ward_access(current_user, worker.ward_id, db)

    worker.status = new_status
    worker.updated_at = utc_now()
    await db.commit()
    await db.refresh(worker)

    return SupervisorWorkerSummary(
        id=worker.id,
        email=worker.email,
        full_name=worker.full_name,
        phone_number=worker.phone_number,
        official_id=worker.official_id,
        status=worker.status,
        ward_id=worker.ward_id,
        created_at=worker.created_at,
    )


@router.post(
    "/schedules",
    response_model=WorkerScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign Recurring Work Schedule",
)
async def assign_schedule(
    payload: WorkerScheduleCreateRequest,
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> WorkerScheduleResponse:
    # 1. Verify worker exists and is sanitation worker
    stmt_w = select(User).where(User.id == payload.worker_id, User.role == UserRole.SANITATION_WORKER.value)
    res_w = await db.execute(stmt_w)
    worker = res_w.scalars().first()
    if not worker:
        raise HTTPException(status_code=404, detail="Sanitation worker not found.")

    # 2. Resolve ward_id if not explicitly provided
    resolved_ward_id = payload.ward_id
    if not resolved_ward_id:
        resolved_ward_id = worker.ward_id
        if not resolved_ward_id:
            stmt_a = select(UserWardAssignment.ward_id).where(UserWardAssignment.user_id == worker.id)
            res_a = await db.execute(stmt_a)
            resolved_ward_id = res_a.scalars().first()
        if not resolved_ward_id:
            raise HTTPException(status_code=400, detail="Worker has no ward assigned. Please specify ward_id.")

    # 3. Enforce ward access
    await verify_ward_access(current_user, resolved_ward_id, db)

    # 4. Validate time windows
    shift_start_m = parse_time_minutes(payload.shift_start_time)
    shift_end_m = parse_time_minutes(payload.shift_end_time)
    check_in_start_m = parse_time_minutes(payload.check_in_start_time)
    check_in_end_m = parse_time_minutes(payload.check_in_end_time)

    if shift_end_m <= shift_start_m:
        raise HTTPException(status_code=400, detail="Shift end time must be after shift start time.")
    if check_in_end_m <= check_in_start_m:
        raise HTTPException(status_code=400, detail="Check-in window closing time must be after opening time.")
    if not payload.days_of_week or not all(1 <= d <= 7 for d in payload.days_of_week):
        raise HTTPException(status_code=400, detail="Working days must be a non-empty list of ISO weekdays (1=Mon..7=Sun).")

    # 5. If route_id provided, verify route belongs to ward
    route_name = None
    route_code = None
    if payload.route_id:
        stmt_r = select(CollectionRoute).where(CollectionRoute.id == payload.route_id, CollectionRoute.ward_id == resolved_ward_id)
        res_r = await db.execute(stmt_r)
        route_obj = res_r.scalars().first()
        if not route_obj:
            raise HTTPException(status_code=404, detail="Assigned route not found in this ward.")
        route_name = route_obj.name
        route_code = route_obj.route_code

    # 6. Deactivate previous active schedules for this worker
    stmt_deact = (
        update(WorkerSchedule)
        .where(WorkerSchedule.worker_id == payload.worker_id, WorkerSchedule.is_active == True)
        .values(is_active=False, effective_to=payload.effective_from or get_kolkata_today(), updated_at=utc_now())
    )
    await db.execute(stmt_deact)

    # 7. Create new active schedule
    new_sched = WorkerSchedule(
        worker_id=payload.worker_id,
        ward_id=resolved_ward_id,
        route_id=payload.route_id,
        days_of_week=payload.days_of_week,
        shift_start_time=payload.shift_start_time,
        shift_end_time=payload.shift_end_time,
        check_in_start_time=payload.check_in_start_time,
        check_in_end_time=payload.check_in_end_time,
        check_out_start_time=payload.check_out_start_time,
        check_out_end_time=payload.check_out_end_time,
        grace_period_minutes=payload.grace_period_minutes,
        effective_from=payload.effective_from or get_kolkata_today(),
        is_active=True,
        created_by=current_user.id,
    )
    db.add(new_sched)

    # 7. Notify worker
    days_names = [["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d - 1] for d in sorted(payload.days_of_week)]
    await create_notification(
        db=db,
        user_id=worker.id,
        title="New Work Schedule Assigned",
        message=f"Shift: {payload.shift_start_time}–{payload.shift_end_time} IST on {', '.join(days_names)}.",
        notification_type="SCHEDULE",
        related_entity_type="WORKER_SCHEDULE",
        related_entity_id=new_sched.id,
    )

    await db.commit()
    await db.refresh(new_sched)

    # Resolve ward name
    stmt_ward = select(Ward.display_name).where(Ward.id == resolved_ward_id)
    res_ward = await db.execute(stmt_ward)
    ward_name = res_ward.scalar_one_or_none()

    return WorkerScheduleResponse(
        id=new_sched.id,
        worker_id=new_sched.worker_id,
        worker_name=worker.full_name,
        worker_email=worker.email,
        ward_id=new_sched.ward_id,
        ward_name=ward_name,
        route_id=new_sched.route_id,
        route_name=route_name,
        route_code=route_code,
        days_of_week=new_sched.days_of_week,
        shift_start_time=new_sched.shift_start_time,
        shift_end_time=new_sched.shift_end_time,
        check_in_start_time=new_sched.check_in_start_time,
        check_in_end_time=new_sched.check_in_end_time,
        check_out_start_time=new_sched.check_out_start_time,
        check_out_end_time=new_sched.check_out_end_time,
        grace_period_minutes=new_sched.grace_period_minutes,
        timezone=new_sched.timezone,
        effective_from=new_sched.effective_from,
        effective_to=new_sched.effective_to,
        is_active=new_sched.is_active,
        created_at=new_sched.created_at,
        updated_at=new_sched.updated_at,
    )


@router.post(
    "/schedules/overrides",
    response_model=ScheduleOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Date-Specific Schedule Override",
)
async def create_override(
    payload: ScheduleOverrideCreateRequest,
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ScheduleOverrideResponse:
    stmt_w = select(User).where(User.id == payload.worker_id, User.role == UserRole.SANITATION_WORKER.value)
    res_w = await db.execute(stmt_w)
    worker = res_w.scalars().first()
    if not worker:
        raise HTTPException(status_code=404, detail="Sanitation worker not found.")

    if worker.ward_id:
        await verify_ward_access(current_user, worker.ward_id, db)

    # Check for existing override on this date
    stmt_exist = select(ScheduleOverride).where(
        ScheduleOverride.worker_id == payload.worker_id,
        ScheduleOverride.override_date == payload.override_date,
    )
    res_exist = await db.execute(stmt_exist)
    existing = res_exist.scalars().first()

    if existing:
        existing.override_type = payload.override_type
        existing.shift_start_time = payload.shift_start_time
        existing.shift_end_time = payload.shift_end_time
        existing.check_in_start_time = payload.check_in_start_time
        existing.check_in_end_time = payload.check_in_end_time
        existing.reason = payload.reason
        existing.created_by = current_user.id
        existing.updated_at = utc_now()
        override = existing
    else:
        override = ScheduleOverride(
            worker_id=payload.worker_id,
            override_date=payload.override_date,
            override_type=payload.override_type,
            shift_start_time=payload.shift_start_time,
            shift_end_time=payload.shift_end_time,
            check_in_start_time=payload.check_in_start_time,
            check_in_end_time=payload.check_in_end_time,
            reason=payload.reason,
            created_by=current_user.id,
        )
        db.add(override)

    # Notify worker
    type_display = payload.override_type.replace("_", " ").title()
    await create_notification(
        db=db,
        user_id=worker.id,
        title=f"Schedule Override: {type_display}",
        message=f"Date {payload.override_date}: {type_display}. Reason: {payload.reason or 'Supervisor operational adjustment'}.",
        notification_type="SCHEDULE",
    )

    await db.commit()
    await db.refresh(override)

    return ScheduleOverrideResponse(
        id=override.id,
        worker_id=override.worker_id,
        override_date=override.override_date,
        override_type=override.override_type,
        shift_start_time=override.shift_start_time,
        shift_end_time=override.shift_end_time,
        check_in_start_time=override.check_in_start_time,
        check_in_end_time=override.check_in_end_time,
        reason=override.reason,
        created_at=override.created_at,
    )
