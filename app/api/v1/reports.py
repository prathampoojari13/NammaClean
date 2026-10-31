"""
API router for illegal-dumping reports and evidence management.
Supports citizen report submission, photo evidence uploads, secure streaming,
and role-scoped review workflows for supervisors and municipal administrators.
"""

import uuid
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles, verify_ward_access
from app.models.enums import UserRole, DumpingReportStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.dumping_report import DumpingReport, ReportEvidence, utc_now
from app.schemas.dumping_report import (
    DumpingReportCreateRequest,
    DumpingReportStatusUpdateRequest,
    DumpingReportResponse,
    ReportEvidenceResponse,
)
from app.services.storage_service import (
    store_evidence_upload,
    get_evidence_file_path,
    remove_evidence_file,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Illegal Dumping Reports"])

# Valid state machine transitions
ALLOWED_STATUS_TRANSITIONS = {
    DumpingReportStatus.SUBMITTED.value: {
        DumpingReportStatus.UNDER_REVIEW.value,
        DumpingReportStatus.REJECTED.value,
    },
    DumpingReportStatus.UNDER_REVIEW.value: {
        DumpingReportStatus.ACTION_SCHEDULED.value,
        DumpingReportStatus.RESOLVED.value,
        DumpingReportStatus.REJECTED.value,
    },
    DumpingReportStatus.ACTION_SCHEDULED.value: {
        DumpingReportStatus.RESOLVED.value,
        DumpingReportStatus.REJECTED.value,
    },
    DumpingReportStatus.RESOLVED.value: set(),
    DumpingReportStatus.REJECTED.value: set(),
}


@router.post(
    "",
    response_model=DumpingReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit Illegal Dumping Report",
    description="Allows authenticated citizens to report an illegal waste-dumping incident.",
)
async def submit_report(
    payload: DumpingReportCreateRequest,
    current_user: User = Depends(require_roles(UserRole.CITIZEN)),
    db: AsyncSession = Depends(get_db),
) -> DumpingReportResponse:
    """
    Submits a new civic incident report.

    Rules & Invariants:
    - Only authenticated CITIZEN accounts may submit reports.
    - Status is unconditionally set to SUBMITTED by the server.
    - If ward_id is provided, it must reference an existing Ward.
    - Coordinates are stored as WGS 84 Point geometries.
    - Initial history event is recorded for auditability.
    """
    if payload.ward_id is not None:
        ward = await db.get(Ward, payload.ward_id)
        if not ward:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ward '{payload.ward_id}' not found.",
            )

    location_geom = WKTElement(f"POINT({payload.longitude} {payload.latitude})", srid=4326)
    now_iso = utc_now().isoformat()

    initial_audit_entry = {
        "from_status": None,
        "to_status": DumpingReportStatus.SUBMITTED.value,
        "changed_by_user_id": str(current_user.id),
        "notes": "Report submitted by citizen.",
        "timestamp": now_iso,
    }

    report = DumpingReport(
        reporter_id=current_user.id,
        ward_id=payload.ward_id,
        location=location_geom,
        description=payload.description.strip(),
        status=DumpingReportStatus.SUBMITTED.value,
        official_notes=None,
        status_history=[initial_audit_entry],
    )

    db.add(report)
    await db.commit()

    # Eagerly reload persisted report with evidence collection to prevent MissingGreenlet in async sessions
    stmt = (
        select(DumpingReport)
        .options(selectinload(DumpingReport.evidence))
        .where(DumpingReport.id == report.id)
    )
    res = await db.execute(stmt)
    persisted_report = res.scalar_one()

    return DumpingReportResponse.from_orm_model(persisted_report)


