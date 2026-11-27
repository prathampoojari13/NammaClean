"""
Driver management and operational Driver Dashboard endpoints.
Supports official driver lifecycle management, duty sessions, and real-time GPS telemetry ingestion.
"""

import uuid
import logging
from datetime import datetime, date, timezone, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape

from app.api.deps import get_current_user, require_roles, verify_ward_access
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import RateLimiter
from app.core.security import hash_password
from app.models.enums import UserRole, UserStatus, VehicleStatus
from app.models.user import User, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.models.vehicle import Vehicle, VehiclePosition
from app.models.attendance import AttendanceRecord
from app.models.route import CollectionRoute
from app.schemas.driver import (
    DriverCreateRequest,
    DriverUpdateRequest,
    DriverVehicleAssignmentRequest,
    DriverDutyStartRequest,
    DriverDutyEndRequest,
    DriverLocationPingRequest,
    DriverLocationPingResponse,
    DriverAssignedVehicleResponse,
    DriverSummaryResponse,
    DriverMeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drivers", tags=["Drivers"])

# Rate limiters for driver operations
driver_telemetry_limiter = RateLimiter(max_requests=120, window_seconds=60, key_prefix="drv_telemetry")
driver_mgmt_limiter = RateLimiter(max_requests=60, window_seconds=60, key_prefix="drv_mgmt")


def _extract_coords(geometry: Optional[Any]) -> Optional[Dict[str, float]]:
    """Helper to safely extract lat/lon dictionary from PostGIS geometry."""
    if geometry is None:
        return None
    try:
        pt = to_shape(geometry)
        return {"latitude": round(pt.y, 6), "longitude": round(pt.x, 6)}
    except Exception:
        return None


async def _build_driver_summary(
    driver: User,
    vehicle: Optional[Vehicle],
    ward_name: Optional[str],
    db: AsyncSession,
) -> DriverSummaryResponse:
    """Constructs a DriverSummaryResponse with computed duty and freshness metrics."""
    now = datetime.now(timezone.utc)
    freshness_threshold = timedelta(minutes=settings.VEHICLE_FRESHNESS_MINUTES)

    assigned_veh_resp = None
    duty_status = "OFFLINE" if driver.status == UserStatus.DISABLED.value else "IDLE"
    duty_start_time = None
    last_location = None
    last_seen_at = None
    is_stale = True

    if vehicle is not None:
        assigned_veh_resp = DriverAssignedVehicleResponse.from_vehicle(
            vehicle,
            ward_name=ward_name,
            freshness_minutes=settings.VEHICLE_FRESHNESS_MINUTES,
        )
        if vehicle.status == VehicleStatus.ON_DUTY.value:
            duty_status = "ON_DUTY"
            duty_start_time = vehicle.updated_at
        elif vehicle.status == VehicleStatus.IDLE.value:
            duty_status = "IDLE"
        else:
            duty_status = vehicle.status

        last_seen_at = vehicle.last_seen_at
        last_location = _extract_coords(vehicle.current_location)
        if last_seen_at is not None:
            is_stale = (now - last_seen_at) > freshness_threshold

    # Check today's attendance record for duty start timestamp
    today = now.date()
    att_stmt = (
        select(AttendanceRecord)
        .where(
            AttendanceRecord.worker_id == driver.id,
            AttendanceRecord.attendance_date == today,
        )
        .order_by(AttendanceRecord.created_at.desc())
    )
    att_res = await db.execute(att_stmt)
    today_att = att_res.scalars().first()
    if today_att is not None and today_att.check_in_at is not None:
        duty_start_time = today_att.check_in_at
        if today_att.check_out_at is None and duty_status != "OFFLINE":
            duty_status = "ON_DUTY"
        elif today_att.check_out_at is not None and vehicle and vehicle.status != VehicleStatus.ON_DUTY.value:
            duty_status = "IDLE"

    return DriverSummaryResponse(
        id=driver.id,
        email=driver.email,
        full_name=driver.full_name,
        official_id=driver.official_id,
        phone_number=driver.phone_number,
        role=driver.role,
        status=driver.status,
        ward_id=driver.ward_id,
        ward_name=ward_name,
        assigned_vehicle=assigned_veh_resp,
        duty_status=duty_status,
        duty_start_time=duty_start_time,
        last_location=last_location,
        last_seen_at=last_seen_at,
        is_stale=is_stale,
        created_at=driver.created_at,
        updated_at=driver.updated_at,
    )


# ==============================================================================
# OFFICIAL DRIVER MANAGEMENT ENDPOINTS (Municipal Admins & Ward Supervisors)
# ==============================================================================

@router.get(
    "",
    response_model=List[DriverSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List Registered Drivers",
    description="Retrieves registered drivers with duty status, assigned vehicle, and last location. Role-restricted.",
)
async def list_drivers(
    q: Optional[str] = Query(default=None, description="Search query matching full name or email"),
    ward_id: Optional[uuid.UUID] = Query(default=None, description="Optional ward filter"),
    driver_status: Optional[UserStatus] = Query(default=None, alias="status", description="Optional status filter"),
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(driver_mgmt_limiter),
) -> List[DriverSummaryResponse]:
    """
    Lists drivers for administrative monitoring.
    - Ward supervisors are restricted to their assigned wards.
    - Municipal admins have city-wide access.
    - Supports search by driver name or email.
    """
    # 1. Base query for drivers
    stmt = select(User).where(User.role == UserRole.DRIVER.value)

    # 2. Ward Supervisor scoping
    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        assign_stmt = select(UserWardAssignment.ward_id).where(
            UserWardAssignment.user_id == current_user.id,
            UserWardAssignment.revoked_at.is_(None),
        )
        assign_res = await db.execute(assign_stmt)
        active_ward_ids = assign_res.scalars().all()

        if ward_id is not None:
            if ward_id not in active_ward_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You are not assigned to this ward.",
                )
            stmt = stmt.where(User.ward_id == ward_id)
        else:
            if not active_ward_ids:
                return []
            stmt = stmt.where(User.ward_id.in_(active_ward_ids))
    elif current_user.role == UserRole.MUNICIPAL_ADMIN.value:
        if ward_id is not None:
            stmt = stmt.where(User.ward_id == ward_id)

    # 3. Apply search filter
    if q and q.strip():
        search_term = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(search_term),
                User.email.ilike(search_term),
            )
        )

    # 4. Apply status filter
    if driver_status is not None:
        stmt = stmt.where(User.status == driver_status.value)

    stmt = stmt.order_by(User.full_name.asc().nulls_last(), User.email.asc())
    res = await db.execute(stmt)
    drivers = res.scalars().all()

    # 5. Fetch assigned vehicles and wards for summary response
    driver_ids = [d.id for d in drivers]
    veh_map: Dict[uuid.UUID, Vehicle] = {}
    if driver_ids:
        veh_stmt = select(Vehicle).where(Vehicle.assigned_driver_id.in_(driver_ids))
        veh_res = await db.execute(veh_stmt)
        for v in veh_res.scalars().all():
            if v.assigned_driver_id:
                veh_map[v.assigned_driver_id] = v

    ward_ids = {d.ward_id for d in drivers if d.ward_id}
    for v in veh_map.values():
        if v.assigned_ward_id:
            ward_ids.add(v.assigned_ward_id)

    ward_name_map: Dict[uuid.UUID, str] = {}
    if ward_ids:
        w_stmt = select(Ward).where(Ward.id.in_(ward_ids))
        w_res = await db.execute(w_stmt)
        for w in w_res.scalars().all():
            ward_name_map[w.id] = w.display_name

    # 6. Build summary responses
    summaries = []
    for d in drivers:
        veh = veh_map.get(d.id)
        w_name = ward_name_map.get(d.ward_id) if d.ward_id else None
        if not w_name and veh and veh.assigned_ward_id:
            w_name = ward_name_map.get(veh.assigned_ward_id)
        summary = await _build_driver_summary(d, veh, w_name, db)
        summaries.append(summary)

    return summaries


