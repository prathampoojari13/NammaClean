"""
Public Map API schemas for citizen-facing geospatial views.
Enforces strict field redaction: registration numbers, driver IDs, and worker personal
information are omitted. Only published records are exposed.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from geoalchemy2.shape import to_shape

from app.models.vehicle import Vehicle
from app.models.collection_point import CollectionPoint
from app.models.route import CollectionRoute


class PublicVehicleResponse(BaseModel):
    """
    Public-safe vehicle representation.
    Omits registration number, driver identity, and administrative metadata.
    Redacts location if the telemetry snapshot is older than the freshness threshold.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_type: str
    status: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_seen_at: Optional[datetime] = None
    is_simulated: bool
    is_fresh: bool

    @classmethod
    def from_orm_model(cls, v: Vehicle, freshness_minutes: int = 15) -> "PublicVehicleResponse":
        lat = None
        lon = None
        is_fresh = False

        if v.current_location is not None and v.last_seen_at is not None:
            # Check freshness against threshold
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=freshness_minutes)
            if v.last_seen_at >= cutoff:
                shape = to_shape(v.current_location)
                lon = shape.x
                lat = shape.y
                is_fresh = True

        return cls(
            id=v.id,
            vehicle_type=v.vehicle_type,
            status=v.status,
            latitude=lat,
            longitude=lon,
            last_seen_at=v.last_seen_at,
            is_simulated=bool(v.is_simulated),
            is_fresh=is_fresh,
        )


class PublicCollectionPointResponse(BaseModel):
    """
    Public-safe collection point representation with WGS 84 coordinates.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_id: uuid.UUID
    ward_name: Optional[str] = None
    name: str
    point_type: str
    latitude: float
    longitude: float

    @classmethod
    def from_orm_model(cls, cp: CollectionPoint) -> "PublicCollectionPointResponse":
        shape = to_shape(cp.location)
        ward_display = cp.ward.display_name if cp.ward else None
        return cls(
            id=cp.id,
            ward_id=cp.ward_id,
            ward_name=ward_display,
            name=cp.name,
            point_type=cp.point_type,
            latitude=shape.y,
            longitude=shape.x,
        )


class PublicRouteStopResponse(BaseModel):
    """
    Public stop sequence along a collection route.
    """
    model_config = ConfigDict(from_attributes=True)

    stop_sequence: int
    collection_point_id: uuid.UUID
    collection_point_name: Optional[str] = None
    point_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    planned_arrival_offset_minutes: Optional[int] = None


class PublicRouteResponse(BaseModel):
    """
    Public collection route with GeoJSON LineString coordinates and ordered stops.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_id: uuid.UUID
    ward_name: Optional[str] = None
    name: str
    route_code: Optional[str] = None
    coordinates: List[List[float]]
    stops: List[PublicRouteStopResponse]
    is_simulated: bool

    @classmethod
    def from_orm_model(cls, r: CollectionRoute) -> "PublicRouteResponse":
        shape = to_shape(r.route_path)
        coords = [list(pt) for pt in shape.coords]
        ward_display = r.ward.display_name if r.ward else None

        stops_list: List[PublicRouteStopResponse] = []
        if r.stops:
            for s in r.stops:
                cp_name = None
                pt_type = None
                cp_lat = None
                cp_lon = None
                if s.collection_point:
                    cp_name = s.collection_point.name
                    pt_type = s.collection_point.point_type
                    if s.collection_point.location is not None:
                        cp_shape = to_shape(s.collection_point.location)
                        cp_lon = cp_shape.x
                        cp_lat = cp_shape.y

                stops_list.append(
                    PublicRouteStopResponse(
                        stop_sequence=s.stop_sequence,
                        collection_point_id=s.collection_point_id,
                        collection_point_name=cp_name,
                        point_type=pt_type,
                        latitude=cp_lat,
                        longitude=cp_lon,
                        planned_arrival_offset_minutes=s.planned_arrival_offset_minutes,
                    )
                )

        return cls(
            id=r.id,
            ward_id=r.ward_id,
            ward_name=ward_display,
            name=r.name,
            route_code=r.route_code,
            coordinates=coords,
            stops=stops_list,
            is_simulated=bool(r.is_simulated),
        )


class PublicMapSummaryResponse(BaseModel):
    """
    Summary metrics for public map dashboard.
    """
    model_config = ConfigDict(from_attributes=True)

    published_collection_points: int
    published_routes: int
    active_live_vehicles: int
    freshness_threshold_minutes: int
    generated_at: datetime
    simulation_active: bool
    disclaimer: str
