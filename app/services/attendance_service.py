"""
Foundational Attendance Service for Pourakarmikas (Sanitation Workers).

Handles worker check-in, check-out, geofence proximity verification,
workday date calculation in Asia/Kolkata, and exception lifecycle handling.

Transaction Ownership Convention:
Following project standards (e.g. user_service.py), this service executes
atomic flushes inside savepoints (`session.begin_nested()`). It never calls
`session.commit()` or `session.rollback()`. Transaction boundaries are owned
exclusively by the outer caller (FastAPI request handler, background task, or test).

Security & Telemetry Notice:
GPS coordinates submitted by client devices represent reported telemetry.
Geofence verification checks spatial proximity against designated muster points,
but client-reported coordinates cannot guarantee genuine physical presence
without hardware attestation, supervisor roll-call verification, or QR confirmation.
"""

import math
import uuid
import hashlib
import secrets
from datetime import datetime, date, timezone, timedelta
from typing import Optional, Tuple, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point

from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User, utc_now
from app.models.ward import UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord, AttendanceQrToken


# Timezone Configuration for Indian Standard Time (IST / Asia/Kolkata)
# IST is legally and astronomically UTC+05:30 with no daylight saving time (DST).
# Handles environments where zoneinfo tzdata might be absent (e.g. Windows).
try:
    from zoneinfo import ZoneInfo
    KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


# --- Custom Domain Exceptions ---

class AttendanceServiceError(Exception):
    """Base class for all attendance domain exceptions."""
    pass


class WorkerIneligibleError(AttendanceServiceError):
    """Raised when the user is not found, inactive, or not a sanitation worker."""
    pass


class WardAssignmentError(AttendanceServiceError):
    """Raised when a worker does not have an active assignment to the ward."""
    pass


class MusterPointError(AttendanceServiceError):
    """Raised when a muster point is not found, inactive, or belongs to another ward."""
    pass


class DuplicateAttendanceError(AttendanceServiceError):
    """Raised when an attendance record already exists for the worker on the given workday."""
    pass


class AttendanceNotFoundError(AttendanceServiceError):
    """Raised when check-out is attempted for a non-existent daily attendance record."""
    pass


class DuplicateCheckOutError(AttendanceServiceError):
    """Raised when check-out has already been recorded for the given attendance record."""
    pass


class MissingCheckInError(AttendanceServiceError):
    """Raised when check-out is attempted on an attendance record without a check-in timestamp."""
    pass


class InvalidCoordinateError(AttendanceServiceError):
    """Raised when latitude or longitude fall outside valid geographic bounds."""
    pass


class InvalidAttendanceTimeError(AttendanceServiceError):
    """Raised when check-out timestamp is earlier than check-in timestamp."""
    pass


class InvalidQrTokenError(AttendanceServiceError):
    """Raised when a submitted QR token cannot be found or is malformed."""
    pass


class ExpiredQrTokenError(AttendanceServiceError):
    """Raised when a QR token is scanned after its expiration window (5 minutes)."""
    pass


class QrTokenAlreadyRedeemedError(AttendanceServiceError):
    """Raised when an attempt is made to reuse an already redeemed QR token."""
    pass


class AttendanceNotReviewableError(AttendanceServiceError):
    """Raised when attempting to review an attendance record that is not in EXCEPTION_PENDING state."""
    pass


# --- Pure Helper Functions ---

