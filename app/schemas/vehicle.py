"""
Pydantic schemas for Vehicle fleet management and GPS telemetry.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from geoalchemy2.shape import to_shape

from app.models.enums import VehicleStatus, VehicleType
from app.models.vehicle import Vehicle, VehiclePosition


class VehicleCreateRequest(BaseModel):
    """
    Schema for registering a new waste fleet vehicle.
    Restricted to Municipal Admins and Ward Supervisors.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    registration_number: str = Field(
        ...,
        min_length=2,
        max_length=50,
        description="Official registration code or plate identifier.",
    )
    vehicle_type: VehicleType = Field(
        ...,
        description="Classification of the municipal vehicle.",
    )
    status: VehicleStatus = Field(
        default=VehicleStatus.IDLE,
        description="Initial operational status.",
    )
    assigned_ward_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional assigned administrative ward ID.",
    )
    assigned_driver_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional assigned driver user ID.",
    )
    is_simulated: bool = Field(
        default=False,
        description="Designates vehicle as demo/simulated fleet record.",
    )
    is_published: bool = Field(
        default=False,
        description="Designates vehicle as approved for public map display.",
    )

    @field_validator("registration_number")
    @classmethod
    def validate_registration_not_blank(cls, v: str) -> str:
        stripped = v.strip().upper()
        if not stripped:
            raise ValueError("Registration number cannot be empty.")
        return stripped


class VehicleUpdateRequest(BaseModel):
    """
    Schema for partial updates to waste collection fleet vehicles.
    Strictly forbids modifications to protected telemetry, publication, or simulation fields.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    status: Optional[VehicleStatus] = Field(
        default=None,
        description="Updated operational lifecycle status.",
    )
    vehicle_type: Optional[VehicleType] = Field(
        default=None,
        description="Updated vehicle classification.",
    )
    registration_number: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=50,
        description="Updated registration identifier (Admins only).",
    )
    assigned_ward_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Updated ward assignment (Admins only). Can be set to null for unassignment.",
    )
    assigned_driver_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Updated driver assignment (Admins only). Can be set to null for unassignment.",
    )

    @field_validator("registration_number")
    @classmethod
    def validate_registration_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip().upper()
            if not stripped:
                raise ValueError("Registration number cannot be empty.")
            return stripped
        return v



class VehicleResponse(BaseModel):
    """
    Vehicle representation returning current operational status and cached location snapshot.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    registration_number: str
    vehicle_type: str
    status: str
    assigned_ward_id: Optional[uuid.UUID] = None
    assigned_driver_id: Optional[uuid.UUID] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_seen_at: Optional[datetime] = None
    is_simulated: bool = False
    is_published: bool = False
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, v: Vehicle) -> "VehicleResponse":
        lat = None
        lon = None
        if v.current_location is not None:
            shape = to_shape(v.current_location)
            lon = shape.x
            lat = shape.y

        return cls(
            id=v.id,
            registration_number=v.registration_number,
            vehicle_type=v.vehicle_type,
            status=v.status,
            assigned_ward_id=v.assigned_ward_id,
            assigned_driver_id=v.assigned_driver_id,
            latitude=lat,
            longitude=lon,
            last_seen_at=v.last_seen_at,
            is_simulated=bool(v.is_simulated),
            is_published=bool(v.is_published),
            created_at=v.created_at,
            updated_at=v.updated_at,
        )


class VehiclePositionCreateRequest(BaseModel):
    """
    Schema for telemetry ingestion.
    Coordinates must follow WGS 84 specifications.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
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
    speed_kmh: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=200.0,
        description="Instantaneous speed in km/h (0 to 200).",
    )
    heading: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=360.0,
        description="Compass bearing in degrees (0 to 360).",
    )
    recorded_at: datetime = Field(
        ...,
        description="Timestamp recorded by vehicle GPS hardware or simulator.",
    )
    is_simulated: bool = Field(
        default=False,
        description="Flag explicitly marking whether telemetry is simulated or hardware-generated.",
    )

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, v: datetime) -> datetime:
        # Normalize timezone to UTC
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        # Reject timestamps in the future with 1 minute clock-skew tolerance
        if v > now_utc + timedelta(minutes=1):
            raise ValueError("recorded_at timestamp cannot be in the future.")
        return v


class VehiclePositionResponse(BaseModel):
    """
    Response schema for persisted vehicle telemetry.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    latitude: float
    longitude: float
    speed_kmh: Optional[float]
    heading: Optional[float]
    recorded_at: datetime
    received_at: datetime
    is_simulated: bool

    @classmethod
    def from_orm_model(cls, pos: VehiclePosition) -> "VehiclePositionResponse":
        shape = to_shape(pos.location)
        return cls(
            id=pos.id,
            vehicle_id=pos.vehicle_id,
            latitude=shape.y,
            longitude=shape.x,
            speed_kmh=pos.speed_kmh,
            heading=pos.heading,
            recorded_at=pos.recorded_at,
            received_at=pos.received_at,
            is_simulated=pos.is_simulated,
        )