@router.post(
    "/{report_id}/evidence",
    response_model=ReportEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Report Evidence Photo",
    description="Uploads photographic evidence (JPEG, PNG, WebP up to 5 MB) for an existing report.",
)
async def upload_evidence(
    report_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportEvidenceResponse:
    """
    Uploads and attaches photographic evidence to a report.

    Authorization:
    - Only the original reporter (CITIZEN) can upload evidence.
    - Rejects uploads if the report is already RESOLVED or REJECTED.
    - Files are validated by MIME type, file size limit (5MB), and binary magic bytes.
    - Stores file under a server-generated UUID key on local filesystem storage.
    - Cleans up storage safely on any database commit failure.
    """
    if current_user.role != UserRole.CITIZEN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only citizens can submit evidence for incident reports.",
        )

    stmt = select(DumpingReport).where(DumpingReport.id == report_id)
    res = await db.execute(stmt)
    report = res.scalars().first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found.",
        )

    if report.reporter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to attach evidence to this report.",
        )

    if report.status in (DumpingReportStatus.RESOLVED.value, DumpingReportStatus.REJECTED.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot attach evidence to a resolved or rejected report.",
        )

    # Stream, validate magic bytes, enforce 5MB limit, and save with server UUID
    sanitized_filename, storage_key, file_size, mime_type = await store_evidence_upload(request)

    evidence = ReportEvidence(
        report_id=report.id,
        storage_key=storage_key,
        file_name=sanitized_filename,
        file_size_bytes=file_size,
        content_type=mime_type,
    )

    db.add(evidence)
    try:
        await db.commit()
        await db.refresh(evidence)
    except Exception as exc:
        await db.rollback()
        remove_evidence_file(storage_key)
        logger.error("Failed to persist evidence record: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record evidence file.",
        )

    return ReportEvidenceResponse.model_validate(evidence)


@router.get(
    "/me",
    response_model=List[DumpingReportResponse],
    status_code=status.HTTP_200_OK,
    summary="List Citizen's Own Reports",
    description="Returns all illegal-dumping reports submitted by the authenticated citizen.",
)
async def list_my_reports(
    current_user: User = Depends(require_roles(UserRole.CITIZEN)),
    db: AsyncSession = Depends(get_db),
) -> List[DumpingReportResponse]:
    """
    Returns incident reports owned by the requesting citizen, ordered newest first.
    """
    stmt = (
        select(DumpingReport)
        .options(selectinload(DumpingReport.evidence))
        .where(DumpingReport.reporter_id == current_user.id)
        .order_by(DumpingReport.created_at.desc())
    )
    res = await db.execute(stmt)
    reports = res.scalars().all()
    return [DumpingReportResponse.from_orm_model(r) for r in reports]


@router.get(
    "",
    response_model=List[DumpingReportResponse],
    status_code=status.HTTP_200_OK,
    summary="List Reports for Review",
    description="Retrieves incident reports. Municipal Admins have city-wide access; Ward Supervisors are restricted to their actively assigned wards.",
)
async def list_reports(
    ward_id: Optional[uuid.UUID] = Query(default=None, description="Optional ward filter"),
    report_status: Optional[DumpingReportStatus] = Query(default=None, alias="status", description="Optional status filter"),
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> List[DumpingReportResponse]:
    """
    Official review query endpoint.

    Authorization & Scoping:
    - Municipal Admins: View all reports city-wide, with optional ward and status filtering.
    - Ward Supervisors: Strictly restricted to active ward assignments (revoked_at IS NULL).
      - If ward_id is supplied, supervisor must be actively assigned to that ward; otherwise 403 Forbidden.
      - If ward_id is omitted, returns only reports within the supervisor's active wards.
      - Unassigned reports (ward_id IS NULL) are never exposed to supervisors.
    """
    stmt = select(DumpingReport).options(selectinload(DumpingReport.evidence))

    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        assign_stmt = select(UserWardAssignment.ward_id).where(
            UserWardAssignment.user_id == current_user.id,
            UserWardAssignment.revoked_at.is_(None),
        )
        assign_res = await db.execute(assign_stmt)
        active_ward_ids = assign_res.scalars().all()

        if ward_id is not None:
            if ward_id not in active_ward_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: Supervisor is not actively assigned to this ward.",
                )
            stmt = stmt.where(DumpingReport.ward_id == ward_id)
        else:
            if not active_ward_ids:
                return []
            stmt = stmt.where(DumpingReport.ward_id.in_(active_ward_ids))
    else:
        # Municipal Admin
        if ward_id is not None:
            stmt = stmt.where(DumpingReport.ward_id == ward_id)

    if report_status is not None:
        stmt = stmt.where(DumpingReport.status == report_status.value)

    stmt = stmt.order_by(DumpingReport.created_at.desc())
    res = await db.execute(stmt)
    reports = res.scalars().all()
    return [DumpingReportResponse.from_orm_model(r) for r in reports]


