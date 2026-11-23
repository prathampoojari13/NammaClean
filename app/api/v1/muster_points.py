"""
Administrative endpoints for MusterPoint management within administrative wards.
Used by municipal officials and supervisors to configure roll-call locations.
"""

import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape

from app.api.deps import require_roles, verify_ward_access
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.user import User, utc_now
from app.models.ward import Ward
from app.models.attendance import MusterPoint
from app.schemas.muster_point import (
    MusterPointCreateRequest,
    MusterPointUpdateRequest,
    MusterPointResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Muster Points"])


@router.post(
    "/wards/{ward_id}/muster-points",
    response_model=MusterPointResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Ward Muster Point",
    description="Creates a new reporting station for attendance roll-call. Restricted to Municipal Admins and assigned Ward Supervisors.",
)
async def create_muster_point(
    ward_id: uuid.UUID,
    payload: MusterPointCreateRequest,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> MusterPointResponse:
    """
    Creates a new muster point associated with the specified ward.

    Security & Business Rules:
    - Restricted to MUNICIPAL_ADMIN and actively assigned WARD_SUPERVISOR (HTTP 403 otherwise).
    - Unauthenticated callers receive HTTP 401.
    - Validates that the target ward exists (HTTP 404 if missing).
    - Stores location as PostGIS Point geometry with SRID 4326.
    - Correctly maps longitude to X and latitude to Y.
    """
    # 1. Verify target ward existence
    stmt = select(Ward).where(Ward.id == ward_id)
    result = await db.execute(stmt)
    ward = result.scalars().first()
    if ward is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ward with id '{ward_id}' not found.",
        )

    # 2. Enforce ward access
    await verify_ward_access(current_user, ward.id, db)

    try:
        # Note: Longitude corresponds to X, Latitude corresponds to Y in WKT/PostGIS
        point_location = WKTElement(
            f"POINT({payload.longitude} {payload.latitude})",
            srid=4326,
        )

        muster_point = MusterPoint(
            id=uuid.uuid4(),
            ward_id=ward.id,
            name=payload.name,
            location=point_location,
            geofence_radius_meters=payload.geofence_radius_meters,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        db.add(muster_point)
        await db.commit()
        await db.refresh(muster_point)

        return MusterPointResponse.from_orm_model(muster_point)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to create muster point: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the muster point.",
        )


@router.get(
    "/wards/{ward_id}/muster-points",
    response_model=List[MusterPointResponse],
    status_code=status.HTTP_200_OK,
    summary="List Ward Muster Points",
    description="Retrieves muster points configured for a ward. Supports active_only filtering. Restricted to Admins and assigned Supervisors.",
)
async def list_ward_muster_points(
    ward_id: uuid.UUID,
    active_only: bool = Query(
        default=True,
        description="Whether to return only active muster stations.",
    ),
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> List[MusterPointResponse]:
    """
    Lists muster points associated with the specified ward.
    Restricted to authorized municipal personnel assigned to this ward.
    """
    stmt = select(Ward).where(Ward.id == ward_id)
    result = await db.execute(stmt)
    ward = result.scalars().first()
    if ward is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ward with id '{ward_id}' not found.",
        )

    # Enforce ward access
    await verify_ward_access(current_user, ward.id, db)

    query = select(MusterPoint).where(MusterPoint.ward_id == ward_id)
    if active_only:
        query = query.where(MusterPoint.is_active.is_(True))

    query = query.order_by(MusterPoint.name.asc())
    res = await db.execute(query)
    points = res.scalars().all()

    return [MusterPointResponse.from_orm_model(p) for p in points]


@router.get(
    "/muster-points/{muster_point_id}",
    response_model=MusterPointResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Single Muster Point",
    description="Retrieves details of a specific muster point. Enforces ward access authorization.",
)
async def get_muster_point(
    muster_point_id: uuid.UUID,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> MusterPointResponse:
    """
    Retrieves details for a single muster point.
    Requires caller to have administrative access to the muster point's ward.
    """
    stmt = select(MusterPoint).where(MusterPoint.id == muster_point_id)
    res = await db.execute(stmt)
    mp = res.scalars().first()
    if mp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Muster point with id '{muster_point_id}' not found.",
        )

    await verify_ward_access(current_user, mp.ward_id, db)

    return MusterPointResponse.from_orm_model(mp)


@router.patch(
    "/muster-points/{muster_point_id}",
    response_model=MusterPointResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Muster Point",
    description="Partially updates name, coordinates, geofence radius, or active status. Cannot change ID or ward.",
)
async def update_muster_point(
    muster_point_id: uuid.UUID,
    payload: MusterPointUpdateRequest,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> MusterPointResponse:
    """
    Partially updates a muster point.
    - Requires ward-level authorization.
    - Rejects empty updates (HTTP 400).
    - Prohibits changing point ID or ward assignment via extra='forbid'.
    """
    stmt = select(MusterPoint).where(MusterPoint.id == muster_point_id)
    res = await db.execute(stmt)
    mp = res.scalars().first()
    if mp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Muster point with id '{muster_point_id}' not found.",
        )

    await verify_ward_access(current_user, mp.ward_id, db)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update.",
        )

    try:
        if "name" in update_data:
            mp.name = update_data["name"]
        if "geofence_radius_meters" in update_data:
            mp.geofence_radius_meters = update_data["geofence_radius_meters"]
        if "is_active" in update_data:
            mp.is_active = update_data["is_active"]
        if "latitude" in update_data or "longitude" in update_data:
            current_shape = to_shape(mp.location)
            new_lat = update_data.get("latitude", current_shape.y)
            new_lon = update_data.get("longitude", current_shape.x)
            mp.location = WKTElement(f"POINT({new_lon} {new_lat})", srid=4326)

        mp.updated_at = utc_now()
        await db.commit()
        await db.refresh(mp)
        return MusterPointResponse.from_orm_model(mp)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to update muster point: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the muster point.",
        )


@router.delete(
    "/muster-points/{muster_point_id}",
    response_model=MusterPointResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft Deactivate Muster Point",
    description="Soft-deactivates a muster point by setting is_active=False, preserving all historical attendance references.",
)
async def deactivate_muster_point(
    muster_point_id: uuid.UUID,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> MusterPointResponse:
    """
    Soft-deactivates a muster point by setting is_active = False.
    Does NOT physically delete the database row; preserves historical attendance records.
    """
    stmt = select(MusterPoint).where(MusterPoint.id == muster_point_id)
    res = await db.execute(stmt)
    mp = res.scalars().first()
    if mp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Muster point with id '{muster_point_id}' not found.",
        )

    await verify_ward_access(current_user, mp.ward_id, db)

    try:
        mp.is_active = False
        mp.updated_at = utc_now()
        await db.commit()
        await db.refresh(mp)
        return MusterPointResponse.from_orm_model(mp)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to deactivate muster point: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deactivating the muster point.",
        )
