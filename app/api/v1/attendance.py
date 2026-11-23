"""
API endpoints for Pourakarmika attendance lifecycle:
- POST /api/v1/wards/{ward_id}/muster-points/{muster_point_id}/qr-code
  Issues a single-use 5-minute QR roll-call token for an active muster station.
  Restricted to Municipal Admins and assigned Ward Supervisors.

- POST /api/v1/attendance/qr-check-in
  Redeems a single-use QR token and records worker attendance with GPS proximity verification.
  Restricted to active Sanitation Workers assigned to the muster station's ward.

- POST /api/v1/attendance/check-out
  Records worker shift check-out with GPS proximity verification.
  Restricted to active Sanitation Workers.

- GET /api/v1/wards/{ward_id}/attendance/daily
  Queries daily attendance roster and exception metrics for an administrative ward.
  Restricted to Municipal Admins and assigned Ward Supervisors.

- POST /api/v1/attendance/{record_id}/review
  Resolves pending attendance geofence exceptions (approving to PRESENT or rejecting to REJECTED).
  Restricted to Municipal Admins and assigned Ward Supervisors.
"""

import uuid
import logging
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles, verify_ward_access
from app.core.database import get_db
from app.core.config import settings
from app.models.enums import UserRole, AttendanceStatus
from app.models.user import User
from app.models.attendance import AttendanceRecord
from app.schemas.attendance import (
    AttendanceQrIssueResponse,
    AttendanceQrCheckInRequest,
    AttendanceQrCheckInResponse,
    AttendanceCheckOutRequest,
    AttendanceCheckOutResponse,
    AttendanceDailyItemResponse,
    AttendanceDailyRosterResponse,
    AttendanceReviewAction,
    AttendanceReviewRequest,
    AttendanceReviewResponse,
)
from app.services.attendance_service import (
    generate_qr_token,
    redeem_qr_attendance,
    record_check_out,
    review_attendance_record,
    get_daily_attendance_roster,
    get_kolkata_workday_date,
    utc_now,
    InvalidQrTokenError,
    ExpiredQrTokenError,
    QrTokenAlreadyRedeemedError,
    WorkerIneligibleError,
    WardAssignmentError,
    MusterPointError,
    DuplicateAttendanceError,
    AttendanceNotFoundError,
    DuplicateCheckOutError,
    MissingCheckInError,
    AttendanceNotReviewableError,
    InvalidCoordinateError,
    InvalidAttendanceTimeError,
)
from app.core.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Attendance"])

# Rate limiters: sliding-window per caller IP
qr_issue_rate_limiter = RateLimiter(max_requests=30, window_seconds=60, key_prefix="qr_issue")
qr_check_in_rate_limiter = RateLimiter(max_requests=15, window_seconds=60, key_prefix="qr_checkin")
check_out_rate_limiter = RateLimiter(max_requests=15, window_seconds=60, key_prefix="att_checkout")
roster_rate_limiter = RateLimiter(max_requests=60, window_seconds=60, key_prefix="att_roster")
review_rate_limiter = RateLimiter(max_requests=30, window_seconds=60, key_prefix="att_review")


@router.post(
    "/wards/{ward_id}/muster-points/{muster_point_id}/qr-code",
    response_model=AttendanceQrIssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue Roll-Call QR Token",
    description="Generates an unpredictable, single-use, 5-minute QR attendance token for an active muster point. Restricted to Admins and assigned Ward Supervisors.",
    dependencies=[Depends(qr_issue_rate_limiter)],
)
async def issue_roll_call_qr(
    ward_id: uuid.UUID,
    muster_point_id: uuid.UUID,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> AttendanceQrIssueResponse:
    """
    Issues a single-use roll-call QR token for a muster point.
    - Enforces municipal official or supervisor role.
    - Enforces ward-level authorization for supervisors.
    - Verifies that the muster point is active and belongs to ward_id.
    """
    # 1. Enforce ward access
    await verify_ward_access(current_user, ward_id, db)

    try:
        qr_token, raw_token = await generate_qr_token(
            session=db,
            muster_point_id=muster_point_id,
            ward_id=ward_id,
            official_user=current_user,
        )
        await db.commit()
        await db.refresh(qr_token)

        return AttendanceQrIssueResponse(
            token=raw_token,
            muster_point_id=qr_token.muster_point_id,
            ward_id=qr_token.ward_id,
            issued_at=qr_token.issued_at,
            expires_at=qr_token.expires_at,
            expires_in_seconds=300,
        )
    except MusterPointError as exc:
        await db.rollback()
        err_msg = str(exc)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except WardAssignmentError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkerIneligibleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error during QR issuance: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while generating the roll-call QR token.",
        )