@router.patch(
    "/{report_id}/status",
    response_model=DumpingReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Report Status & Review Notes",
    description="Updates the lifecycle status of a dumping report. Enforces valid state transitions and appends to the audit history.",
)
async def update_report_status(
    report_id: uuid.UUID,
    payload: DumpingReportStatusUpdateRequest,
    current_user: User = Depends(
        require_roles(UserRole.MUNICIPAL_ADMIN, UserRole.WARD_SUPERVISOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> DumpingReportResponse:
    """
    Official status update endpoint.

    Lifecycle & Authorization:
    - Enforces valid state transitions. Terminal statuses (RESOLVED, REJECTED) cannot be transitioned further.
    - Ward Supervisors can only review reports in their actively assigned wards.
    - Unassigned reports (ward_id IS NULL) can only be reviewed by Municipal Admins.
    - Appends an audit event to status_history preserving historical notes and timestamps.
    - Updates latest official_notes.
    """
    stmt = (
        select(DumpingReport)
        .options(selectinload(DumpingReport.evidence))
        .where(DumpingReport.id == report_id)
    )
    res = await db.execute(stmt)
    report = res.scalars().first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found.",
        )

    # Ward-level authorization check for supervisors
    if current_user.role == UserRole.WARD_SUPERVISOR.value:
        if report.ward_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Supervisor cannot review reports that are not assigned to any ward.",
            )
        await verify_ward_access(current_user, report.ward_id, db)

    # Validate state transition
    target_status = payload.status.value
    allowed_targets = ALLOWED_STATUS_TRANSITIONS.get(report.status, set())
    if target_status not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition from '{report.status}' to '{target_status}'.",
        )

    now_iso = utc_now().isoformat()
    clean_notes = payload.official_notes.strip() if payload.official_notes else None

    audit_entry = {
        "from_status": report.status,
        "to_status": target_status,
        "changed_by_user_id": str(current_user.id),
        "notes": clean_notes,
        "timestamp": now_iso,
    }

    # Append to status history (preserving existing entries)
    current_history = list(report.status_history or [])
    current_history.append(audit_entry)
    report.status_history = current_history

    report.status = target_status
    if clean_notes is not None:
        report.official_notes = clean_notes

    await db.commit()

    # Reload with evidence collection to prevent MissingGreenlet in async sessions
    stmt = (
        select(DumpingReport)
        .options(selectinload(DumpingReport.evidence))
        .where(DumpingReport.id == report.id)
    )
    res = await db.execute(stmt)
    persisted_report = res.scalar_one()

    return DumpingReportResponse.from_orm_model(persisted_report)


@router.get(
    "/{report_id}/evidence/{evidence_id}",
    summary="Download/Stream Evidence Photo",
    description="Streams a private evidence image file. Strictly authenticated and authorization-scoped.",
)
async def get_evidence_file(
    report_id: uuid.UUID,
    evidence_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """
    Authenticated evidence streaming endpoint.

    Access Control:
    - CITIZEN: Granted only if they are the original reporter of this incident.
    - MUNICIPAL_ADMIN: Granted city-wide.
    - WARD_SUPERVISOR: Granted only if the report belongs to an actively assigned ward.
    - All other roles: Denied with HTTP 403 Forbidden.
    """
    report = await db.get(DumpingReport, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found.",
        )

    # Authorization verification
    if current_user.role == UserRole.CITIZEN.value:
        if report.reporter_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to report evidence.",
            )
    elif current_user.role == UserRole.MUNICIPAL_ADMIN.value:
        pass
    elif current_user.role == UserRole.WARD_SUPERVISOR.value:
        if report.ward_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Report has no ward assignment.",
            )
        await verify_ward_access(current_user, report.ward_id, db)
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to access evidence files.",
        )

    # Retrieve evidence record
    stmt = select(ReportEvidence).where(
        ReportEvidence.id == evidence_id,
        ReportEvidence.report_id == report_id,
    )
    res = await db.execute(stmt)
    evidence = res.scalars().first()

    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence '{evidence_id}' not found for this report.",
        )

    file_path = get_evidence_file_path(evidence.storage_key)

    return FileResponse(
        path=str(file_path),
        media_type=evidence.content_type,
        filename=evidence.file_name,
    )