@router.post(
    "",
    response_model=DriverSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Driver Account",
    description="Provisions a new Driver account and optionally assigns an initial vehicle and ward. Role-restricted.",
)
async def create_driver(
    payload: DriverCreateRequest,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(driver_mgmt_limiter),
) -> DriverSummaryResponse:
    """
    Registers a new driver.
    - Role is strictly forced to DRIVER by the backend.
    - Rejects duplicate email addresses with HTTP 409 Conflict.
    - Passwords are securely hashed with Argon2id.
    - If vehicle_id is provided, assigns vehicle to the newly created driver.
    """
    # 1. Ward Supervisor authorization check
    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        if payload.ward_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisors must assign created drivers to an active ward they supervise.",
            )
        await verify_ward_access(current_user, payload.ward_id, db)

    # 2. Check for duplicate email
    dup_stmt = select(User).where(User.email == payload.email)
    dup_res = await db.execute(dup_stmt)
    if dup_res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # 3. Validate ward existence if provided
    ward_obj: Optional[Ward] = None
    if payload.ward_id is not None:
        w_stmt = select(Ward).where(Ward.id == payload.ward_id)
        w_res = await db.execute(w_stmt)
        ward_obj = w_res.scalars().first()
        if ward_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ward with id '{payload.ward_id}' not found.",
            )

    # 4. Validate vehicle existence if provided
    vehicle_obj: Optional[Vehicle] = None
    if payload.vehicle_id is not None:
        v_stmt = select(Vehicle).where(Vehicle.id == payload.vehicle_id)
        v_res = await db.execute(v_stmt)
        vehicle_obj = v_res.scalars().first()
        if vehicle_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle with id '{payload.vehicle_id}' not found.",
            )
        if current_user.role == UserRole.WARD_SUPERVISOR.value and vehicle_obj.assigned_ward_id != payload.ward_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot assign a vehicle that does not belong to your supervised ward.",
            )

    # 5. Create Driver account with forced DRIVER role
    plain_password = payload.password.get_secret_value()
    pwd_hash = hash_password(plain_password)
    new_driver = User(
        id=uuid.uuid4(),
        email=payload.email,
        password_hash=pwd_hash,
        role=UserRole.DRIVER.value,  # Enforce backend assignment
        status=payload.status.value,
        full_name=payload.full_name,
        official_id=payload.official_id,
        phone_number=payload.phone_number,
        ward_id=payload.ward_id,
    )
    db.add(new_driver)

    # 6. Assign vehicle if provided
    if vehicle_obj is not None:
        vehicle_obj.assigned_driver_id = new_driver.id

    # 7. Record ward assignment if ward provided
    if payload.ward_id is not None:
        assignment = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=new_driver.id,
            ward_id=payload.ward_id,
            assigned_at=utc_now(),
        )
        db.add(assignment)

    try:
        await db.commit()
        await db.refresh(new_driver)
        if vehicle_obj is not None:
            await db.refresh(vehicle_obj)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to create driver account: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the driver account.",
        )

    w_name = ward_obj.display_name if ward_obj else None
    return await _build_driver_summary(new_driver, vehicle_obj, w_name, db)


