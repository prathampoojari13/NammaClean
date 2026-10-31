"""
Administrative endpoints for CollectionPoint management within Wards.
"""

import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.api.deps import get_current_user, verify_ward_access
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.models.ward import Ward
from app.models.collection_point import CollectionPoint
from app.schemas.collection_point import (
    CollectionPointCreateRequest,
    CollectionPointUpdateRequest,
    CollectionPointResponse,
)
from app.schemas.simulation import PublicationUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wards", tags=["Collection Points"])


@router.post(
    "/{ward_id}/collection-points",
    response_model=CollectionPointResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Ward Collection Point",
    description="Creates a new waste collection point inside a specified ward. Restricted to Municipal Admins and assigned Ward Supervisors.",
)
async def create_collection_point(
    ward_id: uuid.UUID,
    payload: CollectionPointCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionPointResponse:
    """
    Creates a new collection point associated with the specified ward.

    Security & Business Rules:
    - Restricted to MUNICIPAL_ADMIN and actively assigned WARD_SUPERVISOR (HTTP 403 otherwise).
    - Requires valid authentication (HTTP 401 for unauthenticated requests).
    - Validates that the target ward exists in the database (HTTP 404 if missing).
    - Stores the location using PostGIS Point geometry with SRID 4326.
    - Accurately maps geographic coordinates (longitude as X, latitude as Y).
    - Manages transaction boundary and rolls back on failure.
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

    # 2. Enforce ward access: Municipal Admin across all wards, Supervisor strictly for assigned ward
    await verify_ward_access(current_user, ward.id, db)

    try:
        # Note: Longitude corresponds to X, Latitude corresponds to Y in WKT/PostGIS
        point_location = WKTElement(
            f"POINT({payload.longitude} {payload.latitude})",
            srid=4326,
        )

        collection_point = CollectionPoint(
            ward_id=ward.id,
            name=payload.name,
            point_type=payload.point_type.value,
            location=point_location,
            is_active=payload.is_active,
            is_published=payload.is_published,
        )

        db.add(collection_point)
        await db.commit()
        await db.refresh(collection_point)

        return CollectionPointResponse.from_orm_model(collection_point)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to create collection point: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the collection point.",
        )


@router.get(
    "/{ward_id}/collection-points",
    response_model=List[CollectionPointResponse],
    status_code=status.HTTP_200_OK,
    summary="List Ward Collection Points",
    description="Retrieves all collection points configured for a ward. Restricted to Municipal Admins and assigned Ward Supervisors.",
)
async def list_ward_collection_points(
    ward_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CollectionPointResponse]:
    """
    Lists all collection points associated with the specified ward.
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

    stmt_points = (
        select(CollectionPoint)
        .where(CollectionPoint.ward_id == ward_id)
        .order_by(CollectionPoint.created_at.asc())
    )
    res_points = await db.execute(stmt_points)
    points = res_points.scalars().all()

    return [CollectionPointResponse.from_orm_model(p) for p in points]


@router.patch(
    "/{ward_id}/collection-points/{collection_point_id}/publication",
    response_model=CollectionPointResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Collection Point Publication Status",
    description="Approves or revokes public map display for a collection point. Restricted to Admins and assigned Ward Supervisors.",
)
async def update_collection_point_publication(
    ward_id: uuid.UUID,
    collection_point_id: uuid.UUID,
    payload: PublicationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionPointResponse:
    """
    Explicitly approves or revokes collection point publication for public map views.
    """
    await verify_ward_access(current_user, ward_id, db)

    stmt = select(CollectionPoint).where(
        CollectionPoint.id == collection_point_id,
        CollectionPoint.ward_id == ward_id,
    )
    res = await db.execute(stmt)
    cp = res.scalars().first()
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection point '{collection_point_id}' not found in ward '{ward_id}'.",
        )

    cp.is_published = payload.is_published
    await db.commit()
    await db.refresh(cp)
    return CollectionPointResponse.from_orm_model(cp)


@router.patch(
    "/{ward_id}/collection-points/{collection_point_id}",
    response_model=CollectionPointResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Ward Collection Point",
    description="Partially updates collection point metadata, coordinates, active status, or ward assignment. Role-restricted.",
)
async def update_collection_point(
    ward_id: uuid.UUID,
    collection_point_id: uuid.UUID,
    payload: CollectionPointUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionPointResponse:
    """
    Partially updates a collection point.

    Security & Authorization:
    - Municipal Admins: Permitted across any ward.
    - Ward Supervisors: Permitted only for their actively assigned wards.
    - Ward Reassignment: If ward_id is updated, caller must be authorized for the target ward.
    - Rejects empty updates (HTTP 400).
    - Rejects unknown fields and protected publication changes (HTTP 422).
    - Returns HTTP 404 if the collection point is not found in the ward.
    """
    await verify_ward_access(current_user, ward_id, db)

    stmt = select(CollectionPoint).where(
        CollectionPoint.id == collection_point_id,
        CollectionPoint.ward_id == ward_id,
    )
    res = await db.execute(stmt)
    cp = res.scalars().first()
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection point '{collection_point_id}' not found in ward '{ward_id}'.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update.",
        )

    # Ward reassignment validation
    if "ward_id" in update_data and update_data["ward_id"] is not None:
        target_ward_id = update_data["ward_id"]
        if target_ward_id != ward_id:
            target_ward_stmt = select(Ward).where(Ward.id == target_ward_id)
            target_ward_res = await db.execute(target_ward_stmt)
            if target_ward_res.scalars().first() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target ward with id '{target_ward_id}' not found.",
                )
            # Enforce caller authorization on target ward
            await verify_ward_access(current_user, target_ward_id, db)
            cp.ward_id = target_ward_id

    try:
        if "name" in update_data:
            cp.name = update_data["name"]
        if "point_type" in update_data:
            val = update_data["point_type"]
            cp.point_type = val.value if hasattr(val, "value") else str(val)
        if "is_active" in update_data:
            cp.is_active = update_data["is_active"]
        if "latitude" in update_data and "longitude" in update_data:
            lat = update_data["latitude"]
            lon = update_data["longitude"]
            if lat is not None and lon is not None:
                cp.location = WKTElement(f"POINT({lon} {lat})", srid=4326)

        await db.commit()
        await db.refresh(cp)
        return CollectionPointResponse.from_orm_model(cp)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to update collection point: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the collection point.",
        )


@router.delete(
    "/{ward_id}/collection-points/{collection_point_id}",
    response_model=CollectionPointResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate Ward Collection Point",
    description="Deactivates a collection point (sets is_active=False). Restricted to Admins and assigned Ward Supervisors.",
)
async def deactivate_collection_point(
    ward_id: uuid.UUID,
    collection_point_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionPointResponse:
    """
    Deactivates a collection point by setting is_active = False.
    Preserves audit history and references.
    """
    await verify_ward_access(current_user, ward_id, db)

    stmt = select(CollectionPoint).where(
        CollectionPoint.id == collection_point_id,
        CollectionPoint.ward_id == ward_id,
    )
    res = await db.execute(stmt)
    cp = res.scalars().first()
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection point '{collection_point_id}' not found in ward '{ward_id}'.",
        )

    cp.is_active = False
    await db.commit()
    await db.refresh(cp)
    return CollectionPointResponse.from_orm_model(cp)

