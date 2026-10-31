"""
Vehicle fleet management and GPS telemetry ingestion endpoints.
"""

import uuid
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.api.deps import get_current_user, require_roles, verify_ward_access
from app.core.database import get_db
from app.models.enums import UserRole, UserStatus, VehicleStatus, VehicleType
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.vehicle import Vehicle, VehiclePosition, utc_now
from app.schemas.vehicle import (
    VehicleCreateRequest,
    VehicleUpdateRequest,
    VehicleResponse,
    VehiclePositionCreateRequest,
    VehiclePositionResponse,
)
from app.schemas.simulation import PublicationUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vehicles", tags=["Vehicles & Telemetry"])


@router.post(
    "",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Municipal Vehicle",
    description="Registers a new vehicle in the waste collection fleet. Restricted to Municipal Admins and Ward Supervisors.",
)
async def create_vehicle(
    payload: VehicleCreateRequest,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    """
    Registers a new vehicle in the fleet.
    Validates optional assigned ward and driver foreign keys if provided.
    Enforces that Ward Supervisors may only register vehicles in their assigned ward.
    """
    if payload.assigned_ward_id is not None:
        ward_stmt = select(Ward).where(Ward.id == payload.assigned_ward_id)
        ward_res = await db.execute(ward_stmt)
        if ward_res.scalars().first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Assigned ward with id '{payload.assigned_ward_id}' not found.",
            )

    # Ward Supervisor authorization check
    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        if payload.assigned_ward_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisors must assign created vehicles to a ward they are actively assigned to.",
            )
        await verify_ward_access(current_user, payload.assigned_ward_id, db)

    if payload.assigned_driver_id is not None:
        driver_stmt = select(User).where(User.id == payload.assigned_driver_id)
        driver_res = await db.execute(driver_stmt)
        driver = driver_res.scalars().first()
        if driver is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Assigned driver with id '{payload.assigned_driver_id}' not found.",
            )
        if driver.role != UserRole.DRIVER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User '{payload.assigned_driver_id}' is not a DRIVER.",
            )

    # Check for duplicate registration number
    existing_stmt = select(Vehicle).where(Vehicle.registration_number == payload.registration_number)
    existing_res = await db.execute(existing_stmt)
    if existing_res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vehicle with registration number '{payload.registration_number}' already exists.",
        )

    try:
        vehicle = Vehicle(
            registration_number=payload.registration_number,
            vehicle_type=payload.vehicle_type.value,
            status=payload.status.value,
            assigned_ward_id=payload.assigned_ward_id,
            assigned_driver_id=payload.assigned_driver_id,
            is_simulated=payload.is_simulated,
            is_published=payload.is_published,
        )
        db.add(vehicle)
        await db.commit()
        await db.refresh(vehicle)
        return VehicleResponse.from_orm_model(vehicle)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to register vehicle: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while registering the vehicle.",
        )



@router.get(
    "",
    response_model=List[VehicleResponse],
    status_code=status.HTTP_200_OK,
    summary="List Fleet Vehicles",
    description="Retrieves fleet vehicles. Municipal Admins have city-wide access. Ward Supervisors are restricted to active ward assignments.",
)
async def list_vehicles(
    ward_id: Optional[uuid.UUID] = Query(default=None, description="Optional administrative ward filter"),
    vehicle_status: Optional[VehicleStatus] = Query(default=None, alias="status", description="Optional vehicle status filter"),
    vehicle_type: Optional[VehicleType] = Query(default=None, description="Optional vehicle type filter"),
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> List[VehicleResponse]:
    """
    Fleet inventory query endpoint.

    Authorization & Scoping:
    - Municipal Admins: Can view all vehicles city-wide or filter by specific ward.
    - Ward Supervisors: Strictly scoped to wards where they have active assignments (revoked_at IS NULL).
      - If ward_id is supplied, supervisor must be actively assigned to that ward; otherwise HTTP 403 Forbidden.
      - If ward_id is omitted, returns only vehicles in the supervisor's active wards.
      - Never returns NULL-ward vehicles or unassigned wards to supervisors.
    - Other roles: Denied with HTTP 403 Forbidden.
    """
    stmt = select(Vehicle)

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
                    detail="Access denied: Supervisor is not actively assigned to this ward.",
                )
            stmt = stmt.where(Vehicle.assigned_ward_id == ward_id)
        else:
            if not active_ward_ids:
                return []
            stmt = stmt.where(Vehicle.assigned_ward_id.in_(active_ward_ids))
    elif current_user.role == UserRole.MUNICIPAL_ADMIN.value:
        if ward_id is not None:
            stmt = stmt.where(Vehicle.assigned_ward_id == ward_id)

    if vehicle_status is not None:
        stmt = stmt.where(Vehicle.status == vehicle_status.value)
    if vehicle_type is not None:
        stmt = stmt.where(Vehicle.vehicle_type == vehicle_type.value)

    stmt = stmt.order_by(Vehicle.registration_number.asc())
    res = await db.execute(stmt)
    vehicles = res.scalars().all()

    return [VehicleResponse.from_orm_model(v) for v in vehicles]