@router.patch(
    "/{driver_id}",
    response_model=DriverSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Driver Account or Status",
    description="Updates driver profile, activation status, or assigned vehicle/ward. Role-restricted.",
)
async def update_driver(
    driver_id: uuid.UUID,
    payload: DriverUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(driver_mgmt_limiter),
) -> DriverSummaryResponse:
    """
    Updates driver metadata, activation status (ACTIVE/DISABLED), or vehicle/ward assignment.
    """
    stmt = select(User).where(User.id == driver_id, User.role == UserRole.DRIVER.value)
    res = await db.execute(stmt)
    driver = res.scalars().first()
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Driver with id '{driver_id}' not found.",
        )

    # Ward Supervisor authorization
    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        if driver.ward_id is not None:
            await verify_ward_access(current_user, driver.ward_id, db)

    update_data = payload.model_dump(exclude_unset=True)

    if "full_name" in update_data and update_data["full_name"] is not None:
        driver.full_name = update_data["full_name"]

    if "status" in update_data and update_data["status"] is not None:
        driver.status = update_data["status"].value
        if driver.status == UserStatus.DISABLED.value:
            # If driver is disabled, ensure any currently on-duty vehicle is reset to IDLE
            v_curr_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == driver.id)
            v_curr_res = await db.execute(v_curr_stmt)
            curr_v = v_curr_res.scalars().first()
            if curr_v and curr_v.status == VehicleStatus.ON_DUTY.value:
                curr_v.status = VehicleStatus.IDLE.value

    if "ward_id" in update_data:
        new_ward_id = update_data["ward_id"]
        if new_ward_id is not None:
            w_stmt = select(Ward).where(Ward.id == new_ward_id)
            w_res = await db.execute(w_stmt)
            if w_res.scalars().first() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Ward with id '{new_ward_id}' not found.",
                )
            if current_user.role == UserRole.WARD_SUPERVISOR.value:
                await verify_ward_access(current_user, new_ward_id, db)
            driver.ward_id = new_ward_id
        else:
            driver.ward_id = None

    # Handle vehicle reassignment
    if "vehicle_id" in update_data:
        target_veh_id = update_data["vehicle_id"]
        # 1. Unassign current vehicle if any
        unassign_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == driver.id)
        unassign_res = await db.execute(unassign_stmt)
        for prev_v in unassign_res.scalars().all():
            prev_v.assigned_driver_id = None

        # 2. Assign new vehicle if provided
        if target_veh_id is not None:
            new_v_stmt = select(Vehicle).where(Vehicle.id == target_veh_id)
            new_v_res = await db.execute(new_v_stmt)
            new_v = new_v_res.scalars().first()
            if new_v is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Vehicle with id '{target_veh_id}' not found.",
                )
            new_v.assigned_driver_id = driver.id

    driver.updated_at = utc_now()

    await db.commit()
    await db.refresh(driver)

    # Fetch updated assigned vehicle
    veh_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == driver.id)
    veh_res = await db.execute(veh_stmt)
    assigned_vehicle = veh_res.scalars().first()

    ward_name = None
    if driver.ward_id:
        w_stmt = select(Ward).where(Ward.id == driver.ward_id)
        w_res = await db.execute(w_stmt)
        w_obj = w_res.scalars().first()
        ward_name = w_obj.display_name if w_obj else None

    return await _build_driver_summary(driver, assigned_vehicle, ward_name, db)


