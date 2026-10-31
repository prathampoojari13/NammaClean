"""
Pydantic schemas for CollectionRoute and RouteStop resources.
"""

import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from geoalchemy2.shape import to_shape

from app.models.route import CollectionRoute, RouteStop


class RouteStopCreateRequest(BaseModel):
    """
    Schema for adding an ordered collection stop to a route.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    collection_point_id: uuid.UUID = Field(
        ...,
        description="ID of the collection point to stop at.",
    )
    stop_sequence: int = Field(
        ...,
        gt=0,
        description="Positive sequential order along the route (1, 2, 3...).",
    )
    planned_arrival_offset_minutes: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional planned arrival offset from route departure in minutes.",
    )


class RouteStopResponse(BaseModel):
    """
    Response schema for an ordered collection stop along a route.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    route_id: uuid.UUID
    collection_point_id: uuid.UUID
    stop_sequence: int
    planned_arrival_offset_minutes: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class CollectionRouteCreateRequest(BaseModel):
    """
    Schema for defining a new collection route within a ward.
    Restricted to Municipal Admins and assigned Ward Supervisors.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Descriptive route name.",
    )
    route_code: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Optional short identifier or route code.",
    )
    coordinates: List[List[float]] = Field(
        ...,
        min_length=2,
        description="Ordered list of [longitude, latitude] coordinate pairs defining the LineString.",
    )
    is_active: bool = Field(
        default=True,
        description="Operational status flag for the route.",
    )
    is_published: bool = Field(
        default=False,
        description="Whether this route is approved for public display.",
    )
    is_simulated: bool = Field(
        default=False,
        description="Whether this route is designated as simulated demo corridor.",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Route name cannot be empty.")
        return stripped

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, coords: List[List[float]]) -> List[List[float]]:
        if len(coords) < 2:
            raise ValueError("Route LineString must contain at least 2 coordinate pairs.")
        for idx, pt in enumerate(coords):
            if len(pt) != 2:
                raise ValueError(f"Coordinate pair at index {idx} must contain exactly [longitude, latitude].")
            lon, lat = pt[0], pt[1]
            if not (-180.0 <= lon <= 180.0):
                raise ValueError(f"Longitude {lon} at index {idx} is out of bounds (-180 to +180).")
            if not (-90.0 <= lat <= 90.0):
                raise ValueError(f"Latitude {lat} at index {idx} is out of bounds (-90 to +90).")
        return coords


class CollectionRouteResponse(BaseModel):
    """
    Response schema for a collection route, including WGS 84 LineString coordinates
    and ordered stops.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_id: uuid.UUID
    name: str
    route_code: Optional[str] = None
    coordinates: List[List[float]]
    is_active: bool
    is_published: bool = False
    is_simulated: bool = False
    stops: List[RouteStopResponse] = []
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, r: CollectionRoute) -> "CollectionRouteResponse":
        shape = to_shape(r.route_path)
        # Extract coordinates as [[lon, lat], ...]
        coords = [[pt[0], pt[1]] for pt in shape.coords]

        from sqlalchemy import inspect
        ins = inspect(r)
        if "stops" in ins.dict and ins.dict["stops"] is not None:
            ordered_stops = [
                RouteStopResponse.model_validate(s)
                for s in sorted(ins.dict["stops"], key=lambda s: s.stop_sequence)
            ]
        else:
            ordered_stops = []

        return cls(
            id=r.id,
            ward_id=r.ward_id,
            name=r.name,
            route_code=r.route_code,
            coordinates=coords,
            is_active=r.is_active,
            is_published=bool(r.is_published),
            is_simulated=bool(r.is_simulated),
            stops=ordered_stops,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )


class CollectionRouteUpdateRequest(BaseModel):
    """
    Schema for partial updates to a collection route.
    Rejects changes to protected simulation or publication flags.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="Updated route name.",
    )
    route_code: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Updated route code identifier.",
    )
    coordinates: Optional[List[List[float]]] = Field(
        default=None,
        min_length=2,
        description="Updated LineString coordinate pairs [longitude, latitude].",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Updated operational activity status.",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Route name cannot be empty.")
            return stripped
        return v

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, coords: Optional[List[List[float]]]) -> Optional[List[List[float]]]:
        if coords is not None:
            if len(coords) < 2:
                raise ValueError("Route LineString must contain at least 2 coordinate pairs.")
            for idx, pt in enumerate(coords):
                if len(pt) != 2:
                    raise ValueError(f"Coordinate pair at index {idx} must contain exactly [longitude, latitude].")
                lon, lat = pt[0], pt[1]
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError(f"Longitude {lon} at index {idx} is out of bounds (-180 to +180).")
                if not (-90.0 <= lat <= 90.0):
                    raise ValueError(f"Latitude {lat} at index {idx} is out of bounds (-90 to +90).")
        return coords


class RouteStopUpdateRequest(BaseModel):
    """
    Schema for partial update of an individual route stop.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    collection_point_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Updated collection point ID (must belong to route ward).",
    )
    stop_sequence: Optional[int] = Field(
        default=None,
        gt=0,
        description="Updated positive sequential order along the route.",
    )
    planned_arrival_offset_minutes: Optional[int] = Field(
        default=None,
        ge=0,
        description="Updated arrival offset from route departure in minutes.",
    )


class RouteStopReorderItem(BaseModel):
    """
    Single stop sequence specification in a reorder operation.
    """
    model_config = ConfigDict(extra="forbid")

    stop_id: uuid.UUID = Field(
        ...,
        description="ID of the route stop.",
    )
    stop_sequence: int = Field(
        ...,
        gt=0,
        description="Target positive sequence number.",
    )


class RouteStopReorderRequest(BaseModel):
    """
    Schema for atomic reordering of stops along a collection route.
    """
    model_config = ConfigDict(extra="forbid")

    stops: List[RouteStopReorderItem] = Field(
        ...,
        min_length=1,
        description="List of stop sequence mappings to apply atomically.",
    )