def hash_qr_token(token: str) -> str:
    """Computes the SHA-256 digest hex string of a raw QR token string."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def normalize_to_utc(dt: Optional[datetime] = None) -> datetime:
    """
    Normalizes a datetime to a timezone-aware UTC datetime instant.
    - If dt is None: returns current UTC timestamp.
    - If dt is naive (tzinfo is None): interprets it as UTC.
    - If dt has another timezone: converts it to UTC.
    """
    if dt is None:
        return utc_now()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_kolkata_workday_date(dt: Optional[datetime] = None) -> date:
    """
    Computes the civic workday date for an instant in Indian Standard Time (Asia/Kolkata).

    Normalizes the input datetime to timezone-aware UTC first, then evaluates
    the workday date in Asia/Kolkata.
    """
    normalized_dt = normalize_to_utc(dt)
    return normalized_dt.astimezone(KOLKATA_TZ).date()


def validate_coordinates(latitude: float, longitude: float) -> None:
    """
    Validates that numeric coordinates conform to WGS 84 geographic bounds.
    Latitude: [-90.0, 90.0], Longitude: [-180.0, 180.0].
    """
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        raise InvalidCoordinateError("Latitude and longitude must be numeric values.")

    if math.isnan(latitude) or math.isnan(longitude) or math.isinf(latitude) or math.isinf(longitude):
        raise InvalidCoordinateError("Coordinates must be finite numeric values.")

    if not (-90.0 <= latitude <= 90.0):
        raise InvalidCoordinateError(f"Latitude {latitude} is out of bounds [-90.0, 90.0].")

    if not (-180.0 <= longitude <= 180.0):
        raise InvalidCoordinateError(f"Longitude {longitude} is out of bounds [-180.0, 180.0].")


def calculate_haversine_distance_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    Computes great-circle distance between two (latitude, longitude) coordinate pairs
    in meters using the Haversine formula on the WGS 84 mean Earth radius (6,371,000 meters).
    """
    R = 6371000.0  # Earth's mean radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    # Clamp a to [0.0, 1.0] to prevent floating-point inaccuracy domain errors near antipodes
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def is_duplicate_attendance_integrity_error(exc: IntegrityError) -> bool:
    """
    Checks if an IntegrityError was caused specifically by the
    'uq_worker_daily_attendance' unique constraint violation.
    Re-raises unrelated integrity failures (foreign keys, check constraints).
    """
    exc_str = str(exc)
    if "uq_worker_daily_attendance" in exc_str:
        return True

    orig = getattr(exc, "orig", None)
    if orig is not None:
        constraint_name = getattr(orig, "constraint_name", None)
        if constraint_name == "uq_worker_daily_attendance":
            return True

        diag = getattr(orig, "diag", None)
        if diag is not None and getattr(diag, "constraint_name", None) == "uq_worker_daily_attendance":
            return True

        if "uq_worker_daily_attendance" in str(orig):
            return True

    return False


def extract_point_coordinates(location: Any) -> Tuple[float, float]:
    """
    Extracts (latitude, longitude) from a PostGIS geometry element or Shapely Point.
    Returns:
        tuple[float, float]: (latitude, longitude)
    """
    if location is None:
        raise ValueError("Geometry location is None.")

    if isinstance(location, Point):
        return float(location.y), float(location.x)

    shape = to_shape(location)
    return float(shape.y), float(shape.x)


def validate_gps_proximity(
    latitude: float,
    longitude: float,
    muster_point: MusterPoint,
) -> Tuple[float, bool]:
    """
    Validates coordinates and calculates distance from the muster point.

    Returns:
        tuple[float, bool]: (distance_meters, is_within_geofence)
    Raises:
        InvalidCoordinateError: If submitted coordinates are out of bounds.
    """
    validate_coordinates(latitude, longitude)

    mp_lat, mp_lon = extract_point_coordinates(muster_point.location)
    distance = calculate_haversine_distance_meters(latitude, longitude, mp_lat, mp_lon)

    is_within = distance <= muster_point.geofence_radius_meters
    return round(distance, 2), is_within


# --- Core Service Functions ---