@router.post(
    "/{driver_id}/assign-vehicle",
    response_model=DriverSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign or Reassign Vehicle to Driver",
    description="Explicit vehicle assignment/reassignment endpoint for municipal fleet dispatch.",
)
async def assign_vehicle_to_driver(
    driver_id: uuid.UUID,
    payload: DriverVehicleAssignmentRequest,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(driver_mgmt_limiter),
) -> DriverSummaryResponse:
    """
    Assigns or unassigns a vehicle for a driver.
    """
    stmt = select(User).where(User.id == driver_id, User.role == UserRole.DRIVER.value)
    res = await db.execute(stmt)
    driver = res.scalars().first()
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Driver with id '{driver_id}' not found.",
        )

    # Unassign current vehicle
    unassign_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == driver.id)
    unassign_res = await db.execute(unassign_stmt)
    for prev_v in unassign_res.scalars().all():
        prev_v.assigned_driver_id = None

    assigned_vehicle = None
    if payload.vehicle_id is not None:
        v_stmt = select(Vehicle).where(Vehicle.id == payload.vehicle_id)
        v_res = await db.execute(v_stmt)
        assigned_vehicle = v_res.scalars().first()
        if assigned_vehicle is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle with id '{payload.vehicle_id}' not found.",
            )
        if current_user.role == UserRole.WARD_SUPERVISOR.value and assigned_vehicle.assigned_ward_id is not None:
            await verify_ward_access(current_user, assigned_vehicle.assigned_ward_id, db)

        assigned_vehicle.assigned_driver_id = driver.id

    driver.updated_at = utc_now()
    await db.commit()
    await db.refresh(driver)
    if assigned_vehicle:
        await db.refresh(assigned_vehicle)

    ward_name = None
    if driver.ward_id:
        w_stmt = select(Ward).where(Ward.id == driver.ward_id)
        w_res = await db.execute(w_stmt)
        w_obj = w_res.scalars().first()
        ward_name = w_obj.display_name if w_obj else None

    return await _build_driver_summary(driver, assigned_vehicle, ward_name, db)