@router.get(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Vehicle Details",
    description="Retrieves vehicle status and last known location. Accessible by Admins, Supervisors, and assigned Drivers.",
)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    """
    Retrieves vehicle information.
    Restricted to authorized municipal roles or the driver assigned to this vehicle.
    """
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle with id '{vehicle_id}' not found.",
        )

    # Authorization logic
    if current_user.role not in (UserRole.MUNICIPAL_ADMIN.value, UserRole.WARD_SUPERVISOR.value):
        if current_user.role == UserRole.DRIVER.value and vehicle.assigned_driver_id == current_user.id:
            pass  # Authorized driver
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to access this vehicle.",
            )

    return VehicleResponse.from_orm_model(vehicle)


@router.patch(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Vehicle Fleet Record",
    description="Partially updates vehicle operational status, type, registration, or assignments. Role-restricted.",
)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleUpdateRequest,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    """
    Partially updates vehicle metadata.

    Security & Authorization:
    - Municipal Admins: Permitted to update operational fields, registration number, ward, and driver assignments.
    - Ward Supervisors: Permitted to update operational fields (status, vehicle_type) ONLY for vehicles in their active wards.
      Cannot change ward assignment, unassign ward, change driver assignment, or alter registration number.
    - Other roles: Denied with HTTP 403 Forbidden.
    """
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    res = await db.execute(stmt)
    vehicle = res.scalars().first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle with id '{vehicle_id}' not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update.",
        )

    # Ward Supervisor authorization and field restriction check
    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        if vehicle.assigned_ward_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisors cannot modify unassigned vehicles.",
            )
        await verify_ward_access(current_user, vehicle.assigned_ward_id, db)

        if "assigned_ward_id" in update_data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisors are not authorized to modify vehicle ward assignments.",
            )
        if "assigned_driver_id" in update_data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisors are not authorized to modify vehicle driver assignments.",
            )
        if "registration_number" in update_data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisors are not authorized to modify vehicle registration numbers.",
            )

    # Admin validation for assignments and registration numbers
    if current_user.role == UserRole.MUNICIPAL_ADMIN.value:
        if "assigned_ward_id" in update_data:
            new_ward_id = update_data["assigned_ward_id"]
            if new_ward_id is not None:
                w_stmt = select(Ward).where(Ward.id == new_ward_id)
                w_res = await db.execute(w_stmt)
                if w_res.scalars().first() is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Assigned ward with id '{new_ward_id}' not found.",
                    )

        if "assigned_driver_id" in update_data:
            new_driver_id = update_data["assigned_driver_id"]
            if new_driver_id is not None:
                d_stmt = select(User).where(User.id == new_driver_id)
                d_res = await db.execute(d_stmt)
                driver = d_res.scalars().first()
                if driver is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Assigned driver with id '{new_driver_id}' not found.",
                    )
                if driver.role != UserRole.DRIVER.value:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"User '{new_driver_id}' is not a DRIVER.",
                    )
                if driver.status != UserStatus.ACTIVE.value:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"User '{new_driver_id}' is not an ACTIVE driver.",
                    )

        if "registration_number" in update_data:
            new_reg = update_data["registration_number"]
            if new_reg != vehicle.registration_number:
                reg_stmt = select(Vehicle).where(
                    Vehicle.registration_number == new_reg,
                    Vehicle.id != vehicle.id,
                )
                reg_res = await db.execute(reg_stmt)
                if reg_res.scalars().first() is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Vehicle with registration number '{new_reg}' already exists.",
                    )

    try:
        if "status" in update_data:
            vehicle.status = update_data["status"].value if hasattr(update_data["status"], "value") else str(update_data["status"])
        if "vehicle_type" in update_data:
            vehicle.vehicle_type = update_data["vehicle_type"].value if hasattr(update_data["vehicle_type"], "value") else str(update_data["vehicle_type"])
        if "registration_number" in update_data:
            vehicle.registration_number = update_data["registration_number"]
        if "assigned_ward_id" in update_data:
            vehicle.assigned_ward_id = update_data["assigned_ward_id"]
        if "assigned_driver_id" in update_data:
            vehicle.assigned_driver_id = update_data["assigned_driver_id"]

        await db.commit()
        await db.refresh(vehicle)
        return VehicleResponse.from_orm_model(vehicle)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to update vehicle: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the vehicle.",
        )



