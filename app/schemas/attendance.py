"""
Pydantic v2 schemas for QR-based Pourakarmika attendance.
"""

from enum import Enum
import uuid
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AttendanceQrIssueResponse(BaseModel):
    """Response returned when an authorized municipal official generates a roll-call QR token."""
    model_config = ConfigDict(extra="forbid")

    token: str = Field(
        ...,
        description="High-entropy single-use cryptographic token encoded in the QR code.",
    )
    muster_point_id: uuid.UUID = Field(
        ...,
        description="UUID of the muster station where roll-call is conducted.",
    )
    ward_id: uuid.UUID = Field(
        ...,
        description="Administrative ward of the muster station.",
    )
    issued_at: datetime = Field(
        ...,
        description="Timezone-aware UTC instant when the token was generated.",
    )
    expires_at: datetime = Field(
        ...,
        description="Timezone-aware UTC instant when the token expires (5 minutes from issue).",
    )
    expires_in_seconds: int = Field(
        default=300,
        description="Remaining validity duration in seconds.",
    )


class AttendanceQrCheckInRequest(BaseModel):
    """Payload submitted by a sanitation worker scanning the roll-call QR code."""
    model_config = ConfigDict(extra="forbid")

    qr_token: str = Field(
        ...,
        min_length=16,
        max_length=256,
        description="The scanned single-use QR token.",
    )
    latitude: float = Field(
        ...,
        description="Device latitude coordinate (-90.0 to 90.0).",
    )
    longitude: float = Field(
        ...,
        description="Device longitude coordinate (-180.0 to 180.0).",
    )
    device_timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional device timestamp at scan instant (untrusted client telemetry only; official attendance and token expiry are determined by authoritative server clock).",
    )

    @field_validator("qr_token")
    @classmethod
    def validate_token_non_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("QR token cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90.0 and 90.0 degrees.")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180.0 and 180.0 degrees.")
        return v


class AttendanceQrCheckInResponse(BaseModel):
    """Response returned upon successful QR check-in processing."""
    model_config = ConfigDict(extra="forbid")

    attendance_id: uuid.UUID = Field(..., description="UUID of the created daily AttendanceRecord.")
    worker_id: uuid.UUID = Field(..., description="UUID of the authenticated sanitation worker.")
    ward_id: uuid.UUID = Field(..., description="Ward ID where attendance was recorded.")
    muster_point_id: uuid.UUID = Field(..., description="Muster station UUID.")
    attendance_date: date = Field(..., description="Civic workday date in Asia/Kolkata.")
    check_in_at: datetime = Field(..., description="UTC timestamp of the recorded check-in.")
    status: str = Field(..., description="Attendance status: PRESENT or EXCEPTION_PENDING.")
    distance_meters: float = Field(..., description="Calculated Haversine distance in meters to muster point.")
    is_within_geofence: bool = Field(..., description="Whether worker coordinates were within geofence radius.")
    exception_reason: Optional[str] = Field(default=None, description="Reason if flagged as EXCEPTION_PENDING.")
    message: str = Field(..., description="Human-readable result summary.")


class AttendanceCheckOutRequest(BaseModel):
    """Payload submitted by a sanitation worker recording shift check-out."""
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(
        ...,
        description="Device latitude coordinate (-90.0 to 90.0) at check-out location.",
    )
    longitude: float = Field(
        ...,
        description="Device longitude coordinate (-180.0 to 180.0) at check-out location.",
    )
    ward_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional administrative ward UUID. If omitted, resolved from today's attendance record.",
    )
    muster_point_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional muster point UUID. If omitted, resolved from today's attendance record.",
    )
    device_timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional client telemetry timestamp.",
    )

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90.0 and 90.0 degrees.")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180.0 and 180.0 degrees.")
        return v


class AttendanceCheckOutResponse(BaseModel):
    """Response returned upon successful shift check-out processing."""
    model_config = ConfigDict(extra="forbid")

    attendance_id: uuid.UUID = Field(..., description="UUID of the updated AttendanceRecord.")
    worker_id: uuid.UUID = Field(..., description="UUID of the authenticated sanitation worker.")
    ward_id: uuid.UUID = Field(..., description="Ward ID where attendance was recorded.")
    muster_point_id: Optional[uuid.UUID] = Field(default=None, description="Muster station UUID.")
    attendance_date: date = Field(..., description="Civic workday date in Asia/Kolkata.")
    check_in_at: Optional[datetime] = Field(default=None, description="UTC timestamp of the original check-in.")
    check_out_at: datetime = Field(..., description="UTC timestamp of the recorded check-out.")
    status: str = Field(..., description="Attendance status (e.g. PRESENT or EXCEPTION_PENDING).")
    distance_meters: Optional[float] = Field(default=None, description="Calculated Haversine distance in meters to muster point.")
    is_within_geofence: bool = Field(..., description="Whether check-out coordinates were within geofence radius.")
    exception_reason: Optional[str] = Field(default=None, description="Reason if flagged as EXCEPTION_PENDING.")
    message: str = Field(..., description="Human-readable result summary.")