@router.post(
    "/attendance/qr-check-in",
    response_model=AttendanceQrCheckInResponse,
    status_code=status.HTTP_201_CREATED,
    summary="QR Roll-Call Check-In",
    description="Redeems a single-use QR attendance token and records daily shift check-in with GPS proximity verification.",
    dependencies=[Depends(qr_check_in_rate_limiter)],
)
async def qr_check_in(
    payload: AttendanceQrCheckInRequest,
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
) -> AttendanceQrCheckInResponse:
    """
    Redeems a single-use QR attendance token to check in an active sanitation worker.
    - Authoritative server clock determines token expiry, check-in timestamp, and redemption time.
    - Validates token authenticity, single-use state, and 5-minute validity window.
    - Verifies worker is actively assigned to the muster point's ward.
    - Enforces daily check-in uniqueness (Asia/Kolkata workday).
    - Calculates distance using Haversine formula and flags EXCEPTION_PENDING if outside geofence.
    - Atomically marks the token as redeemed and creates the attendance record.
    """
    try:
        record, qr_token, distance, is_within = await redeem_qr_attendance(
            session=db,
            worker_id=current_user.id,
            raw_token=payload.qr_token,
            latitude=payload.latitude,
            longitude=payload.longitude,
            device_timestamp=payload.device_timestamp,
        )
        await db.commit()
        await db.refresh(record)

        msg = (
            "Check-in verified within muster point geofence."
            if is_within
            else "Check-in recorded with exception (outside designated geofence). Supervisor review required."
        )

        return AttendanceQrCheckInResponse(
            attendance_id=record.id,
            worker_id=record.worker_id,
            ward_id=record.ward_id,
            muster_point_id=record.muster_point_id,
            attendance_date=record.attendance_date,
            check_in_at=record.check_in_at,
            status=record.status,
            distance_meters=distance,
            is_within_geofence=is_within,
            exception_reason=record.exception_reason,
            message=msg,
        )
    except InvalidQrTokenError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ExpiredQrTokenError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except QrTokenAlreadyRedeemedError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except DuplicateAttendanceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except WardAssignmentError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkerIneligibleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except MusterPointError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InvalidCoordinateError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except InvalidAttendanceTimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error during QR attendance redemption: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing attendance check-in.",
        )


