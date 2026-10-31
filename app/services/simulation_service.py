"""
Controlled GPS Simulation Engine for Development and Demonstration.
Enforces that:
1. Simulation must be explicitly enabled via configuration.
2. Only demo/simulated vehicles (is_simulated == True) and routes can be modified.
3. Coordinates are strictly validated and constrained along demo LineStrings.
4. Timestamps are monotonically increasing; snapshots cannot be moved backwards.
5. All telemetry generated is explicitly tagged with is_simulated = True.
"""

import math
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point as ShapelyPoint

from app.core.config import settings
from app.models.vehicle import Vehicle, VehiclePosition
from app.models.route import CollectionRoute, RouteStop
from app.models.collection_point import CollectionPoint
from app.models.ward import Ward
from app.models.enums import VehicleType, VehicleStatus, CollectionPointType
from app.schemas.simulation import (
    SimulatedVehicleStep,
    SimulationTickResponse,
    SeedDemoFleetResponse,
)


class SimulationDisabledError(Exception):
    """Raised when simulation operation is attempted while SIMULATION_ENABLED is False."""
    pass


class NonDemoAssetError(Exception):
    """Raised when simulation is attempted on a non-demo/genuine municipal asset."""
    pass


def _calculate_heading(p1_x: float, p1_y: float, p2_x: float, p2_y: float) -> float:
    """Calculates compass heading in degrees (0 = North, 90 = East) from p1 to p2."""
    dx = p2_x - p1_x
    dy = p2_y - p1_y
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return 0.0
    angle = math.degrees(math.atan2(dx, dy))
    return (angle + 360.0) % 360.0


async def step_simulation(
    db: AsyncSession,
    vehicle_id: Optional[uuid.UUID] = None,
    step_seconds: int = 30,
) -> SimulationTickResponse:
    """
    Executes a single deterministic simulation tick across eligible demo vehicles.
    """
    if not settings.SIMULATION_ENABLED:
        raise SimulationDisabledError("GPS simulation engine is disabled by configuration.")

    # 1. Fetch demo vehicles
    if vehicle_id is not None:
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        res = await db.execute(stmt)
        vehicle = res.scalars().first()
        if vehicle is None:
            raise ValueError(f"Vehicle '{vehicle_id}' not found.")
        if not vehicle.is_simulated:
            raise NonDemoAssetError(
                f"Vehicle '{vehicle_id}' is not designated as demo/simulated data. Simulation rejected."
            )
        vehicles = [vehicle]
    else:
        # Select all demo vehicles
        stmt = select(Vehicle).where(Vehicle.is_simulated.is_(True))
        res = await db.execute(stmt)
        vehicles = list(res.scalars().all())

    if not vehicles:
        return SimulationTickResponse(
            simulated_vehicles_count=0,
            steps=[],
            timestamp=datetime.now(timezone.utc),
        )

    # 2. Fetch demo routes (is_simulated == True)
    route_stmt = select(CollectionRoute).where(
        CollectionRoute.is_simulated.is_(True),
        CollectionRoute.is_active.is_(True),
    )
    route_res = await db.execute(route_stmt)
    demo_routes = list(route_res.scalars().all())
    routes_by_ward = {r.ward_id: r for r in demo_routes}

    steps: List[SimulatedVehicleStep] = []
    now = datetime.now(timezone.utc)

    for v in vehicles:
        # Match route by vehicle's assigned ward, or take the first demo route
        target_route = routes_by_ward.get(v.assigned_ward_id) if v.assigned_ward_id else None
        if target_route is None and demo_routes:
            target_route = demo_routes[0]

        if target_route is None:
            continue  # No demo route available to simulate this vehicle along

        line_shape = to_shape(target_route.route_path)
        total_length = line_shape.length

        if total_length <= 0:
            continue

        # Determine current distance along the route LineString
        if v.current_location is not None:
            curr_shape = to_shape(v.current_location)
            curr_pt = ShapelyPoint(curr_shape.x, curr_shape.y)
            curr_dist = line_shape.project(curr_pt)
        else:
            coords = list(line_shape.coords)
            curr_pt = ShapelyPoint(coords[0][0], coords[0][1])
            curr_dist = 0.0

        # Advance along route LineString based on speed (25 km/h approx 0.002 deg / 30s)
        # Advance proportional to line length and step seconds
        advance_dist = max(total_length * 0.05, 0.002 * (step_seconds / 30.0))
        next_dist = (curr_dist + advance_dist) % total_length
        next_shapely_pt = line_shape.interpolate(next_dist)

        new_lon = float(next_shapely_pt.x)
        new_lat = float(next_shapely_pt.y)

        # Validate coordinate bounds
        if not (-180.0 <= new_lon <= 180.0 and -90.0 <= new_lat <= 90.0):
            continue

        heading = _calculate_heading(curr_pt.x, curr_pt.y, new_lon, new_lat)
        speed_kmh = 25.0

        # Enforce monotonically increasing timestamps: never go backwards
        if v.last_seen_at is not None and v.last_seen_at >= now:
            recorded_at = v.last_seen_at + timedelta(seconds=step_seconds)
        else:
            recorded_at = now

        # Update vehicle location snapshot
        point_geom = WKTElement(f"POINT({new_lon} {new_lat})", srid=4326)
        v.current_location = point_geom
        v.last_seen_at = recorded_at
        v.is_simulated = True

        # Append historical position breadcrumb
        position = VehiclePosition(
            vehicle_id=v.id,
            location=point_geom,
            speed_kmh=speed_kmh,
            heading=heading,
            recorded_at=recorded_at,
            received_at=now,
            is_simulated=True,
        )
        db.add(position)

        steps.append(
            SimulatedVehicleStep(
                vehicle_id=v.id,
                route_id=target_route.id,
                latitude=new_lat,
                longitude=new_lon,
                speed_kmh=speed_kmh,
                heading=heading,
                recorded_at=recorded_at,
            )
        )

    await db.commit()

    return SimulationTickResponse(
        simulated_vehicles_count=len(steps),
        steps=steps,
        timestamp=now,
    )


