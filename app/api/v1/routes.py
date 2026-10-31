"""
Route management and ordered collection stop endpoints for NammaClean API v1.
"""

import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.api.deps import get_current_user, verify_ward_access
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.models.ward import Ward
from app.models.collection_point import CollectionPoint
from app.models.route import CollectionRoute, RouteStop
from app.schemas.route import (
    CollectionRouteCreateRequest,
    CollectionRouteUpdateRequest,
    CollectionRouteResponse,
    RouteStopCreateRequest,
    RouteStopUpdateRequest,
    RouteStopReorderRequest,
    RouteStopResponse,
)
from app.schemas.simulation import PublicationUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Collection Routes"])


@router.post(
    "/wards/{ward_id}/routes",
    response_model=CollectionRouteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Ward Collection Route",
    description="Creates a new collection route within a ward. Restricted to Admins and assigned Ward Supervisors.",
)
async def create_route(
    ward_id: uuid.UUID,
    payload: CollectionRouteCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionRouteResponse:
    """
    Creates a new collection route with a WGS 84 LineString path.
    Enforces ward existence and database-backed supervisor assignment.
    """
    stmt = select(Ward).where(Ward.id == ward_id)
    ward_res = await db.execute(stmt)
    ward = ward_res.scalars().first()
    if ward is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ward with id '{ward_id}' not found.",
        )

    await verify_ward_access(current_user, ward_id, db)

    try:
        # Construct LineString WKT: 'LINESTRING(lon1 lat1, lon2 lat2, ...)'
        points_str = ", ".join(f"{pt[0]} {pt[1]}" for pt in payload.coordinates)
        linestring_wkt = f"LINESTRING({points_str})"
        route_geom = WKTElement(linestring_wkt, srid=4326)

        route = CollectionRoute(
            ward_id=ward.id,
            name=payload.name,
            route_code=payload.route_code,
            route_path=route_geom,
            is_active=payload.is_active,
            is_published=payload.is_published,
            is_simulated=payload.is_simulated,
        )
        db.add(route)
        await db.commit()
        await db.refresh(route)

        return CollectionRouteResponse.from_orm_model(route)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to create route: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the collection route.",
        )


@router.get(
    "/wards/{ward_id}/routes",
    response_model=List[CollectionRouteResponse],
    status_code=status.HTTP_200_OK,
    summary="List Ward Collection Routes",
    description="Retrieves all collection routes within a ward with ordered stops. Restricted to Admins and assigned Supervisors.",
)
async def list_ward_routes(
    ward_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CollectionRouteResponse]:
    """
    Lists routes for the specified ward.
    """
    stmt = select(Ward).where(Ward.id == ward_id)
    ward_res = await db.execute(stmt)
    if ward_res.scalars().first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ward with id '{ward_id}' not found.",
        )

    await verify_ward_access(current_user, ward_id, db)

    routes_stmt = (
        select(CollectionRoute)
        .where(CollectionRoute.ward_id == ward_id)
        .options(selectinload(CollectionRoute.stops))
        .order_by(CollectionRoute.name.asc())
    )
    routes_res = await db.execute(routes_stmt)
    routes = routes_res.scalars().all()

    return [CollectionRouteResponse.from_orm_model(r) for r in routes]


@router.post(
    "/routes/{route_id}/stops",
    response_model=RouteStopResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Ordered Stop to Route",
    description="Adds an ordered collection point stop to an existing route. Enforces ward consistency.",
)
async def add_route_stop(
    route_id: uuid.UUID,
    payload: RouteStopCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RouteStopResponse:
    """
    Adds an ordered stop along a collection route.

    Integrity & Ward Consistency:
    - Route must exist (HTTP 404).
    - Supervisor must be assigned to the route's ward (HTTP 403).
    - Collection point must exist (HTTP 404).
    - Collection point MUST belong to the route's ward (HTTP 400).
    - Sequence number must be unique for the route (HTTP 409).
    """
    route_stmt = select(CollectionRoute).where(CollectionRoute.id == route_id)
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    cp_stmt = select(CollectionPoint).where(CollectionPoint.id == payload.collection_point_id)
    cp_res = await db.execute(cp_stmt)
    cp = cp_res.scalars().first()
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection point with id '{payload.collection_point_id}' not found.",
        )

    # Enforce ward consistency: Stop must belong to the route's ward
    if cp.ward_id != route.ward_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Collection point '{cp.id}' belongs to ward '{cp.ward_id}', not route ward '{route.ward_id}'.",
        )

    # Check for duplicate stop sequence
    seq_stmt = (
        select(RouteStop)
        .where(
            RouteStop.route_id == route.id,
            RouteStop.stop_sequence == payload.stop_sequence,
        )
    )
    seq_res = await db.execute(seq_stmt)
    if seq_res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Stop sequence {payload.stop_sequence} already exists for this route.",
        )

    try:
        stop = RouteStop(
            route_id=route.id,
            collection_point_id=cp.id,
            stop_sequence=payload.stop_sequence,
            planned_arrival_offset_minutes=payload.planned_arrival_offset_minutes,
        )
        db.add(stop)
        await db.commit()
        await db.refresh(stop)

        return RouteStopResponse.model_validate(stop)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to add route stop: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while adding the route stop.",
        )