class AttendanceDailyItemResponse(BaseModel):
    """Item representation of an attendance record within a supervisor's daily ward roster."""
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(..., description="Attendance record UUID.")
    worker_id: uuid.UUID = Field(..., description="Worker UUID.")
    worker_email: Optional[str] = Field(default=None, description="Worker registered email address.")
    ward_id: uuid.UUID = Field(..., description="Ward UUID.")
    muster_point_id: Optional[uuid.UUID] = Field(default=None, description="Muster station UUID.")
    muster_point_name: Optional[str] = Field(default=None, description="Muster station name.")
    attendance_date: date = Field(..., description="Workday date in Asia/Kolkata.")
    check_in_at: Optional[datetime] = Field(default=None, description="UTC check-in timestamp.")
    check_out_at: Optional[datetime] = Field(default=None, description="UTC check-out timestamp.")
    status: str = Field(..., description="Attendance lifecycle status.")
    check_in_distance_meters: Optional[float] = Field(default=None, description="Check-in distance to station.")
    check_out_distance_meters: Optional[float] = Field(default=None, description="Check-out distance to station.")
    exception_reason: Optional[str] = Field(default=None, description="Geofence or audit exception reason.")
    reviewed_by: Optional[uuid.UUID] = Field(default=None, description="Reviewer UUID if reviewed.")
    reviewed_at: Optional[datetime] = Field(default=None, description="UTC review timestamp.")
    review_notes: Optional[str] = Field(default=None, description="Supervisory review notes.")
    created_at: datetime = Field(..., description="Record creation timestamp.")
    updated_at: datetime = Field(..., description="Record last update timestamp.")


class AttendanceDailyRosterResponse(BaseModel):
    """Supervisory daily roster overview for an administrative ward."""
    model_config = ConfigDict(extra="forbid")

    ward_id: uuid.UUID = Field(..., description="Ward UUID.")
    attendance_date: date = Field(..., description="Workday date in Asia/Kolkata.")
    total_count: int = Field(..., description="Total attendance records for the ward and date.")
    present_count: int = Field(..., description="Count of records with status PRESENT.")
    exception_pending_count: int = Field(..., description="Count of records awaiting supervisor exception review.")
    rejected_count: int = Field(..., description="Count of rejected attendance records.")
    records: List[AttendanceDailyItemResponse] = Field(..., description="List of attendance records.")


class AttendanceReviewAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AttendanceReviewRequest(BaseModel):
    """Payload submitted by a supervisor or municipal admin to resolve an attendance exception."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: AttendanceReviewAction = Field(
        ...,
        description="Supervisory review action: 'APPROVE' (resolves to PRESENT) or 'REJECT' (resolves to REJECTED).",
    )
    review_notes: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Explanation or justification for the review decision. Mandatory when action is REJECT.",
    )


class AttendanceReviewResponse(BaseModel):
    """Response returned upon resolving an attendance exception."""
    model_config = ConfigDict(extra="forbid")

    attendance_id: uuid.UUID = Field(..., description="Attendance record UUID.")
    worker_id: uuid.UUID = Field(..., description="Worker UUID.")
    ward_id: uuid.UUID = Field(..., description="Ward UUID.")
    attendance_date: date = Field(..., description="Workday date in Asia/Kolkata.")
    previous_status: str = Field(..., description="Status prior to supervisory review.")
    new_status: str = Field(..., description="Updated status after review.")
    reviewed_by: uuid.UUID = Field(..., description="UUID of supervisor or admin who reviewed the record.")
    reviewed_at: datetime = Field(..., description="UTC timestamp of the review decision.")
    review_notes: Optional[str] = Field(default=None, description="Review justification notes.")
    message: str = Field(..., description="Human-readable result summary.")



# --- Email OTP Attendance Verification Schemas ---

class AttendanceOtpIssueResponse(BaseModel):
    """Response returned when an OTP challenge is issued for worker attendance."""
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(..., description="Unique opaque challenge identifier.")
    expires_in_seconds: int = Field(default=300, description="Expiration TTL in seconds.")
    worker_email: str = Field(..., description="Registered worker email address where OTP was dispatched.")
    message: str = Field(..., description="Status message.")
    dev_otp: Optional[str] = Field(
        default=None,
        description="Local development demonstration OTP code. Strictly omitted/null in production or staging environments.",
    )


class AttendanceOtpVerifyRequest(BaseModel):
    """Payload to verify the entered OTP challenge."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    challenge_id: str = Field(..., description="Active challenge ID.")
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit numeric OTP.")

    @field_validator("otp")
    @classmethod
    def validate_otp_digits(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 6:
            raise ValueError("Verification code must be exactly 6 digits.")
        return v


class AttendanceOtpVerifyResponse(BaseModel):
    """Response returned upon verifying the OTP."""
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(..., description="Challenge ID.")
    verified: bool = Field(..., description="Whether OTP verification succeeded.")
    message: str = Field(..., description="Human-readable result summary.")


class AttendanceOtpCheckInRequest(BaseModel):
    """Payload to complete attendance check-in following verified Email OTP."""
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(..., description="Verified OTP challenge ID.")
    latitude: float = Field(..., description="Device latitude coordinate (-90.0 to 90.0).")
    longitude: float = Field(..., description="Device longitude coordinate (-180.0 to 180.0).")
    ward_id: Optional[uuid.UUID] = Field(default=None, description="Assigned ward UUID.")
    muster_point_id: Optional[uuid.UUID] = Field(default=None, description="Assigned muster point UUID.")
    device_timestamp: Optional[datetime] = Field(default=None, description="Client device timestamp.")

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90.0 and 90.0 degrees.")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180.0 and 180.0 degrees.")
        return v


class WorkerAssignmentResponse(BaseModel):
    """Response containing a worker's active ward assignment and muster stations."""
    model_config = ConfigDict(extra="forbid")

    worker_id: uuid.UUID
    worker_email: str
    ward_id: Optional[uuid.UUID] = None
    ward_number: Optional[int] = None
    ward_name: Optional[str] = None
    muster_point_id: Optional[uuid.UUID] = None
    muster_point_name: Optional[str] = None
    geofence_radius_meters: Optional[int] = None