async def seed_demo_fleet(
    db: AsyncSession,
    ward_id: uuid.UUID,
) -> SeedDemoFleetResponse:
    """
    Creates standard demo route and demo vehicle records in the specified ward.
    Restricted to development/demonstration when SIMULATION_ENABLED is True.
    """
    if not settings.SIMULATION_ENABLED:
        raise SimulationDisabledError("GPS simulation engine is disabled by configuration.")

    # 1. Verify ward existence
    ward_stmt = select(Ward).where(Ward.id == ward_id)
    ward_res = await db.execute(ward_stmt)
    ward = ward_res.scalars().first()
    if ward is None:
        raise ValueError(f"Ward with id '{ward_id}' not found.")

    # 2. Check or create demo route
    demo_route_code = f"DEMO-ROUTE-{ward.ward_code}"
    route_stmt = select(CollectionRoute).where(CollectionRoute.route_code == demo_route_code)
    route_res = await db.execute(route_stmt)
    route = route_res.scalars().first()

    if route is None:
        # Loop LineString around central Bengaluru coordinates (WGS 84: lon lat)
        demo_coords_wkt = (
            "LINESTRING("
            "77.5900 12.9700, "
            "77.5950 12.9750, "
            "77.6000 12.9720, "
            "77.5950 12.9680, "
            "77.5900 12.9700"
            ")"
        )
        route = CollectionRoute(
            ward_id=ward.id,
            name=f"Demo Simulation Corridor - {ward.display_name}",
            route_code=demo_route_code,
            route_path=WKTElement(demo_coords_wkt, srid=4326),
            is_active=True,
            is_published=True,
            is_simulated=True,
        )
        db.add(route)
        await db.flush()

    # 3. Check or create demo vehicle
    demo_reg = f"SIM-{ward.ward_code[:8]}-01"
    veh_stmt = select(Vehicle).where(Vehicle.registration_number == demo_reg)
    veh_res = await db.execute(veh_stmt)
    vehicle = veh_res.scalars().first()

    if vehicle is None:
        initial_point = WKTElement("POINT(77.5900 12.9700)", srid=4326)
        vehicle = Vehicle(
            registration_number=demo_reg,
            vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
            status=VehicleStatus.ON_DUTY.value,
            assigned_ward_id=ward.id,
            current_location=initial_point,
            last_seen_at=datetime.now(timezone.utc),
            is_simulated=True,
            is_published=True,
        )
        db.add(vehicle)
        await db.flush()

    # 4. Check or create demo collection points along the demo route
    demo_points_spec = [
        (
            f"Demo Community Bin - {ward.ward_code}",
            CollectionPointType.COMMUNITY_BIN.value,
            77.5900,
            12.9700,
            1,
            0,
        ),
        (
            f"Demo Door-to-Door Point - {ward.ward_code}",
            CollectionPointType.DOOR_TO_DOOR_PICKUP.value,
            77.5950,
            12.9750,
            2,
            15,
        ),
        (
            f"Demo Commercial Point - {ward.ward_code}",
            CollectionPointType.COMMERCIAL_POINT.value,
            77.6000,
            12.9720,
            3,
            30,
        ),
        (
            f"Demo DWCC - {ward.ward_code}",
            CollectionPointType.DRY_WASTE_COLLECTION_CENTRE.value,
            77.5950,
            12.9680,
            4,
            45,
        ),
    ]

    seeded_points: List[CollectionPoint] = []
    for name, p_type, lon, lat, seq, offset in demo_points_spec:
        cp_stmt = select(CollectionPoint).where(
            CollectionPoint.ward_id == ward.id,
            CollectionPoint.name == name,
        )
        cp_res = await db.execute(cp_stmt)
        cp = cp_res.scalars().first()
        if cp is None:
            cp = CollectionPoint(
                ward_id=ward.id,
                name=name,
                point_type=p_type,
                location=WKTElement(f"POINT({lon} {lat})", srid=4326),
                is_active=True,
                is_published=True,
            )
            db.add(cp)
            await db.flush()
        seeded_points.append(cp)

    # 5. Check or create ordered route stops linking route to demo collection points
    for idx, (name, p_type, lon, lat, seq, offset) in enumerate(demo_points_spec):
        cp = seeded_points[idx]
        stop_stmt = select(RouteStop).where(
            RouteStop.route_id == route.id,
            RouteStop.stop_sequence == seq,
        )
        stop_res = await db.execute(stop_stmt)
        stop = stop_res.scalars().first()
        if stop is None:
            stop = RouteStop(
                route_id=route.id,
                collection_point_id=cp.id,
                stop_sequence=seq,
                planned_arrival_offset_minutes=offset,
            )
            db.add(stop)
            await db.flush()

    await db.commit()

    return SeedDemoFleetResponse(
        ward_id=ward.id,
        vehicle_id=vehicle.id,
        route_id=route.id,
        registration_number=vehicle.registration_number,
        route_code=route.route_code,
        message="Demo simulation fleet, route, collection points, and stops successfully initialized.",
        collection_point_ids=[p.id for p in seeded_points],
        stop_count=len(demo_points_spec),
    )