@router.post(
    "/attendance/check-out",
    response_model=AttendanceCheckOutResponse,
    status_code=status.HTTP_200_OK,
    summary="Worker Shift Check-Out",
    description="Records end-of-shift check-out for the authenticated sanitation worker with GPS proximity verification.",
    dependencies=[Depends(check_out_rate_limiter)],
)
async def check_out(
    payload: AttendanceCheckOutRequest,
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
) -> AttendanceCheckOutResponse:
    """
    Records end-of-shift check-out for the authenticated sanitation worker.
    - Worker identity is derived exclusively from the validated JWT token (current_user.id).
    - Checks out today's attendance record in Asia/Kolkata timezone.
    - Rejects duplicate check-outs, unrecorded check-ins, or mismatched wards.
    - Validates check-out coordinates against muster station geofence.
    - If outside geofence: status remains or transitions to EXCEPTION_PENDING.
    """
    server_now = utc_now()
    attendance_date = get_kolkata_workday_date(server_now)

    # Resolve ward_id and muster_point_id from today's attendance record if not provided in payload
    ward_id = payload.ward_id
    muster_point_id = payload.muster_point_id

    if ward_id is None or muster_point_id is None:
        stmt = (
            select(AttendanceRecord)
            .where(
                AttendanceRecord.worker_id == current_user.id,
                AttendanceRecord.attendance_date == attendance_date,
            )
        )
        res = await db.execute(stmt)
        today_record = res.scalars().first()
        if today_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No attendance check-in found for worker on workday {attendance_date}.",
            )
        if ward_id is None:
            ward_id = today_record.ward_id
        if muster_point_id is None:
            muster_point_id = today_record.muster_point_id

    if muster_point_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Muster point could not be determined for check-out.",
        )

    try:
        record = await record_check_out(
            session=db,
            worker_id=current_user.id,
            ward_id=ward_id,
            muster_point_id=muster_point_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            check_out_time=server_now,
        )
        await db.commit()
        await db.refresh(record)

        is_within = record.status != AttendanceStatus.EXCEPTION_PENDING.value or (
            record.exception_reason is not None and "Check-out outside geofence" not in record.exception_reason
        )

        msg = (
            "Check-out verified within muster point geofence."
            if is_within
            else "Check-out recorded outside designated geofence. Exception logged for supervisor review."
        )

        return AttendanceCheckOutResponse(
            attendance_id=record.id,
            worker_id=record.worker_id,
            ward_id=record.ward_id,
            muster_point_id=record.muster_point_id,
            attendance_date=record.attendance_date,
            check_in_at=record.check_in_at,
            check_out_at=record.check_out_at,
            status=record.status,
            distance_meters=record.check_out_distance_meters,
            is_within_geofence=is_within,
            exception_reason=record.exception_reason,
            message=msg,
        )
    except AttendanceNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DuplicateCheckOutError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except MissingCheckInError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except WardAssignmentError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkerIneligibleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except MusterPointError as exc:
        await db.rollback()
        err_msg = str(exc)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except InvalidCoordinateError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except InvalidAttendanceTimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error during worker check-out: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing attendance check-out.",
        )