async def validate_check_in_eligibility(
    session: AsyncSession,
    worker_id: uuid.UUID,
    ward_id: uuid.UUID,
    muster_point_id: uuid.UUID,
    check_in_time: Optional[datetime] = None,
) -> Tuple[User, MusterPoint, date]:
    """
    Validates that a worker is eligible to check in at a muster point for a given workday.

    Checks:
    1. Worker exists, has role SANITATION_WORKER, and has status ACTIVE.
    2. Worker has an active assignment to the ward (revoked_at IS NULL).
    3. Muster point exists, is active, and belongs to the specified ward.
    4. Worker does not already have an attendance record for the calculated workday date.

    Returns:
        tuple[User, MusterPoint, date]: The validated worker, muster point, and workday date.
    """
    # 1. Validate worker entity, role, and active status
    stmt_worker = select(User).where(User.id == worker_id)
    res_worker = await session.execute(stmt_worker)
    worker = res_worker.scalars().first()

    if worker is None:
        raise WorkerIneligibleError(f"User with id '{worker_id}' not found.")

    if worker.role != UserRole.SANITATION_WORKER.value:
        raise WorkerIneligibleError(
            f"User '{worker_id}' has role '{worker.role}', but only sanitation workers can record attendance."
        )

    if worker.status != UserStatus.ACTIVE.value:
        raise WorkerIneligibleError(f"Worker account '{worker_id}' is not active (status: {worker.status}).")

    # 2. Validate active ward assignment
    stmt_assignment = select(UserWardAssignment).where(
        UserWardAssignment.user_id == worker.id,
        UserWardAssignment.ward_id == ward_id,
        UserWardAssignment.revoked_at.is_(None),
    )
    res_assignment = await session.execute(stmt_assignment)
    assignment = res_assignment.scalars().first()

    if assignment is None:
        raise WardAssignmentError(
            f"Worker '{worker_id}' is not actively assigned to ward '{ward_id}'."
        )

    # 3. Validate muster point existence, status, and ward association
    stmt_mp = select(MusterPoint).where(MusterPoint.id == muster_point_id)
    res_mp = await session.execute(stmt_mp)
    muster_point = res_mp.scalars().first()

    if muster_point is None:
        raise MusterPointError(f"Muster point with id '{muster_point_id}' not found.")

    if not muster_point.is_active:
        raise MusterPointError(f"Muster point '{muster_point.name}' is inactive.")

    if muster_point.ward_id != ward_id:
        raise MusterPointError(
            f"Muster point '{muster_point.name}' belongs to ward '{muster_point.ward_id}', not ward '{ward_id}'."
        )

    # 4. Validate workday uniqueness in Asia/Kolkata
    attendance_date = get_kolkata_workday_date(check_in_time)

    stmt_attendance = select(AttendanceRecord).where(
        AttendanceRecord.worker_id == worker.id,
        AttendanceRecord.attendance_date == attendance_date,
    )
    res_attendance = await session.execute(stmt_attendance)
    existing_record = res_attendance.scalars().first()

    if existing_record is not None:
        raise DuplicateAttendanceError(
            f"Worker '{worker_id}' already has an attendance record for workday {attendance_date}."
        )

    return worker, muster_point, attendance_date