@router.get(
    "/routes/{route_id}",
    response_model=CollectionRouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Collection Route Details",
    description="Retrieves collection route geometry and ordered stops. Restricted to authorized municipal personnel.",
)
async def get_route(
    route_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionRouteResponse:
    """
    Retrieves route details with all ordered stops.
    """
    route_stmt = (
        select(CollectionRoute)
        .where(CollectionRoute.id == route_id)
        .options(selectinload(CollectionRoute.stops))
    )
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    return CollectionRouteResponse.from_orm_model(route)


@router.patch(
    "/routes/{route_id}/publication",
    response_model=CollectionRouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Route Publication Status",
    description="Approves or revokes public map display for a collection route. Restricted to Admins and assigned Ward Supervisors.",
)
async def update_route_publication(
    route_id: uuid.UUID,
    payload: PublicationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionRouteResponse:
    """
    Explicitly approves or revokes route publication for public map views.
    """
    route_stmt = (
        select(CollectionRoute)
        .where(CollectionRoute.id == route_id)
        .options(selectinload(CollectionRoute.stops))
    )
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    route.is_published = payload.is_published
    await db.commit()
    await db.refresh(route)
    return CollectionRouteResponse.from_orm_model(route)


@router.patch(
    "/routes/{route_id}",
    response_model=CollectionRouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Collection Route",
    description="Partially updates collection route metadata, coordinates, or active status. Restricted to Admins and assigned Ward Supervisors.",
)
async def update_route(
    route_id: uuid.UUID,
    payload: CollectionRouteUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionRouteResponse:
    """
    Partially updates route metadata or LineString geometry.

    Security & Authorization:
    - Municipal Admins: Permitted across any ward.
    - Ward Supervisors: Permitted only for their actively assigned wards.
    - Protected flags (is_published, is_simulated) cannot be modified through this generic patch (HTTP 422).
    - Preserves route's ward association.
    - Rejects empty updates (HTTP 400).
    """
    route_stmt = (
        select(CollectionRoute)
        .where(CollectionRoute.id == route_id)
        .options(selectinload(CollectionRoute.stops))
    )
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update.",
        )

    try:
        if "name" in update_data:
            route.name = update_data["name"]
        if "route_code" in update_data:
            route.route_code = update_data["route_code"]
        if "is_active" in update_data:
            route.is_active = update_data["is_active"]
        if "coordinates" in update_data and update_data["coordinates"] is not None:
            points_str = ", ".join(f"{pt[0]} {pt[1]}" for pt in update_data["coordinates"])
            route.route_path = WKTElement(f"LINESTRING({points_str})", srid=4326)

        await db.commit()
        await db.refresh(route)
        return CollectionRouteResponse.from_orm_model(route)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to update route: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the collection route.",
        )


@router.delete(
    "/routes/{route_id}",
    response_model=CollectionRouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate Collection Route",
    description="Deactivates a collection route (sets is_active=False). Restricted to Admins and assigned Ward Supervisors.",
)
async def deactivate_route(
    route_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionRouteResponse:
    """
    Deactivates a collection route by setting is_active = False.
    Preserves audit history and route stops.
    """
    route_stmt = (
        select(CollectionRoute)
        .where(CollectionRoute.id == route_id)
        .options(selectinload(CollectionRoute.stops))
    )
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    route.is_active = False
    await db.commit()
    await db.refresh(route)
    return CollectionRouteResponse.from_orm_model(route)


@router.patch(
    "/routes/{route_id}/stops/{stop_id}",
    response_model=RouteStopResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Route Stop",
    description="Updates route stop sequence, arrival offset, or referenced collection point. Enforces ward consistency.",
)
async def update_route_stop(
    route_id: uuid.UUID,
    stop_id: uuid.UUID,
    payload: RouteStopUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RouteStopResponse:
    """
    Partially updates an individual route stop.
    Enforces ward consistency and sequence uniqueness for the route.
    """
    route_stmt = select(CollectionRoute).where(CollectionRoute.id == route_id)
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    stop_stmt = select(RouteStop).where(
        RouteStop.id == stop_id,
        RouteStop.route_id == route_id,
    )
    stop_res = await db.execute(stop_stmt)
    stop = stop_res.scalars().first()
    if stop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route stop '{stop_id}' not found for route '{route_id}'.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update.",
        )

    # Validate collection point if changed
    if "collection_point_id" in update_data and update_data["collection_point_id"] is not None:
        new_cp_id = update_data["collection_point_id"]
        cp_stmt = select(CollectionPoint).where(CollectionPoint.id == new_cp_id)
        cp_res = await db.execute(cp_stmt)
        cp = cp_res.scalars().first()
        if cp is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection point with id '{new_cp_id}' not found.",
            )
        if cp.ward_id != route.ward_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Collection point '{cp.id}' belongs to ward '{cp.ward_id}', not route ward '{route.ward_id}'.",
            )
        stop.collection_point_id = new_cp_id

    # Validate stop sequence uniqueness if changed
    if "stop_sequence" in update_data and update_data["stop_sequence"] is not None:
        new_seq = update_data["stop_sequence"]
        if new_seq != stop.stop_sequence:
            conflict_stmt = select(RouteStop).where(
                RouteStop.route_id == route_id,
                RouteStop.stop_sequence == new_seq,
                RouteStop.id != stop.id,
            )
            conflict_res = await db.execute(conflict_stmt)
            if conflict_res.scalars().first() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Stop sequence {new_seq} already exists for this route.",
                )
            stop.stop_sequence = new_seq

    if "planned_arrival_offset_minutes" in update_data:
        stop.planned_arrival_offset_minutes = update_data["planned_arrival_offset_minutes"]

    try:
        await db.commit()
        await db.refresh(stop)
        return RouteStopResponse.model_validate(stop)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to update route stop: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the route stop.",
        )


