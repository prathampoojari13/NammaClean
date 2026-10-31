"""
Public Read-Only Map API for NammaClean citizen dashboard.
Exposes explicitly published vehicles, collection points, routes, and aggregate summary.
Strictly omits private operational identifiers and redacts stale vehicle locations.
"""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.vehicle import Vehicle
from app.models.collection_point import CollectionPoint
from app.models.route import CollectionRoute, RouteStop
from app.schemas.public_map import (
    PublicVehicleResponse,
    PublicCollectionPointResponse,
    PublicRouteResponse,
    PublicMapSummaryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/map", tags=["Public Map"])


@router.get(
    "/vehicles",
    response_model=List[PublicVehicleResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Published Fleet Vehicles",
    description="Returns public-safe vehicle locations for explicitly published vehicles. Stale locations are redacted.",
)
async def get_public_vehicles(
    ward_id: Optional[uuid.UUID] = Query(default=None, description="Optional ward filter"),
    limit: int = Query(default=100, ge=1, le=500, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
) -> List[PublicVehicleResponse]:
    """
    Returns only vehicles explicitly approved for public display (`is_published == True`).
    Omits registration numbers, driver IDs, and worker personal info.
    If location telemetry is older than VEHICLE_FRESHNESS_MINUTES, coordinates are redacted.
    """
    stmt = (
        select(Vehicle)
        .where(
            Vehicle.is_published.is_(True),
            Vehicle.current_location.isnot(None),
        )
        .limit(limit)
    )
    if ward_id is not None:
        stmt = stmt.where(Vehicle.assigned_ward_id == ward_id)

    res = await db.execute(stmt)
    vehicles = res.scalars().all()

    return [
        PublicVehicleResponse.from_orm_model(
            v,
            freshness_minutes=settings.VEHICLE_FRESHNESS_MINUTES,
        )
        for v in vehicles
    ]


@router.get(
    "/collection-points",
    response_model=List[PublicCollectionPointResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Published Collection Points",
    description="Returns active, explicitly published waste collection points.",
)
async def get_public_collection_points(
    ward_id: Optional[uuid.UUID] = Query(default=None, description="Optional ward filter"),
    limit: int = Query(default=200, ge=1, le=500, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
) -> List[PublicCollectionPointResponse]:
    """
    Returns collection points that are both active and explicitly approved for public disclosure.
    Includes point type and WGS 84 coordinates.
    """
    stmt = (
        select(CollectionPoint)
        .options(joinedload(CollectionPoint.ward))
        .where(
            CollectionPoint.is_active.is_(True),
            CollectionPoint.is_published.is_(True),
        )
        .limit(limit)
    )
    if ward_id is not None:
        stmt = stmt.where(CollectionPoint.ward_id == ward_id)

    res = await db.execute(stmt)
    points = res.scalars().all()

    return [PublicCollectionPointResponse.from_orm_model(cp) for cp in points]


@router.get(
    "/routes",
    response_model=List[PublicRouteResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Published Collection Routes",
    description="Returns active, explicitly published collection routes with ordered stops.",
)
async def get_public_routes(
    ward_id: Optional[uuid.UUID] = Query(default=None, description="Optional ward filter"),
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
) -> List[PublicRouteResponse]:
    """
    Returns active, approved routes with LineString coordinates and ordered stops.
    Excludes unpublished or internal operational routes.
    """
    stmt = (
        select(CollectionRoute)
        .options(
            joinedload(CollectionRoute.ward),
            selectinload(CollectionRoute.stops).joinedload(RouteStop.collection_point),
        )
        .where(
            CollectionRoute.is_active.is_(True),
            CollectionRoute.is_published.is_(True),
        )
        .limit(limit)
    )
    if ward_id is not None:
        stmt = stmt.where(CollectionRoute.ward_id == ward_id)

    res = await db.execute(stmt)
    routes = res.scalars().all()

    return [PublicRouteResponse.from_orm_model(r) for r in routes]


@router.get(
    "/summary",
    response_model=PublicMapSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Public Map Dashboard Summary",
    description="Returns aggregate counts of published collection points, routes, and live fresh vehicles.",
)
async def get_public_map_summary(
    ward_id: Optional[uuid.UUID] = Query(default=None, description="Optional ward filter"),
    db: AsyncSession = Depends(get_db),
) -> PublicMapSummaryResponse:
    """
    Returns civic metrics suitable for map widgets and dashboards.
    Vehicles are counted as active live vehicles ONLY if their position was recorded
    within the freshness threshold (VEHICLE_FRESHNESS_MINUTES). Stale positions are never counted.
    """
    now = datetime.now(timezone.utc)
    freshness_cutoff = now - timedelta(minutes=settings.VEHICLE_FRESHNESS_MINUTES)

    # 1. Count published collection points
    cp_stmt = select(func.count(CollectionPoint.id)).where(
        CollectionPoint.is_active.is_(True),
        CollectionPoint.is_published.is_(True),
    )
    if ward_id is not None:
        cp_stmt = cp_stmt.where(CollectionPoint.ward_id == ward_id)
    cp_count = (await db.execute(cp_stmt)).scalar() or 0

    # 2. Count published routes
    route_stmt = select(func.count(CollectionRoute.id)).where(
        CollectionRoute.is_active.is_(True),
        CollectionRoute.is_published.is_(True),
    )
    if ward_id is not None:
        route_stmt = route_stmt.where(CollectionRoute.ward_id == ward_id)
    route_count = (await db.execute(route_stmt)).scalar() or 0

    # 3. Count live fresh vehicles
    veh_stmt = select(func.count(Vehicle.id)).where(
        Vehicle.is_published.is_(True),
        Vehicle.current_location.isnot(None),
        Vehicle.last_seen_at.isnot(None),
        Vehicle.last_seen_at >= freshness_cutoff,
    )
    if ward_id is not None:
        veh_stmt = veh_stmt.where(Vehicle.assigned_ward_id == ward_id)
    live_veh_count = (await db.execute(veh_stmt)).scalar() or 0

    return PublicMapSummaryResponse(
        published_collection_points=cp_count,
        published_routes=route_count,
        active_live_vehicles=live_veh_count,
        freshness_threshold_minutes=settings.VEHICLE_FRESHNESS_MINUTES,
        generated_at=now,
        simulation_active=settings.SIMULATION_ENABLED,
        disclaimer=(
            "NammaClean demonstration platform. Simulated GPS telemetry is used for development "
            "and demonstration purposes. No live BBMP GPS integration is established."
        ),
    )
