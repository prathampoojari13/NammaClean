"""
Pydantic schemas for Driver account management, vehicle assignments, and Driver Dashboard telemetry.
"""

import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, SecretStr, ConfigDict, field_validator
from geoalchemy2.shape import to_shape

from app.models.enums import UserRole, UserStatus, VehicleStatus, VehicleType
from app.models.user import normalize_email

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class DriverCreateRequest(BaseModel):
    """
    Administrator / Supervisor schema for registering a new Driver account.
    The DRIVER role is strictly enforced by the backend and cannot be overridden by clients.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Driver full legal name.",
    )
    email: str = Field(
        ...,
        max_length=255,
        description="Unique personal email address used as the login identifier.",
    )
    password: SecretStr = Field(
        ...,
        description="Password meeting security requirements (12 to 128 characters).",
    )
    ward_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional assigned administrative ward ID.",
    )
    vehicle_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional initial vehicle assignment ID.",
    )
    official_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Government / BBMP Employee or Contractor ID.",
    )
    phone_number: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Contact phone number.",
    )
    status: UserStatus = Field(
        default=UserStatus.ACTIVE,
        description="Account activation status.",
    )

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Email address cannot be empty.")
        normalized = normalize_email(v)
        if not EMAIL_REGEX.match(normalized):
            raise ValueError("Invalid email address format.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, v: SecretStr) -> SecretStr:
        val = v.get_secret_value()
        if len(val) < 12:
            raise ValueError("Password must be at least 12 characters long.")
        if len(val) > 128:
            raise ValueError("Password must not exceed 128 characters.")
        return v


class DriverUpdateRequest(BaseModel):
    """
    Schema for updating driver metadata, activation status, or vehicle/ward assignment.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    full_name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
    )
    status: Optional[UserStatus] = Field(
        default=None,
        description="Update account activation status (ACTIVE or DISABLED).",
    )
    ward_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Update assigned ward.",
    )
    vehicle_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Update assigned vehicle ID (pass None to unassign).",
    )


class DriverVehicleAssignmentRequest(BaseModel):
    """
    Schema for assigning or reassigning a vehicle to a driver.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    vehicle_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Vehicle UUID to assign, or null to unassign current vehicle.",
    )


class DriverDutyStartRequest(BaseModel):
    """
    Payload when driver starts their duty session with pre-trip checklist.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    accuracy_meters: Optional[float] = Field(default=None, ge=0.0)
    tyre_condition_checked: bool = Field(default=True, description="Pre-trip inspection: Tyres inspected and pressure checked.")
    fuel_battery_level_ok: bool = Field(default=True, description="Pre-trip inspection: Fuel or EV battery level adequate.")
    mirrors_lights_checked: bool = Field(default=True, description="Pre-trip inspection: Mirrors, headlamps, and indicators functional.")
    safety_kit_present: bool = Field(default=True, description="Pre-trip inspection: First aid kit and reflective vest present.")
    brakes_checked: bool = Field(default=True, description="Pre-trip inspection: Service brakes and parking brake verified.")
    odometer_start_km: Optional[float] = Field(default=None, ge=0.0, description="Initial vehicle odometer reading.")


class DriverDutyEndRequest(BaseModel):
    """
    Payload when driver ends their duty session with post-trip inspection.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    waste_disposed_at_depot: bool = Field(default=True, description="Post-trip inspection: Waste delivered to transfer station/depot.")
    odometer_end_km: Optional[float] = Field(default=None, ge=0.0, description="Final vehicle odometer reading.")
    vehicle_condition_notes: Optional[str] = Field(default=None, max_length=500, description="End-of-shift vehicle remarks or maintenance flags.")


class DriverLocationPingRequest(BaseModel):
    """
    GPS telemetry update sent from the driver's browser session.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS 84 latitude.")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS 84 longitude.")
    speed_kmh: Optional[float] = Field(default=None, ge=0.0, le=200.0)
    heading: Optional[float] = Field(default=None, ge=0.0, le=360.0)
    accuracy_meters: Optional[float] = Field(default=None, ge=0.0)
    recorded_at: Optional[datetime] = Field(
        default=None,
        description="Client device capture timestamp. Defaults to server UTC now if omitted.",
    )


class DriverAssignedVehicleResponse(BaseModel):
    """
    Summary of the vehicle assigned to a driver.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    registration_number: str
    vehicle_type: str
    status: str
    assigned_ward_id: Optional[uuid.UUID] = None
    ward_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_seen_at: Optional[datetime] = None
    is_published: bool
    is_simulated: bool
    is_fresh: bool = False

    @classmethod
    def from_vehicle(cls, vehicle: Any, ward_name: Optional[str] = None, freshness_minutes: int = 15) -> "DriverAssignedVehicleResponse":
        lat = None
        lon = None
        if vehicle.current_location is not None:
            try:
                pt = to_shape(vehicle.current_location)
                lon = round(pt.x, 6)
                lat = round(pt.y, 6)
            except Exception:
                pass

        is_fresh = False
        if vehicle.last_seen_at is not None:
            now = datetime.now(timezone.utc)
            is_fresh = (now - vehicle.last_seen_at) <= timedelta(minutes=freshness_minutes)

        return cls(
            id=vehicle.id,
            registration_number=vehicle.registration_number,
            vehicle_type=vehicle.vehicle_type,
            status=vehicle.status,
            assigned_ward_id=vehicle.assigned_ward_id,
            ward_name=ward_name,
            latitude=lat,
            longitude=lon,
            last_seen_at=vehicle.last_seen_at,
            is_published=vehicle.is_published,
            is_simulated=vehicle.is_simulated,
            is_fresh=is_fresh,
        )


class DriverSummaryResponse(BaseModel):
    """
    Full driver profile for official management and driver self-inspection.
    Never exposes passwords, hashes, or private credentials.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    official_id: Optional[str] = None
    phone_number: Optional[str] = None
    role: str
    status: str
    ward_id: Optional[uuid.UUID] = None
    ward_name: Optional[str] = None
    assigned_vehicle: Optional[DriverAssignedVehicleResponse] = None
    duty_status: str  # "ON_DUTY" | "IDLE" | "OFFLINE"
    duty_start_time: Optional[datetime] = None
    last_location: Optional[Dict[str, float]] = None
    last_seen_at: Optional[datetime] = None
    is_stale: bool = True
    created_at: datetime
    updated_at: datetime


class DriverMeResponse(BaseModel):
    """
    Dedicated response for authenticated driver dashboard landing.
    """
    model_config = ConfigDict(from_attributes=True)

    driver: DriverSummaryResponse
    assigned_vehicle: Optional[DriverAssignedVehicleResponse] = None
    assigned_ward: Optional[Dict[str, Any]] = None
    assigned_route: Optional[Dict[str, Any]] = None
    duty_status: str
    duty_start_time: Optional[datetime] = None


class DriverLocationPingResponse(BaseModel):
    """
    Response returned after accepting a GPS location update.
    """
    success: bool = True
    vehicle_id: uuid.UUID
    latitude: float
    longitude: float
    recorded_at: datetime
    received_at: datetime
    accuracy_meters: Optional[float] = None
    message: str = "GPS location telemetry ingested successfully."