@router.delete(
    "/routes/{route_id}/stops/{stop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Route Stop",
    description="Removes a collection stop from a route. Restricted to Admins and assigned Ward Supervisors.",
)
async def delete_route_stop(
    route_id: uuid.UUID,
    stop_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Removes a collection stop from a route.
    """
    route_stmt = select(CollectionRoute).where(CollectionRoute.id == route_id)
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    stop_stmt = select(RouteStop).where(
        RouteStop.id == stop_id,
        RouteStop.route_id == route_id,
    )
    stop_res = await db.execute(stop_stmt)
    stop = stop_res.scalars().first()
    if stop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route stop '{stop_id}' not found for route '{route_id}'.",
        )

    try:
        await db.delete(stop)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to delete route stop: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the route stop.",
        )


@router.post(
    "/routes/{route_id}/stops/reorder",
    response_model=List[RouteStopResponse],
    status_code=status.HTTP_200_OK,
    summary="Atomically Reorder Route Stops",
    description="Atomically reorders stops along a collection route without sequence constraint violations.",
)
async def reorder_route_stops(
    route_id: uuid.UUID,
    payload: RouteStopReorderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[RouteStopResponse]:
    """
    Atomically reorders stops along a collection route.

    Safety:
    - Verifies route existence and caller authorization.
    - Validates that target sequences are unique in the request.
    - Uses a two-phase positive offset update to strictly avoid violating
      the unique `(route_id, stop_sequence)` constraint during intermediate states.
    """
    route_stmt = select(CollectionRoute).where(CollectionRoute.id == route_id)
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with id '{route_id}' not found.",
        )

    await verify_ward_access(current_user, route.ward_id, db)

    # Validate sequence uniqueness in payload
    target_seqs = [item.stop_sequence for item in payload.stops]
    if len(target_seqs) != len(set(target_seqs)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate stop sequences provided in reorder request.",
        )

    # Fetch existing stops for route
    stops_stmt = select(RouteStop).where(RouteStop.route_id == route.id)
    stops_res = await db.execute(stops_stmt)
    stops = list(stops_res.scalars().all())
    stops_by_id = {s.id: s for s in stops}

    # Verify all payload stop IDs exist on this route
    for item in payload.stops:
        if item.stop_id not in stops_by_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Route stop with id '{item.stop_id}' not found for route '{route_id}'.",
            )

    try:
        # Phase 1: Shift to safe intermediate sequence numbers above any operational sequence
        for item in payload.stops:
            stops_by_id[item.stop_id].stop_sequence = 10000 + item.stop_sequence
        await db.flush()

        # Phase 2: Set final target sequence numbers
        for item in payload.stops:
            stops_by_id[item.stop_id].stop_sequence = item.stop_sequence
        await db.commit()

        # Refresh all stops
        for s in stops:
            await db.refresh(s)

        return [
            RouteStopResponse.model_validate(s)
            for s in sorted(stops, key=lambda s: s.stop_sequence)
        ]
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to reorder route stops: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while reordering route stops.",
        )