@router.patch(
    "/{vehicle_id}/publication",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Vehicle Publication Status",
    description="Approves or revokes public map display for a vehicle. Restricted to Admins and assigned Ward Supervisors.",
)
async def update_vehicle_publication(
    vehicle_id: uuid.UUID,
    payload: PublicationUpdateRequest,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    """
    Explicitly approves or revokes publication for public map views.
    """
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    res = await db.execute(stmt)
    vehicle = res.scalars().first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle with id '{vehicle_id}' not found.",
        )

    # Ward Supervisor authorization check
    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        if vehicle.assigned_ward_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisor cannot manage publication of an unassigned vehicle.",
            )
        await verify_ward_access(current_user, vehicle.assigned_ward_id, db)

    vehicle.is_published = payload.is_published
    await db.commit()
    await db.refresh(vehicle)
    return VehicleResponse.from_orm_model(vehicle)


@router.post(
    "/{vehicle_id}/positions",
    response_model=VehiclePositionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Vehicle GPS Position Telemetry",
    description="Ingests timestamped GPS position for a vehicle. Restricted to the assigned driver or authorized municipal officials.",
)
async def ingest_vehicle_position(
    vehicle_id: uuid.UUID,
    payload: VehiclePositionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VehiclePositionResponse:
    """
    Ingests a GPS telemetry update for a vehicle.

    Security & Authorization:
    - Drivers are strictly authorized ONLY for their currently assigned vehicle.
    - Municipal Admins may submit telemetry for any vehicle.
    - Ward Supervisors may submit telemetry ONLY for vehicles in wards they are actively assigned to.
    - Citizens and other roles are rejected with HTTP 403 Forbidden.
    - Unauthenticated requests receive HTTP 401 Unauthorized.

    Data Integrity & Freshness:
    - Verifies the vehicle exists in the database (HTTP 404 if missing).
    - Prevents simulated telemetry from initializing or overwriting genuine vehicles.
    - Constructs WGS 84 Point geometry (longitude=X, latitude=Y, srid=4326).
    - Sets received_at timestamp server-side.
    - Atomically updates vehicle's current_location and last_seen_at ONLY IF
      the reported recorded_at timestamp is >= vehicle.last_seen_at.
      Older telemetry updates are stored in history without overwriting newer snapshots.
    """
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle with id '{vehicle_id}' not found.",
        )

    # Role and assignment authorization check
    if current_user.role == UserRole.DRIVER.value:
        if vehicle.assigned_driver_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to submit telemetry for this vehicle.",
            )
    elif current_user.role == UserRole.MUNICIPAL_ADMIN.value:
        pass  # Municipal dispatch / admin access permitted across all fleet
    elif current_user.role == UserRole.WARD_SUPERVISOR.value:
        if vehicle.assigned_ward_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ward supervisors cannot submit telemetry for an unassigned vehicle.",
            )
        await verify_ward_access(current_user, vehicle.assigned_ward_id, db)
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this resource.",
        )

    try:
        # Longitude is X, Latitude is Y in PostGIS WKT
        point_geom = WKTElement(
            f"POINT({payload.longitude} {payload.latitude})",
            srid=4326,
        )
        server_received_at = utc_now()

        # 1. Create historical position record
        position = VehiclePosition(
            vehicle_id=vehicle.id,
            location=point_geom,
            speed_kmh=payload.speed_kmh,
            heading=payload.heading,
            recorded_at=payload.recorded_at,
            received_at=server_received_at,
            is_simulated=payload.is_simulated,
        )
        db.add(position)

        # 2. Freshness check: Update vehicle's cached snapshot ONLY if this position is newer or first
        # Rule: A simulated position cannot overwrite or initialize a genuine (non-simulated) position snapshot.
        can_update_snapshot = False
        if not vehicle.is_simulated and payload.is_simulated:
            # Under NO circumstances can simulated telemetry initialize or update
            # the live snapshot of a genuine (non-simulated) municipal vehicle.
            can_update_snapshot = False
        elif vehicle.last_seen_at is None or payload.recorded_at >= vehicle.last_seen_at:
            can_update_snapshot = True

        if can_update_snapshot:
            vehicle.current_location = point_geom
            vehicle.last_seen_at = payload.recorded_at
            if vehicle.is_simulated:
                vehicle.is_simulated = payload.is_simulated

        # 3. Commit atomically
        await db.commit()
        await db.refresh(position)

        return VehiclePositionResponse.from_orm_model(position)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to ingest vehicle position: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while ingesting vehicle telemetry.",
        )