@router.get(
    "/wards/{ward_id}/attendance/daily",
    response_model=AttendanceDailyRosterResponse,
    status_code=status.HTTP_200_OK,
    summary="Supervisor Daily Attendance Roster",
    description="Fetches daily attendance records and exception summary for an administrative ward. Restricted to Municipal Admins and assigned Ward Supervisors.",
    dependencies=[Depends(roster_rate_limiter)],
)
async def get_daily_roster(
    ward_id: uuid.UUID,
    attendance_date: Optional[date] = Query(
        default=None,
        description="Workday date (YYYY-MM-DD). Defaults to current date in Asia/Kolkata.",
    ),
    limit: Optional[int] = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum records to return.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of records to skip.",
    ),
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> AttendanceDailyRosterResponse:
    """
    Retrieves the daily attendance roster for a ward.
    - Enforces ward-level authorization for supervisors (HTTP 403 if unassigned).
    - Defaults to current date in Asia/Kolkata if not specified.
    - Returns summary counts (total, present, pending exceptions, rejected) and record details.
    - Eagerly loads worker and muster point relationships to eliminate N+1 queries.
    """
    await verify_ward_access(user=current_user, ward_id=ward_id, db=db)

    target_date = attendance_date if attendance_date is not None else get_kolkata_workday_date(utc_now())

    records, total_count, present_count, exception_pending_count, rejected_count = await get_daily_attendance_roster(
        session=db,
        ward_id=ward_id,
        attendance_date=target_date,
        limit=limit,
        offset=offset,
    )

    items = []
    for r in records:
        worker_email = r.worker.email if r.worker else None
        mp_name = r.muster_point.name if r.muster_point else None
        items.append(
            AttendanceDailyItemResponse(
                id=r.id,
                worker_id=r.worker_id,
                worker_email=worker_email,
                ward_id=r.ward_id,
                muster_point_id=r.muster_point_id,
                muster_point_name=mp_name,
                attendance_date=r.attendance_date,
                check_in_at=r.check_in_at,
                check_out_at=r.check_out_at,
                status=r.status,
                check_in_distance_meters=r.check_in_distance_meters,
                check_out_distance_meters=r.check_out_distance_meters,
                exception_reason=r.exception_reason,
                reviewed_by=r.reviewed_by,
                reviewed_at=r.reviewed_at,
                review_notes=r.review_notes,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )

    return AttendanceDailyRosterResponse(
        ward_id=ward_id,
        attendance_date=target_date,
        total_count=total_count,
        present_count=present_count,
        exception_pending_count=exception_pending_count,
        rejected_count=rejected_count,
        records=items,
    )


@router.post(
    "/attendance/{record_id}/review",
    response_model=AttendanceReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Review Attendance Exception",
    description="Resolves a pending attendance exception (approves to PRESENT or rejects to REJECTED). Restricted to Municipal Admins and assigned Ward Supervisors.",
    dependencies=[Depends(review_rate_limiter)],
)
async def review_attendance(
    record_id: uuid.UUID,
    payload: AttendanceReviewRequest,
    current_user: User = Depends(require_roles(UserRole.WARD_SUPERVISOR, UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> AttendanceReviewResponse:
    """
    Reviews a pending attendance exception record.
    - Requires WARD_SUPERVISOR or MUNICIPAL_ADMIN.
    - Enforces ward-level authorization for supervisors (HTTP 403 if unassigned).
    - Requires record to be in EXCEPTION_PENDING status (HTTP 409 if already resolved).
    - Row-level locking (with_for_update) prevents concurrent conflicting reviews.
    - Action 'APPROVE' sets status to PRESENT.
    - Action 'REJECT' sets status to REJECTED and requires review_notes.
    - Records reviewer ID, review timestamp, and notes.
    """
    # 1. Fetch record first to determine ward_id for ward access check
    stmt_check = select(AttendanceRecord).where(AttendanceRecord.id == record_id)
    res_check = await db.execute(stmt_check)
    record_peek = res_check.scalars().first()

    if record_peek is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attendance record with id '{record_id}' not found.",
        )

    # 2. Ward-level authorization check
    await verify_ward_access(user=current_user, ward_id=record_peek.ward_id, db=db)

    # 3. Check reviewable state
    if record_peek.status != AttendanceStatus.EXCEPTION_PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attendance record '{record_id}' is not in reviewable state. Current status is '{record_peek.status}'.",
        )

    # 4. Rejection note validation
    if payload.action == AttendanceReviewAction.REJECT and (not payload.review_notes or not payload.review_notes.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Review notes explaining the reason for rejection are mandatory when rejecting an attendance exception.",
        )

    # 5. Execute atomic review with row-level locking
    try:
        previous_status = record_peek.status
        updated_record = await review_attendance_record(
            session=db,
            record_id=record_id,
            reviewer_id=current_user.id,
            action=payload.action.value,
            review_notes=payload.review_notes,
        )
        await db.commit()
        await db.refresh(updated_record)

        msg = (
            "Attendance exception approved. Status updated to PRESENT."
            if updated_record.status == AttendanceStatus.PRESENT.value
            else "Attendance exception rejected. Status updated to REJECTED."
        )

        return AttendanceReviewResponse(
            attendance_id=updated_record.id,
            worker_id=updated_record.worker_id,
            ward_id=updated_record.ward_id,
            attendance_date=updated_record.attendance_date,
            previous_status=previous_status,
            new_status=updated_record.status,
            reviewed_by=updated_record.reviewed_by,
            reviewed_at=updated_record.reviewed_at,
            review_notes=updated_record.review_notes,
            message=msg,
        )
    except AttendanceNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except AttendanceNotReviewableError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error during attendance review: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing attendance review.",
        )



# --- Email OTP Attendance Endpoints & Today's Attendance ---

from app.services.otp_service import otp_manager
from app.services.attendance_service import record_check_in
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint
from app.schemas.attendance import (
    AttendanceOtpIssueResponse,
    AttendanceOtpVerifyRequest,
    AttendanceOtpVerifyResponse,
    AttendanceOtpCheckInRequest,
    WorkerAssignmentResponse,
)


@router.post(
    "/attendance/otp/request",
    response_model=AttendanceOtpIssueResponse,
    status_code=status.HTTP_200_OK,
    summary="Request Attendance Email OTP",
    description="Dispatches a secure, single-use 6-digit OTP to the authenticated worker's registered email.",
)
async def request_attendance_otp(
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
) -> AttendanceOtpIssueResponse:
    try:
        challenge_id, expires_in, raw_otp = otp_manager.request_otp(
            worker_id=current_user.id,
            worker_email=current_user.email,
        )

        # Enforce strict server-side environment boundary:
        # dev_otp is ONLY disclosed when running in local development mode.
        # In production or staging environments, dev_otp is strictly None (null in JSON).
        app_env_lower = (getattr(settings, "APP_ENV", "") or "").lower().strip()
        is_dev_mode = (
            app_env_lower == "development" or getattr(settings, "APP_DEBUG", False) is True
        ) and app_env_lower not in ("production", "staging", "prod")

        dev_otp_val = raw_otp if is_dev_mode else None

        return AttendanceOtpIssueResponse(
            challenge_id=challenge_id,
            expires_in_seconds=expires_in,
            worker_email=current_user.email,
            message="Verification code dispatched to your registered email address.",
            dev_otp=dev_otp_val,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to dispatch attendance OTP: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not dispatch verification code. Please try again.",
        )


@router.post(
    "/attendance/otp/verify",
    response_model=AttendanceOtpVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify Attendance Email OTP",
    description="Validates the entered 6-digit OTP code against the worker's active challenge.",
)
async def verify_attendance_otp(
    payload: AttendanceOtpVerifyRequest,
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
) -> AttendanceOtpVerifyResponse:
    is_valid, msg, _ = otp_manager.verify_otp_detailed(
        challenge_id=payload.challenge_id,
        worker_id=current_user.id,
        entered_otp=payload.otp,
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )
    return AttendanceOtpVerifyResponse(
        challenge_id=payload.challenge_id,
        verified=True,
        message=msg,
    )


@router.post(
    "/attendance/otp-check-in",
    response_model=AttendanceQrCheckInResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Complete Attendance Check-In via Verified OTP & GPS",
    description="Submits attendance check-in verified by Email OTP and device GPS proximity to assigned muster station.",
)
async def otp_check_in(
    payload: AttendanceOtpCheckInRequest,
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
) -> AttendanceQrCheckInResponse:
    # 1. Validate and redeem OTP challenge
    if not otp_manager.validate_and_redeem(payload.challenge_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attendance verification session is invalid, unverified, or expired.",
        )

    # 2. Resolve ward and muster point
    ward_id = payload.ward_id
    muster_point_id = payload.muster_point_id

    if ward_id is None or muster_point_id is None:
        # Find worker's active ward assignment
        stmt_assign = select(UserWardAssignment).where(
            UserWardAssignment.user_id == current_user.id,
            UserWardAssignment.revoked_at.is_(None),
        )
        res_assign = await db.execute(stmt_assign)
        assign = res_assign.scalars().first()

        if assign is not None:
            ward_id = ward_id or assign.ward_id

        if ward_id is not None and muster_point_id is None:
            stmt_mp = select(MusterPoint).where(
                MusterPoint.ward_id == ward_id,
                MusterPoint.is_active.is_(True),
            )
            res_mp = await db.execute(stmt_mp)
            mp = res_mp.scalars().first()
            if mp is not None:
                muster_point_id = mp.id

    if ward_id is None or muster_point_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active ward assignment or muster station found for this worker.",
        )

    # 3. Record attendance using authoritative core service
    try:
        record = await record_check_in(
            session=db,
            worker_id=current_user.id,
            ward_id=ward_id,
            muster_point_id=muster_point_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            check_in_time=utc_now(),
        )
        await db.commit()
        await db.refresh(record)

        is_within = record.status == AttendanceStatus.PRESENT.value
        msg = (
            "Check-in verified within muster point geofence."
            if is_within
            else "Check-in recorded with exception (outside designated geofence). Supervisor review required."
        )

        return AttendanceQrCheckInResponse(
            attendance_id=record.id,
            worker_id=record.worker_id,
            ward_id=record.ward_id,
            muster_point_id=record.muster_point_id,
            attendance_date=record.attendance_date,
            check_in_at=record.check_in_at,
            status=record.status,
            distance_meters=record.check_in_distance_meters,
            is_within_geofence=is_within,
            exception_reason=record.exception_reason,
            message=msg,
        )
    except DuplicateAttendanceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except WardAssignmentError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkerIneligibleError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except MusterPointError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InvalidCoordinateError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error in OTP check-in: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while recording attendance.",
        )