# ==============================================================================
# DRIVER DASHBOARD ENDPOINTS (Authenticated Driver Operations)
# ==============================================================================

@router.get(
    "/me",
    response_model=DriverMeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Driver Profile & Assigned Fleet Vehicle",
    description="Returns authenticated driver profile, assigned vehicle, active duty status, and ward/route info.",
)
async def get_driver_me(
    current_user: User = Depends(require_roles(UserRole.DRIVER)),
    db: AsyncSession = Depends(get_db),
) -> DriverMeResponse:
    """
    Returns the authenticated driver's operational context:
    - Assigned vehicle details (registration, type, status, location snapshot).
    - Duty status (ON_DUTY / IDLE) and duty start time.
    - Assigned ward details and scheduled collection route if available.
    """
    # 1. Fetch assigned vehicle
    v_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == current_user.id)
    v_res = await db.execute(v_stmt)
    vehicle = v_res.scalars().first()

    # 2. Fetch assigned ward
    ward_info = None
    target_ward_id = vehicle.assigned_ward_id if vehicle and vehicle.assigned_ward_id else current_user.ward_id
    ward_name = None
    if target_ward_id:
        w_stmt = select(Ward).where(Ward.id == target_ward_id)
        w_res = await db.execute(w_stmt)
        ward_obj = w_res.scalars().first()
        if ward_obj:
            ward_name = ward_obj.display_name
            ward_info = {
                "id": str(ward_obj.id),
                "ward_code": ward_obj.ward_code,
                "display_name": ward_obj.display_name,
            }

    # 3. Fetch scheduled route for ward if available
    route_info = None
    if target_ward_id:
        r_stmt = (
            select(CollectionRoute)
            .where(
                CollectionRoute.ward_id == target_ward_id,
                CollectionRoute.is_active.is_(True),
            )
            .order_by(CollectionRoute.created_at.desc())
        )
        r_res = await db.execute(r_stmt)
        route_obj = r_res.scalars().first()
        if route_obj:
            route_info = {
                "id": str(route_obj.id),
                "name": route_obj.name,
                "route_code": route_obj.route_code,
                "is_active": route_obj.is_active,
            }

    # 4. Build driver summary
    driver_summary = await _build_driver_summary(current_user, vehicle, ward_name, db)

    assigned_veh_resp = None
    if vehicle:
        assigned_veh_resp = DriverAssignedVehicleResponse.from_vehicle(
            vehicle,
            ward_name=ward_name,
            freshness_minutes=settings.VEHICLE_FRESHNESS_MINUTES,
        )

    return DriverMeResponse(
        driver=driver_summary,
        assigned_vehicle=assigned_veh_resp,
        assigned_ward=ward_info,
        assigned_route=route_info,
        duty_status=driver_summary.duty_status,
        duty_start_time=driver_summary.duty_start_time,
    )