async def record_check_in(
    session: AsyncSession,
    worker_id: uuid.UUID,
    ward_id: uuid.UUID,
    muster_point_id: uuid.UUID,
    latitude: float,
    longitude: float,
    check_in_time: Optional[datetime] = None,
) -> AttendanceRecord:
    """
    Records an attendance check-in for an eligible sanitation worker.

    - Verifies worker eligibility, ward assignment, muster point validity, and daily uniqueness.
    - Validates device GPS coordinates and computes distance to the muster point.
    - If within geofence: sets status to PRESENT.
    - If outside geofence: sets status to EXCEPTION_PENDING and logs distance exception reason.
    - Stores coordinates in PostGIS POINT geometry (SRID 4326, X=longitude, Y=latitude).
    - Flushes atomically within a nested savepoint to catch concurrent duplicate submissions.
    """
    # 1. Normalize check-in timestamp to timezone-aware UTC
    check_in_at = normalize_to_utc(check_in_time)

    # 2. Eligibility validation
    worker, muster_point, attendance_date = await validate_check_in_eligibility(
        session=session,
        worker_id=worker_id,
        ward_id=ward_id,
        muster_point_id=muster_point_id,
        check_in_time=check_in_at,
    )

    # 3. GPS proximity validation
    distance, is_within_geofence = validate_gps_proximity(latitude, longitude, muster_point)

    # 4. Status and exception determination
    if is_within_geofence:
        status = AttendanceStatus.PRESENT.value
        exception_reason = None
    else:
        status = AttendanceStatus.EXCEPTION_PENDING.value
        exception_reason = (
            f"Check-in outside geofence: distance {distance:.1f}m exceeds "
            f"radius {muster_point.geofence_radius_meters}m"
        )

    # 5. Construct PostGIS POINT geometry with SRID 4326 (X=lon, Y=lat)
    point_geom = WKTElement(f"POINT({longitude} {latitude})", srid=4326)

    # 6. Instantiate AttendanceRecord with normalized UTC instants
    record = AttendanceRecord(
        id=uuid.uuid4(),
        worker_id=worker.id,
        ward_id=ward_id,
        muster_point_id=muster_point.id,
        attendance_date=attendance_date,
        check_in_at=check_in_at,
        check_in_location=point_geom,
        check_in_distance_meters=distance,
        status=status,
        exception_reason=exception_reason,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    # 7. Atomic savepoint flush to catch race conditions without poisoning caller session
    try:
        async with session.begin_nested():
            session.add(record)
            await session.flush()
    except IntegrityError as exc:
        if is_duplicate_attendance_integrity_error(exc):
            raise DuplicateAttendanceError(
                f"Worker '{worker_id}' already has an attendance record for workday {attendance_date}."
            ) from exc
        # Re-raise unrelated integrity failures (e.g. check constraints, foreign keys)
        raise

    return record


async def record_check_out(
    session: AsyncSession,
    worker_id: uuid.UUID,
    ward_id: uuid.UUID,
    muster_point_id: uuid.UUID,
    latitude: float,
    longitude: float,
    check_out_time: Optional[datetime] = None,
) -> AttendanceRecord:
    """
    Records an attendance check-out for a worker's existing daily attendance record.

    - Requires an existing check-in on the workday in Asia/Kolkata.
    - Rejects duplicate check-outs.
    - Validates muster point, worker active status, and ward assignment.
    - Validates check-out timestamp is not earlier than check-in.
    - Computes check-out GPS distance against the muster point.
    - Preserves EXCEPTION_PENDING if check-in or check-out triggered an exception.
    - If previously PRESENT but check-out is outside geofence, flags EXCEPTION_PENDING.
    - Flushes atomically within a nested savepoint.
    """
    # 1. Coordinate validation
    validate_coordinates(latitude, longitude)

    # 2. Normalize check-out timestamp to timezone-aware UTC and lookup workday
    check_out_at = normalize_to_utc(check_out_time)
    attendance_date = get_kolkata_workday_date(check_out_at)

    stmt_attendance = (
        select(AttendanceRecord)
        .where(
            AttendanceRecord.worker_id == worker_id,
            AttendanceRecord.attendance_date == attendance_date,
        )
        .with_for_update()
    )
    res_attendance = await session.execute(stmt_attendance)
    record = res_attendance.scalars().first()

    if record is None:
        raise AttendanceNotFoundError(
            f"No attendance check-in found for worker '{worker_id}' on workday {attendance_date}."
        )

    # 3. Ward consistency: Check-out ward must strictly match the attendance record's check-in ward
    if record.ward_id != ward_id:
        raise WardAssignmentError(
            f"Check-out ward '{ward_id}' does not match check-in ward '{record.ward_id}'."
        )

    # 4. Duplicate check-out rejection
    if record.check_out_at is not None:
        raise DuplicateCheckOutError(
            f"Check-out has already been recorded for worker '{worker_id}' on workday {attendance_date}."
        )

    # 5. Missing check-in timestamp rejection (e.g. administrative ABSENT records)
    if record.check_in_at is None:
        raise MissingCheckInError(
            f"Cannot record check-out: attendance record for worker '{worker_id}' on workday {attendance_date} has no check-in timestamp."
        )

    # 6. Validate worker active status and ward assignment
    stmt_worker = select(User).where(User.id == worker_id)
    res_worker = await session.execute(stmt_worker)
    worker = res_worker.scalars().first()

    if worker is None or worker.role != UserRole.SANITATION_WORKER.value or worker.status != UserStatus.ACTIVE.value:
        raise WorkerIneligibleError(f"Worker '{worker_id}' is not an active sanitation worker.")

    stmt_assignment = select(UserWardAssignment).where(
        UserWardAssignment.user_id == worker_id,
        UserWardAssignment.ward_id == ward_id,
        UserWardAssignment.revoked_at.is_(None),
    )
    res_assignment = await session.execute(stmt_assignment)
    if res_assignment.scalars().first() is None:
        raise WardAssignmentError(f"Worker '{worker_id}' is not actively assigned to ward '{ward_id}'.")

    # 7. Validate muster point existence, status, and ward association
    stmt_mp = select(MusterPoint).where(MusterPoint.id == muster_point_id)
    res_mp = await session.execute(stmt_mp)
    muster_point = res_mp.scalars().first()

    if muster_point is None:
        raise MusterPointError(f"Muster point with id '{muster_point_id}' not found.")

    if not muster_point.is_active:
        raise MusterPointError(f"Muster point '{muster_point.name}' is inactive.")

    if muster_point.ward_id != ward_id:
        raise MusterPointError(
            f"Muster point '{muster_point.name}' belongs to ward '{muster_point.ward_id}', not ward '{ward_id}'."
        )

    # 8. Validate timestamps (normalized to timezone-aware UTC)
    check_in_at_normalized = normalize_to_utc(record.check_in_at)
    if check_out_at < check_in_at_normalized:
        raise InvalidAttendanceTimeError(
            f"Check-out timestamp ({check_out_at}) cannot be earlier than check-in timestamp ({check_in_at_normalized})."
        )

    # 7. GPS proximity validation
    distance, is_within_geofence = validate_gps_proximity(latitude, longitude, muster_point)

    # 8. Update check-out attributes
    point_geom = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
    record.check_out_at = check_out_at
    record.check_out_location = point_geom
    record.check_out_distance_meters = distance

    # 9. Exception status preservation and transition logic
    if record.status == AttendanceStatus.EXCEPTION_PENDING.value:
        # Preserve existing check-in exception pending supervisor review
        if not is_within_geofence:
            checkout_reason = (
                f"Check-out outside geofence: distance {distance:.1f}m exceeds "
                f"radius {muster_point.geofence_radius_meters}m"
            )
            if record.exception_reason:
                record.exception_reason = f"{record.exception_reason}; {checkout_reason}"
            else:
                record.exception_reason = checkout_reason
    elif record.status == AttendanceStatus.PRESENT.value:
        if not is_within_geofence:
            record.status = AttendanceStatus.EXCEPTION_PENDING.value
            record.exception_reason = (
                f"Check-out outside geofence: distance {distance:.1f}m exceeds "
                f"radius {muster_point.geofence_radius_meters}m"
            )

    record.updated_at = utc_now()

    # 10. Atomic savepoint flush
    async with session.begin_nested():
        await session.flush()

    return record


async def generate_qr_token(
    session: AsyncSession,
    muster_point_id: uuid.UUID,
    ward_id: uuid.UUID,
    official_user: User,
) -> Tuple[AttendanceQrToken, str]:
    """
    Generates a cryptographically secure, unpredictable, single-use QR attendance token
    valid for exactly 5 minutes at a designated muster roll-call station.

    Authorization & Validation Rules:
    - Restricted to MUNICIPAL_ADMIN and actively assigned WARD_SUPERVISOR.
    - Official account must be ACTIVE.
    - Muster point must exist, be active, and belong to ward_id.
    - Generates 256 bits of cryptographic entropy via secrets.token_urlsafe.
    - Saves the SHA-256 hash in attendance_qr_tokens to prevent token compromise from DB dumps.
    - Flushes atomically within a nested savepoint.

    Returns:
        tuple[AttendanceQrToken, str]: (qr_token_record, raw_token_string)
    """
    # 1. Official role and active status validation
    if official_user.role not in (UserRole.MUNICIPAL_ADMIN.value, UserRole.WARD_SUPERVISOR.value):
        raise WorkerIneligibleError("Only municipal administrators or ward supervisors can issue roll-call QR tokens.")

    if official_user.status != UserStatus.ACTIVE.value:
        raise WorkerIneligibleError(f"Official account '{official_user.id}' is not active.")

    # 2. Ward authorization check for supervisors
    if official_user.role == UserRole.WARD_SUPERVISOR.value:
        stmt_assignment = select(UserWardAssignment).where(
            UserWardAssignment.user_id == official_user.id,
            UserWardAssignment.ward_id == ward_id,
            UserWardAssignment.revoked_at.is_(None),
        )
        res_assignment = await session.execute(stmt_assignment)
        if res_assignment.scalars().first() is None:
            raise WardAssignmentError(
                f"Supervisor '{official_user.id}' is not actively assigned to ward '{ward_id}'."
            )

    # 3. Muster point validation
    stmt_mp = select(MusterPoint).where(MusterPoint.id == muster_point_id)
    res_mp = await session.execute(stmt_mp)
    muster_point = res_mp.scalars().first()

    if muster_point is None:
        raise MusterPointError(f"Muster point with id '{muster_point_id}' not found.")

    if not muster_point.is_active:
        raise MusterPointError(f"Muster point '{muster_point.name}' is inactive.")

    if muster_point.ward_id != ward_id:
        raise MusterPointError(
            f"Muster point '{muster_point.name}' belongs to ward '{muster_point.ward_id}', not ward '{ward_id}'."
        )

    # 4. Generate high-entropy cryptographic token and compute SHA-256 hash
    raw_token = f"nmc_qr_{secrets.token_urlsafe(32)}"
    token_hash = hash_qr_token(raw_token)

    issued_at = utc_now()
    expires_at = issued_at + timedelta(minutes=5)

    qr_token = AttendanceQrToken(
        id=uuid.uuid4(),
        token_hash=token_hash,
        muster_point_id=muster_point.id,
        ward_id=ward_id,
        issued_by=official_user.id,
        issued_at=issued_at,
        expires_at=expires_at,
        created_at=issued_at,
        updated_at=issued_at,
    )

    # 5. Atomic savepoint flush
    async with session.begin_nested():
        session.add(qr_token)
        await session.flush()

    return qr_token, raw_token


async def redeem_qr_attendance(
    session: AsyncSession,
    worker_id: uuid.UUID,
    raw_token: str,
    latitude: float,
    longitude: float,
    device_timestamp: Optional[datetime] = None,
    *,
    check_in_time: Optional[datetime] = None,
) -> Tuple[AttendanceRecord, AttendanceQrToken, float, bool]:
    """
    Redeems a single-use roll-call QR token to record a sanitation worker's daily attendance.

    Security & Business Rules:
    - Authoritative Server Clock: Token expiry, official attendance check_in_at timestamp,
      and token redeemed_at timestamp are strictly anchored to the server clock (utc_now()).
      Untrusted client device timestamps are never used for expiry verification or attendance records.
    - Single-use state and 5-minute validity window are strictly enforced.
    - Submits check-in through the existing record_check_in service (enforcing active worker
      status, sanitation role, active ward assignment, and daily uniqueness in Asia/Kolkata).
    - Computes GPS proximity against the muster point using the Haversine formula.
    - If GPS is inside geofence -> recorded as PRESENT.
    - If GPS is outside geofence -> recorded as EXCEPTION_PENDING.
    - Atomically links the attendance record to the QR token (setting redeemed_at, redeemed_by,
      attendance_record_id) within the same database transaction.
    - If check-in fails (e.g. duplicate attendance or inactive worker), the token is NOT redeemed.
    - Replay-resistant: subsequent or concurrent redemption attempts are rejected.

    Returns:
        tuple[AttendanceRecord, AttendanceQrToken, float, bool]:
        (attendance_record, qr_token_record, distance_meters, is_within_geofence)
    """
    if not raw_token or not raw_token.strip():
        raise InvalidQrTokenError("QR token cannot be empty.")

    # 1. Authoritative server timestamp for expiry, check-in, and redemption
    server_now = utc_now()

    # 2. Lookup QR token by SHA-256 hash with row-locking for concurrency protection
    token_hash = hash_qr_token(raw_token)
    stmt = (
        select(AttendanceQrToken)
        .where(AttendanceQrToken.token_hash == token_hash)
        .with_for_update()
    )
    res = await session.execute(stmt)
    qr_token = res.scalars().first()

    if qr_token is None:
        raise InvalidQrTokenError("Invalid or unrecognized QR token.")

    # 3. Single-use replay protection check
    if qr_token.redeemed_at is not None:
        raise QrTokenAlreadyRedeemedError("This QR attendance token has already been redeemed.")

    # 4. Expiration verification strictly against authoritative server time (5-minute window)
    if server_now > qr_token.expires_at:
        raise ExpiredQrTokenError("This QR attendance token has expired (validity is 5 minutes).")

    # 5. Muster point status verification
    stmt_mp = select(MusterPoint).where(MusterPoint.id == qr_token.muster_point_id)
    res_mp = await session.execute(stmt_mp)
    muster_point = res_mp.scalars().first()
    if muster_point is None or not muster_point.is_active:
        raise MusterPointError("Muster point associated with this QR token is no longer active.")

    # 6. Execute check-in through the existing attendance service
    # Official check-in instant is anchored strictly to authoritative server time (server_now)
    record = await record_check_in(
        session=session,
        worker_id=worker_id,
        ward_id=qr_token.ward_id,
        muster_point_id=qr_token.muster_point_id,
        latitude=latitude,
        longitude=longitude,
        check_in_time=server_now,
    )

    # 7. Atomically mark QR token as redeemed within the same transaction using authoritative server time
    qr_token.redeemed_at = server_now
    qr_token.redeemed_by = worker_id
    qr_token.attendance_record_id = record.id
    qr_token.updated_at = server_now

    # 8. Atomic savepoint flush
    async with session.begin_nested():
        await session.flush()

    is_within = record.status == AttendanceStatus.PRESENT.value
    return record, qr_token, record.check_in_distance_meters, is_within


async def review_attendance_record(
    session: AsyncSession,
    record_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    action: str,
    review_notes: Optional[str] = None,
) -> AttendanceRecord:
    """
    Reviews a pending attendance exception and transitions status to PRESENT or REJECTED.
    Uses row-level locking (with_for_update()) to prevent concurrent conflicting resolutions.
    """
    stmt = (
        select(AttendanceRecord)
        .where(AttendanceRecord.id == record_id)
        .with_for_update()
    )
    res = await session.execute(stmt)
    record = res.scalars().first()

    if record is None:
        raise AttendanceNotFoundError(f"Attendance record with id '{record_id}' not found.")

    if record.status != AttendanceStatus.EXCEPTION_PENDING.value:
        raise AttendanceNotReviewableError(
            f"Attendance record '{record_id}' cannot be reviewed because its status is '{record.status}', not 'EXCEPTION_PENDING'."
        )

    action_upper = action.strip().upper()
    if action_upper == "APPROVE":
        record.status = AttendanceStatus.PRESENT.value
    elif action_upper == "REJECT":
        if not review_notes or not review_notes.strip():
            raise ValueError("A rejection note is required when rejecting an attendance exception.")
        record.status = AttendanceStatus.REJECTED.value
    else:
        raise ValueError(f"Invalid review action '{action}'. Must be 'APPROVE' or 'REJECT'.")

    now = utc_now()
    record.reviewed_by = reviewer_id
    record.reviewed_at = now
    record.review_notes = review_notes.strip() if review_notes else None
    record.updated_at = now

    async with session.begin_nested():
        await session.flush()

    return record


async def get_daily_attendance_roster(
    session: AsyncSession,
    ward_id: uuid.UUID,
    attendance_date: date,
    limit: Optional[int] = 100,
    offset: int = 0,
) -> Tuple[list[AttendanceRecord], int, int, int, int]:
    """
    Queries attendance records for a ward on a specific workday with eager loading of worker and muster point relationships.
    Computes summary counts (total, present, exception_pending, rejected).
    """
    from sqlalchemy.orm import joinedload
    from sqlalchemy import func

    # Query counts for daily summary
    count_stmt = (
        select(
            func.count(AttendanceRecord.id).label("total"),
            func.count(AttendanceRecord.id).filter(AttendanceRecord.status == AttendanceStatus.PRESENT.value).label("present"),
            func.count(AttendanceRecord.id).filter(AttendanceRecord.status == AttendanceStatus.EXCEPTION_PENDING.value).label("exception_pending"),
            func.count(AttendanceRecord.id).filter(AttendanceRecord.status == AttendanceStatus.REJECTED.value).label("rejected"),
        )
        .where(
            AttendanceRecord.ward_id == ward_id,
            AttendanceRecord.attendance_date == attendance_date,
        )
    )
    res_counts = await session.execute(count_stmt)
    counts_row = res_counts.first()
    total_count = counts_row.total if counts_row and counts_row.total is not None else 0
    present_count = counts_row.present if counts_row and counts_row.present is not None else 0
    exception_pending_count = counts_row.exception_pending if counts_row and counts_row.exception_pending is not None else 0
    rejected_count = counts_row.rejected if counts_row and counts_row.rejected is not None else 0

    stmt = (
        select(AttendanceRecord)
        .options(
            joinedload(AttendanceRecord.worker),
            joinedload(AttendanceRecord.muster_point),
        )
        .where(
            AttendanceRecord.ward_id == ward_id,
            AttendanceRecord.attendance_date == attendance_date,
        )
        .order_by(AttendanceRecord.check_in_at.asc().nulls_last(), AttendanceRecord.created_at.asc())
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    res = await session.execute(stmt)
    records = res.scalars().unique().all()
    return list(records), total_count, present_count, exception_pending_count, rejected_count