@router.get(
    "/attendance/today",
    response_model=Optional[AttendanceDailyItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Worker's Today Attendance Record",
    description="Returns the authenticated worker's attendance record for the current workday.",
)
async def get_worker_today_attendance(
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
) -> Optional[AttendanceDailyItemResponse]:
    today = get_kolkata_workday_date(utc_now())
    stmt = (
        select(AttendanceRecord)
        .where(
            AttendanceRecord.worker_id == current_user.id,
            AttendanceRecord.attendance_date == today,
        )
    )
    res = await db.execute(stmt)
    record = res.scalars().first()

    if not record:
        return None

    mp_name = None
    if record.muster_point_id:
        stmt_mp = select(MusterPoint.name).where(MusterPoint.id == record.muster_point_id)
        res_mp = await db.execute(stmt_mp)
        mp_name = res_mp.scalars().first()

    return AttendanceDailyItemResponse(
        id=record.id,
        worker_id=record.worker_id,
        worker_email=current_user.email,
        ward_id=record.ward_id,
        muster_point_id=record.muster_point_id,
        muster_point_name=mp_name,
        attendance_date=record.attendance_date,
        check_in_at=record.check_in_at,
        check_out_at=record.check_out_at,
        status=record.status,
        check_in_distance_meters=record.check_in_distance_meters,
        check_out_distance_meters=record.check_out_distance_meters,
        exception_reason=record.exception_reason,
        reviewed_by=record.reviewed_by,
        reviewed_at=record.reviewed_at,
        review_notes=record.review_notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get(
    "/attendance/worker-assignment",
    response_model=WorkerAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Worker Assignment & Muster Station Information",
    description="Returns the active ward and muster point assigned to the authenticated worker.",
)
async def get_worker_assignment(
    current_user: User = Depends(require_roles(UserRole.SANITATION_WORKER)),
    db: AsyncSession = Depends(get_db),
) -> WorkerAssignmentResponse:
    stmt = (
        select(UserWardAssignment, Ward)
        .join(Ward, UserWardAssignment.ward_id == Ward.id)
        .where(
            UserWardAssignment.user_id == current_user.id,
            UserWardAssignment.revoked_at.is_(None),
        )
    )
    res = await db.execute(stmt)
    row = res.first()

    ward_id = None
    ward_number = None
    ward_name = None
    mp_id = None
    mp_name = None
    radius = None

    if row:
        assignment, ward = row
        ward_id = ward.id
        ward_name = getattr(ward, "display_name", None) or getattr(ward, "name", None)
        ward_number = None
        if getattr(ward, "ward_code", None):
            import re
            m = re.search(r"\d+", str(ward.ward_code))
            if m:
                try:
                    ward_number = int(m.group(0))
                except ValueError:
                    ward_number = None
        elif hasattr(ward, "number") and isinstance(ward.number, int):
            ward_number = ward.number

        stmt_mp = select(MusterPoint).where(
            MusterPoint.ward_id == ward.id,
            MusterPoint.is_active.is_(True),
        )
        res_mp = await db.execute(stmt_mp)
        mp = res_mp.scalars().first()
        if mp:
            mp_id = mp.id
            mp_name = mp.name
            radius = mp.geofence_radius_meters

    return WorkerAssignmentResponse(
        worker_id=current_user.id,
        worker_email=current_user.email,
        ward_id=ward_id,
        ward_number=ward_number,
        ward_name=ward_name,
        muster_point_id=mp_id,
        muster_point_name=mp_name,
        geofence_radius_meters=radius,
    )
