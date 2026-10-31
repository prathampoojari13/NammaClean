"""
Public Ward navigation and details endpoints.
Exposes public-safe municipal boundaries and ward metadata.
"""

import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.ward import Ward
from app.schemas.ward import PublicWardResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Wards"])


@router.get(
    "/public/wards",
    response_model=List[PublicWardResponse],
    status_code=status.HTTP_200_OK,
    summary="List Public Administrative Wards",
    description="Returns a stable, public-safe list of administrative wards with optional GeoJSON boundary polygons.",
)
async def list_public_wards(
    include_boundary: bool = Query(
        default=True,
        description="Whether to serialize and include GeoJSON boundary geometry.",
    ),
    db: AsyncSession = Depends(get_db),
) -> List[PublicWardResponse]:
    """
    Returns public ward listings ordered by ward code.
    No authentication required.
    Omits staff assignments and internal identifiers.
    """
    stmt = select(Ward).order_by(Ward.ward_code.asc())
    res = await db.execute(stmt)
    wards = res.scalars().all()

    return [
        PublicWardResponse.from_orm_model(w, include_boundary=include_boundary)
        for w in wards
    ]


@router.get(
    "/wards/{ward_id}",
    response_model=PublicWardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Public Ward Details",
    description="Returns public-safe details and boundary geometry for a specific ward.",
)
async def get_ward(
    ward_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PublicWardResponse:
    """
    Returns details for a single administrative ward.
    No authentication required.
    Returns HTTP 404 if the ward does not exist.
    """
    stmt = select(Ward).where(Ward.id == ward_id)
    res = await db.execute(stmt)
    ward = res.scalars().first()

    if ward is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ward with id '{ward_id}' not found.",
        )

    return PublicWardResponse.from_orm_model(ward, include_boundary=True)