@router.post(
    "/me/duty/start",
    response_model=DriverMeResponse,
    status_code=status.HTTP_200_OK,
    summary="Start Driver Duty Session",
    description="Transitions assigned vehicle to ON_DUTY, logs shift start timestamp, and records optional starting GPS position.",
)
async def start_driver_duty(
    payload: DriverDutyStartRequest = DriverDutyStartRequest(),
    current_user: User = Depends(require_roles(UserRole.DRIVER)),
    db: AsyncSession = Depends(get_db),
) -> DriverMeResponse:
    """
    Starts an active duty session for the authenticated driver:
    - Enforces that an authorized vehicle is actively assigned.
    - Prevents duplicate active sessions.
    - Sets vehicle status to ON_DUTY.
    - Atomically updates starting location if coordinates are supplied.
    """
    # 1. Verify driver is assigned to a vehicle
    v_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == current_user.id)
    v_res = await db.execute(v_stmt)
    vehicle = v_res.scalars().first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No vehicle is currently assigned to your account. An authorized official must assign a vehicle before starting duty.",
        )

    # 2. Check if already ON_DUTY
    if vehicle.status == VehicleStatus.ON_DUTY.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duty session is already active.",
        )

    now = utc_now()

    # 3. Set vehicle to ON_DUTY
    vehicle.status = VehicleStatus.ON_DUTY.value
    vehicle.updated_at = now

    # 4. Optional starting location ping
    if payload.latitude is not None and payload.longitude is not None:
        point_geom = WKTElement(f"POINT({payload.longitude} {payload.latitude})", srid=4326)
        position = VehiclePosition(
            id=uuid.uuid4(),
            vehicle_id=vehicle.id,
            location=point_geom,
            recorded_at=now,
            received_at=now,
            is_simulated=False,
        )
        db.add(position)
        vehicle.current_location = point_geom
        vehicle.last_seen_at = now
        vehicle.is_simulated = False

    # 5. Record daily attendance shift
    today = now.date()
    ward_id = vehicle.assigned_ward_id or current_user.ward_id
    if not ward_id:
        w_stmt = select(Ward.id).limit(1)
        w_res = await db.execute(w_stmt)
        ward_id = w_res.scalar_one_or_none()

    if ward_id:
        att_stmt = select(AttendanceRecord).where(
            AttendanceRecord.worker_id == current_user.id,
            AttendanceRecord.attendance_date == today,
        )
        att_res = await db.execute(att_stmt)
        att_rec = att_res.scalars().first()
        if att_rec is None:
            att_rec = AttendanceRecord(
                id=uuid.uuid4(),
                worker_id=current_user.id,
                ward_id=ward_id,
                attendance_date=today,
                check_in_at=now,
                check_in_location=point_geom if (payload.latitude is not None and payload.longitude is not None) else None,
                check_in_accuracy_meters=payload.accuracy_meters,
                status="PRESENT",
            )
            db.add(att_rec)
        elif att_rec.check_in_at is None:
            att_rec.check_in_at = now
            if payload.latitude is not None and payload.longitude is not None:
                att_rec.check_in_location = point_geom
            att_rec.check_in_accuracy_meters = payload.accuracy_meters
            att_rec.status = "PRESENT"

    await db.commit()
    await db.refresh(vehicle)
    await db.refresh(current_user)

    return await get_driver_me(current_user=current_user, db=db)


