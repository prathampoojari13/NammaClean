"""
Pydantic schemas for MusterPoint roll-call stations.
"""

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from geoalchemy2.shape import to_shape

from app.models.attendance import MusterPoint


class MusterPointCreateRequest(BaseModel):
    """
    Schema for creating a muster station within an administrative ward.
    Restricted to authorized municipal administrators and ward supervisors.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Descriptive name for the muster station.",
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="WGS 84 latitude coordinate (-90 to +90).",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="WGS 84 longitude coordinate (-180 to +180).",
    )
    geofence_radius_meters: int = Field(
        default=150,
        ge=10,
        le=2000,
        description="Allowed check-in radius from the muster point in meters (10 to 2000).",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Muster point name cannot be blank or contain only whitespace.")
        return stripped


class MusterPointUpdateRequest(BaseModel):
    """
    Schema for partially updating muster point metadata, coordinates, or geofence radius.
    Clients are strictly prohibited from changing the point's ID or assigned ward.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="Updated name for the muster station.",
    )
    latitude: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Updated WGS 84 latitude coordinate (-90 to +90).",
    )
    longitude: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Updated WGS 84 longitude coordinate (-180 to +180).",
    )
    geofence_radius_meters: Optional[int] = Field(
        default=None,
        ge=10,
        le=2000,
        description="Updated allowed check-in radius in meters (10 to 2000).",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Operational activation status.",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Muster point name cannot be blank or contain only whitespace.")
            return stripped
        return v


class MusterPointResponse(BaseModel):
    """
    Public-safe representation of a muster point, exposing explicit
    WGS 84 latitude and longitude coordinates.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_id: uuid.UUID
    name: str
    latitude: float
    longitude: float
    geofence_radius_meters: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, mp: MusterPoint) -> "MusterPointResponse":
        """Converts a MusterPoint ORM entity into a clean Pydantic response."""
        shape = to_shape(mp.location)
        return cls(
            id=mp.id,
            ward_id=mp.ward_id,
            name=mp.name,
            latitude=float(shape.y),
            longitude=float(shape.x),
            geofence_radius_meters=mp.geofence_radius_meters,
            is_active=bool(mp.is_active),
            created_at=mp.created_at,
            updated_at=mp.updated_at,
        )