@router.post(
    "/me/duty/end",
    response_model=DriverMeResponse,
    status_code=status.HTTP_200_OK,
    summary="End Driver Duty Session",
    description="Transitions assigned vehicle from ON_DUTY to IDLE and logs shift check-out timestamp.",
)
async def end_driver_duty(
    payload: DriverDutyEndRequest = DriverDutyEndRequest(),
    current_user: User = Depends(require_roles(UserRole.DRIVER)),
    db: AsyncSession = Depends(get_db),
) -> DriverMeResponse:
    """
    Ends the active duty session for the authenticated driver:
    - Rejects if duty is not currently active.
    - Transitions vehicle to IDLE.
    - Records check-out timestamp and post-trip inspection in today's attendance record.
    """
    # 1. Fetch assigned vehicle
    v_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == current_user.id)
    v_res = await db.execute(v_stmt)
    vehicle = v_res.scalars().first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No vehicle is currently assigned to your account.",
        )

    if vehicle.status != VehicleStatus.ON_DUTY.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duty is not currently active.",
        )

    now = utc_now()
    vehicle.status = VehicleStatus.IDLE.value
    vehicle.updated_at = now

    # Record check-out timestamp
    today = now.date()
    att_stmt = select(AttendanceRecord).where(
        AttendanceRecord.worker_id == current_user.id,
        AttendanceRecord.attendance_date == today,
    )
    att_res = await db.execute(att_stmt)
    att_rec = att_res.scalars().first()
    if att_rec is not None:
        att_rec.check_out_at = now
        if payload.latitude is not None and payload.longitude is not None:
            att_rec.check_out_location = WKTElement(f"POINT({payload.longitude} {payload.latitude})", srid=4326)
        if payload.vehicle_condition_notes:
            existing = att_rec.review_notes or ""
            att_rec.review_notes = f"{existing} [Post-trip: {payload.vehicle_condition_notes}]".strip()

    await db.commit()
    await db.refresh(vehicle)
    await db.refresh(current_user)

    return await get_driver_me(current_user=current_user, db=db)


@router.post(
    "/me/location",
    response_model=DriverLocationPingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Driver Real-Time GPS Telemetry",
    description="Records timestamped GPS coordinates from the driver's browser. Enforces active duty and authorized vehicle assignment.",
)
async def record_driver_location(
    payload: DriverLocationPingRequest,
    current_user: User = Depends(require_roles(UserRole.DRIVER)),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(driver_telemetry_limiter),
) -> DriverLocationPingResponse:
    """
    Ingests high-fidelity GPS telemetry from the authenticated driver's phone/browser session:
    - Derives driver identity directly from the signed Bearer session (never trusts client driver ID).
    - Verifies active vehicle assignment.
    - Rejects pings if duty is inactive (driver must start duty first).
    - Ingests position tagged strictly as real (is_simulated = False).
    - Atomically updates vehicle current_location and last_seen_at.
    """
    # 1. Verify assigned vehicle
    v_stmt = select(Vehicle).where(Vehicle.assigned_driver_id == current_user.id)
    v_res = await db.execute(v_stmt)
    vehicle = v_res.scalars().first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No vehicle is currently assigned to your account. Cannot record telemetry.",
        )

    # 2. Verify active duty status
    if vehicle.status != VehicleStatus.ON_DUTY.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Location telemetry is accepted only while duty is active. Please start duty first.",
        )

    # 3. Determine timestamps
    server_now = utc_now()
    recorded_at = payload.recorded_at or server_now
    # Guard against future timestamps (> 5 minutes in future)
    if recorded_at > server_now + timedelta(minutes=5):
        recorded_at = server_now

    try:
        # Longitude is X, Latitude is Y
        point_geom = WKTElement(f"POINT({payload.longitude} {payload.latitude})", srid=4326)

        # 4. Insert historical position record
        pos_id = uuid.uuid4()
        position = VehiclePosition(
            id=pos_id,
            vehicle_id=vehicle.id,
            location=point_geom,
            speed_kmh=payload.speed_kmh,
            heading=payload.heading,
            recorded_at=recorded_at,
            received_at=server_now,
            is_simulated=False,  # Genuine driver phone GPS
        )
        db.add(position)

        # 5. Atomically update vehicle current snapshot if this position is newer
        if vehicle.last_seen_at is None or recorded_at >= vehicle.last_seen_at:
            vehicle.current_location = point_geom
            vehicle.last_seen_at = recorded_at
            vehicle.is_simulated = False  # Mark vehicle live snapshot as genuine telemetry

        await db.commit()

        return DriverLocationPingResponse(
            success=True,
            vehicle_id=vehicle.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            recorded_at=recorded_at,
            received_at=server_now,
            accuracy_meters=payload.accuracy_meters,
            message="GPS location telemetry ingested successfully.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to ingest driver location telemetry: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving GPS location telemetry.",
        )
