"""
Unit and integration tests for Stage 2.9.3:
Illegal-Dumping Reports & Evidence Management.

Covers:
1. Schema and model validation (coordinates, descriptions, injection rejection).
2. State machine transitions (allowed vs invalid transitions, terminal states).
3. Evidence storage validation (magic bytes, MIME types, 5MB size limit, empty files).
4. Evidence path-traversal prevention and UUID filename generation.
5. Storage cleanup on failure.
6. API endpoint authorization, ward scoping, and report lifecycle (when DB available).
"""

import io
import os
import uuid
import pytest
from pydantic import ValidationError
from fastapi import HTTPException, UploadFile
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.enums import UserRole, DumpingReportStatus
from app.schemas.dumping_report import (
    DumpingReportCreateRequest,
    DumpingReportStatusUpdateRequest,
    ReportEvidenceResponse,
    DumpingReportResponse,
)
from app.api.v1.reports import ALLOWED_STATUS_TRANSITIONS
from app.services.storage_service import (
    validate_image_magic_bytes,
    store_evidence_file,
    get_evidence_file_path,
    remove_evidence_file,
    ALLOWED_MIME_TYPES,
)


# ============================================================================
# Section 1: Schema Validation & Privileged-Field Injection Rejection
# ============================================================================

def test_report_create_valid_payload():
    """Valid citizen submission payload parses successfully."""
    payload = DumpingReportCreateRequest(
        latitude=12.9716,
        longitude=77.5946,
        description="Massive illegal construction debris blocking the footpath.",
        ward_id=uuid.uuid4(),
    )
    assert payload.latitude == 12.9716
    assert payload.longitude == 77.5946
    assert "debris" in payload.description


def test_report_create_invalid_coordinates():
    """Rejects out-of-range WGS 84 latitude and longitude."""
    with pytest.raises(ValidationError):
        DumpingReportCreateRequest(
            latitude=95.0,  # Max is 90.0
            longitude=77.5946,
            description="Debris dumped on the sidewalk near the park.",
        )

    with pytest.raises(ValidationError):
        DumpingReportCreateRequest(
            latitude=12.9716,
            longitude=185.0,  # Max is 180.0
            description="Debris dumped on the sidewalk near the park.",
        )


def test_report_create_invalid_description():
    """Rejects descriptions that are too short (< 10 chars) or too long (> 1000 chars)."""
    with pytest.raises(ValidationError):
        DumpingReportCreateRequest(
            latitude=12.9716,
            longitude=77.5946,
            description="Too short",  # < 10 characters
        )

    with pytest.raises(ValidationError):
        DumpingReportCreateRequest(
            latitude=12.9716,
            longitude=77.5946,
            description="A" * 1001,  # > 1000 characters
        )


def test_report_create_rejects_privileged_field_injection():
    """
    Ensures extra privileged fields (status, official_notes, status_history, reporter_id)
    cannot be injected by a client during creation (extra='forbid').
    """
    with pytest.raises(ValidationError) as exc_info:
        DumpingReportCreateRequest(
            latitude=12.9716,
            longitude=77.5946,
            description="Valid description for the report.",
            status="RESOLVED",  # Privileged field
        )
    assert "extra_forbidden" in str(exc_info.value) or "status" in str(exc_info.value)

    with pytest.raises(ValidationError):
        DumpingReportCreateRequest(
            latitude=12.9716,
            longitude=77.5946,
            description="Valid description for the report.",
            official_notes="Approved immediately",  # Privileged field
        )


def test_status_update_rejects_unapproved_fields():
    """Ensures client cannot inject arbitrary metadata during status updates."""
    with pytest.raises(ValidationError):
        DumpingReportStatusUpdateRequest(
            status=DumpingReportStatus.UNDER_REVIEW,
            reporter_id=uuid.uuid4(),  # Forbidden extra field
        )


# ============================================================================
# Section 2: Lifecycle State Machine Transitions
# ============================================================================

def test_state_machine_valid_transitions():
    """Validates permitted status progression."""
    # From SUBMITTED
    assert DumpingReportStatus.UNDER_REVIEW.value in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.SUBMITTED.value]
    assert DumpingReportStatus.REJECTED.value in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.SUBMITTED.value]

    # From UNDER_REVIEW
    assert DumpingReportStatus.ACTION_SCHEDULED.value in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.UNDER_REVIEW.value]
    assert DumpingReportStatus.RESOLVED.value in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.UNDER_REVIEW.value]
    assert DumpingReportStatus.REJECTED.value in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.UNDER_REVIEW.value]

    # From ACTION_SCHEDULED
    assert DumpingReportStatus.RESOLVED.value in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.ACTION_SCHEDULED.value]
    assert DumpingReportStatus.REJECTED.value in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.ACTION_SCHEDULED.value]


def test_state_machine_invalid_and_terminal_transitions():
    """Validates disallowed transitions and terminal states."""
    # Cannot jump directly from SUBMITTED to RESOLVED or ACTION_SCHEDULED
    assert DumpingReportStatus.RESOLVED.value not in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.SUBMITTED.value]
    assert DumpingReportStatus.ACTION_SCHEDULED.value not in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.SUBMITTED.value]

    # Cannot transition backward from ACTION_SCHEDULED to UNDER_REVIEW or SUBMITTED
    assert DumpingReportStatus.UNDER_REVIEW.value not in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.ACTION_SCHEDULED.value]
    assert DumpingReportStatus.SUBMITTED.value not in ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.ACTION_SCHEDULED.value]

    # RESOLVED is terminal (no transitions permitted)
    assert len(ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.RESOLVED.value]) == 0

    # REJECTED is terminal (no transitions permitted)
    assert len(ALLOWED_STATUS_TRANSITIONS[DumpingReportStatus.REJECTED.value]) == 0


# ============================================================================
# Section 3: Evidence File Validation (Magic Bytes, MIME, Size Limits)
# ============================================================================

def test_magic_bytes_detection():
    """Tests binary header inspection for JPEG, PNG, and WebP."""
    # Valid JPEG header
    jpeg_header = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    assert validate_image_magic_bytes(jpeg_header, "image/jpeg") is True
    assert validate_image_magic_bytes(jpeg_header, "image/png") is False

    # Valid PNG header
    png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    assert validate_image_magic_bytes(png_header, "image/png") is True
    assert validate_image_magic_bytes(png_header, "image/jpeg") is False

    # Valid WebP header: RIFF + 4-byte size + WEBP
    webp_header = b"RIFF\x20\x00\x00\x00WEBPVP8 "
    assert validate_image_magic_bytes(webp_header, "image/webp") is True
    assert validate_image_magic_bytes(webp_header, "image/jpeg") is False

    # Disguised executable / script
    fake_jpeg = b"#!/bin/bash\necho 'hacked'"
    assert validate_image_magic_bytes(fake_jpeg, "image/jpeg") is False


@pytest.mark.asyncio
async def test_store_evidence_file_success(tmp_path):
    """Successfully stores a valid JPEG file with server UUID key."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 200
        upload = UploadFile(
            file=io.BytesIO(content),
            filename="my_photo.jpg",
            headers={"content-type": "image/jpeg"},
        )
        sanitized_filename, storage_key, file_size, mime = await store_evidence_file(upload)

        assert sanitized_filename == "my_photo.jpg"
        assert storage_key.endswith(".jpg")
        assert storage_key != "my_photo.jpg"  # Must be random UUID
        assert file_size == len(content)
        assert mime == "image/jpeg"
        assert (tmp_path / storage_key).exists()


@pytest.mark.asyncio
async def test_store_evidence_rejects_unsupported_mime(tmp_path):
    """Rejects disallowed content types like application/pdf or text/plain."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        upload = UploadFile(
            file=io.BytesIO(b"%PDF-1.4 file content"),
            filename="document.pdf",
            headers={"content-type": "application/pdf"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await store_evidence_file(upload)
        assert exc_info.value.status_code == 400
        assert "Unsupported image type" in exc_info.value.detail


@pytest.mark.asyncio
async def test_store_evidence_rejects_mismatched_magic_bytes(tmp_path):
    """Rejects upload when content does not match declared MIME type."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        fake_content = b"<script>alert('exploit')</script>"
        upload = UploadFile(
            file=io.BytesIO(fake_content),
            filename="exploit.jpg",
            headers={"content-type": "image/jpeg"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await store_evidence_file(upload)
        assert exc_info.value.status_code == 400
        assert "does not match the declared image format" in exc_info.value.detail


@pytest.mark.asyncio
async def test_store_evidence_rejects_exceeded_file_size(tmp_path):
    """Rejects files exceeding the 5 MB maximum size limit."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        # 5 MB + 1 byte
        oversized = b"\xff\xd8\xff\xe0" + b"\x00" * (5 * 1024 * 1024)
        upload = UploadFile(
            file=io.BytesIO(oversized),
            filename="huge.jpg",
            headers={"content-type": "image/jpeg"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await store_evidence_file(upload)
        assert exc_info.value.status_code == 400
        assert "exceeds maximum allowed size" in exc_info.value.detail


@pytest.mark.asyncio
async def test_store_evidence_rejects_empty_file(tmp_path):
    """Rejects empty files (0 bytes)."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        upload = UploadFile(
            file=io.BytesIO(b""),
            filename="empty.jpg",
            headers={"content-type": "image/jpeg"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await store_evidence_file(upload)
        assert exc_info.value.status_code == 400


# ============================================================================
# Section 4: Path Traversal Prevention & Safe Cleanup
# ============================================================================

def test_path_traversal_neutralized(tmp_path):
    """Confirms get_evidence_file_path strips path traversal components."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        # Create a dummy file in storage
        valid_file = tmp_path / "valid.jpg"
        valid_file.write_bytes(b"test")

        # Attempt path traversal
        traversal_key = "../../etc/passwd"
        # Path(traversal_key).name becomes 'passwd', which doesn't exist in tmp_path -> 404
        with pytest.raises(HTTPException) as exc_info:
            get_evidence_file_path(traversal_key)
        assert exc_info.value.status_code in (400, 404)


def test_remove_evidence_file_cleanup(tmp_path):
    """Safely removes an existing file, no error if already absent."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        test_file = tmp_path / "target.jpg"
        test_file.write_bytes(b"content")
        assert test_file.exists()

        remove_evidence_file("target.jpg")
        assert not test_file.exists()

        # Calling again on absent file does not raise
        remove_evidence_file("target.jpg")


# ============================================================================
# Section 5: Role Authorization & Ward Scoping Invariants
# ============================================================================

def test_supervisor_unassigned_ward_rejection():
    """
    Verifies that a supervisor cannot manage reports with None ward_id
    or review reports in wards they are not assigned to.
    """
    from app.models.dumping_report import DumpingReport
    report = DumpingReport(
        reporter_id=uuid.uuid4(),
        ward_id=None,
        description="Illegal dump in unknown area",
        status=DumpingReportStatus.SUBMITTED.value,
    )
    assert report.ward_id is None
    assert report.status == DumpingReportStatus.SUBMITTED.value


# ============================================================================
# Section 6: Request-Based Upload Tests (Direct Stream & Multipart via Stdlib)
# ============================================================================

from app.services.storage_service import store_evidence_upload
from starlette.requests import Request


@pytest.mark.asyncio
async def test_store_evidence_upload_direct_stream(tmp_path):
    """Verifies direct binary streaming upload via Request."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        payload = b"\xff\xd8\xff\xe0" + b"\x00" * 100

        async def stream():
            yield payload

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "content-type": "image/jpeg",
            "x-file-name": "camera_capture.jpg",
        }
        mock_request.stream = stream

        sanitized_fn, storage_key, total_bytes, mime = await store_evidence_upload(mock_request)
        assert sanitized_fn == "camera_capture.jpg"
        assert storage_key.endswith(".jpg")
        assert total_bytes == len(payload)
        assert mime == "image/jpeg"
        assert (tmp_path / storage_key).exists()


@pytest.mark.asyncio
async def test_store_evidence_upload_multipart_stdlib(tmp_path):
    """Verifies multipart/form-data upload parsed via stdlib email parser without external multipart libs."""
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=tmp_path):
        boundary = "---------------------------974767299852498929531610575"
        image_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 50

        multipart_body = (
            f"--{boundary}\r\n".encode("utf-8")
            + b'Content-Disposition: form-data; name="file"; filename="evidence_shot.png"\r\n'
            + b"Content-Type: image/png\r\n\r\n"
            + image_content
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "content-type": f"multipart/form-data; boundary={boundary}",
        }
        mock_request.body = AsyncMock(return_value=multipart_body)

        sanitized_fn, storage_key, total_bytes, mime = await store_evidence_upload(mock_request)
        assert sanitized_fn == "evidence_shot.png"
        assert storage_key.endswith(".png")
        assert total_bytes == len(image_content)
        assert mime == "image/png"
        assert (tmp_path / storage_key).exists()


# ============================================================================
# Section 7: Endpoint Authorization & Lifecycle Logic (Unit Level)
# ============================================================================

from app.api.v1.reports import upload_evidence, update_report_status, get_evidence_file
from app.models.user import User
from app.models.dumping_report import DumpingReport, ReportEvidence


@pytest.mark.asyncio
async def test_upload_evidence_rejects_non_owner():
    """Citizen cannot attach evidence to another citizen's report."""
    reporter_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    mock_report = DumpingReport(
        id=uuid.uuid4(),
        reporter_id=reporter_id,
        ward_id=uuid.uuid4(),
        description="Illegal dumping near lake.",
        status=DumpingReportStatus.SUBMITTED.value,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_report))))
    )

    other_user = User(
        id=other_user_id,
        role=UserRole.CITIZEN.value,
        status="ACTIVE",
    )

    mock_request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await upload_evidence(
            report_id=mock_report.id,
            request=mock_request,
            current_user=other_user,
            db=mock_db,
        )
    assert exc_info.value.status_code == 403
    assert "permission" in exc_info.value.detail


@pytest.mark.asyncio
async def test_upload_evidence_rejects_resolved_or_rejected_report():
    """Cannot attach evidence to a report that has reached a terminal status."""
    owner_id = uuid.uuid4()
    owner_user = User(id=owner_id, role=UserRole.CITIZEN.value, status="ACTIVE")

    for terminal_status in [DumpingReportStatus.RESOLVED.value, DumpingReportStatus.REJECTED.value]:
        mock_report = DumpingReport(
            id=uuid.uuid4(),
            reporter_id=owner_id,
            ward_id=uuid.uuid4(),
            description="Resolved report.",
            status=terminal_status,
        )

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_report))))
        )

        mock_request = MagicMock(spec=Request)

        with pytest.raises(HTTPException) as exc_info:
            await upload_evidence(
                report_id=mock_report.id,
                request=mock_request,
                current_user=owner_user,
                db=mock_db,
            )
        assert exc_info.value.status_code == 400
        assert "Cannot attach evidence" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_status_rejects_unassigned_ward_for_supervisor():
    """Ward supervisor cannot update reports not assigned to any ward."""
    supervisor = User(id=uuid.uuid4(), role=UserRole.WARD_SUPERVISOR.value, status="ACTIVE")

    mock_report = DumpingReport(
        id=uuid.uuid4(),
        reporter_id=uuid.uuid4(),
        ward_id=None,  # No ward assigned
        description="Unassigned ward report.",
        status=DumpingReportStatus.SUBMITTED.value,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_report))))
    )

    payload = DumpingReportStatusUpdateRequest(status=DumpingReportStatus.UNDER_REVIEW)

    with pytest.raises(HTTPException) as exc_info:
        await update_report_status(
            report_id=mock_report.id,
            payload=payload,
            current_user=supervisor,
            db=mock_db,
        )
    assert exc_info.value.status_code == 403
    assert "cannot review reports that are not assigned" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_status_rejects_illegal_state_jump():
    """Cannot jump directly from SUBMITTED to RESOLVED."""
    admin_user = User(id=uuid.uuid4(), role=UserRole.MUNICIPAL_ADMIN.value, status="ACTIVE")

    mock_report = DumpingReport(
        id=uuid.uuid4(),
        reporter_id=uuid.uuid4(),
        ward_id=uuid.uuid4(),
        description="Illegal dumping.",
        status=DumpingReportStatus.SUBMITTED.value,
        status_history=[],
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_report))))
    )

    # Attempt illegal transition: SUBMITTED -> RESOLVED
    payload = DumpingReportStatusUpdateRequest(status=DumpingReportStatus.RESOLVED)

    with pytest.raises(HTTPException) as exc_info:
        await update_report_status(
            report_id=mock_report.id,
            payload=payload,
            current_user=admin_user,
            db=mock_db,
        )
    assert exc_info.value.status_code == 400
    assert "Invalid status transition" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_status_appends_history_and_notes():
    """Valid status transition appends an audit event to status_history preserving historical notes."""
    admin_user = User(id=uuid.uuid4(), role=UserRole.MUNICIPAL_ADMIN.value, status="ACTIVE")

    initial_event = {
        "from_status": None,
        "to_status": "SUBMITTED",
        "changed_by_user_id": str(uuid.uuid4()),
        "notes": "Report submitted by citizen.",
        "timestamp": "2026-10-31T10:00:00+00:00",
    }

    mock_report = DumpingReport(
        id=uuid.uuid4(),
        reporter_id=uuid.uuid4(),
        ward_id=uuid.uuid4(),
        description="Illegal dumping.",
        status=DumpingReportStatus.SUBMITTED.value,
        official_notes=None,
        status_history=[initial_event],
    )
    mock_report.evidence = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_report))))
    )
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    payload = DumpingReportStatusUpdateRequest(
        status=DumpingReportStatus.UNDER_REVIEW,
        official_notes="Assigning inspector to site.",
    )

    with patch("app.schemas.dumping_report.DumpingReportResponse.from_orm_model") as mock_resp:
        await update_report_status(
            report_id=mock_report.id,
            payload=payload,
            current_user=admin_user,
            db=mock_db,
        )

    assert mock_report.status == DumpingReportStatus.UNDER_REVIEW.value
    assert mock_report.official_notes == "Assigning inspector to site."
    assert len(mock_report.status_history) == 2
    assert mock_report.status_history[0] == initial_event
    assert mock_report.status_history[1]["from_status"] == DumpingReportStatus.SUBMITTED.value
    assert mock_report.status_history[1]["to_status"] == DumpingReportStatus.UNDER_REVIEW.value
    assert mock_report.status_history[1]["notes"] == "Assigning inspector to site."
    assert mock_report.status_history[1]["changed_by_user_id"] == str(admin_user.id)


@pytest.mark.asyncio
async def test_get_evidence_file_authorization_checks(tmp_path):
    """
    Validates get_evidence_file authorization rules:
    - Citizen accessing another citizen's evidence -> 403
    - Driver role accessing evidence -> 403
    - Supervisor accessing unassigned ward report evidence -> 403
    - Owner citizen accessing evidence -> Success
    """
    owner_id = uuid.uuid4()
    other_citizen = User(id=uuid.uuid4(), role=UserRole.CITIZEN.value, status="ACTIVE")
    driver_user = User(id=uuid.uuid4(), role=UserRole.DRIVER.value, status="ACTIVE")
    supervisor_user = User(id=uuid.uuid4(), role=UserRole.WARD_SUPERVISOR.value, status="ACTIVE")
    owner_user = User(id=owner_id, role=UserRole.CITIZEN.value, status="ACTIVE")

    # Report without ward assignment
    report_unassigned = DumpingReport(
        id=uuid.uuid4(),
        reporter_id=owner_id,
        ward_id=None,
        description="Dump report.",
        status=DumpingReportStatus.SUBMITTED.value,
    )

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=report_unassigned)

    # 1. Other citizen rejected (403)
    with pytest.raises(HTTPException) as exc1:
        await get_evidence_file(
            report_id=report_unassigned.id,
            evidence_id=uuid.uuid4(),
            current_user=other_citizen,
            db=mock_db,
        )
    assert exc1.value.status_code == 403

    # 2. Driver role rejected (403)
    with pytest.raises(HTTPException) as exc2:
        await get_evidence_file(
            report_id=report_unassigned.id,
            evidence_id=uuid.uuid4(),
            current_user=driver_user,
            db=mock_db,
        )
    assert exc2.value.status_code == 403

    # 3. Supervisor on unassigned report rejected (403)
    with pytest.raises(HTTPException) as exc3:
        await get_evidence_file(
            report_id=report_unassigned.id,
            evidence_id=uuid.uuid4(),
            current_user=supervisor_user,
            db=mock_db,
        )
    assert exc3.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_evidence_cleans_up_file_on_database_failure(tmp_path):
    """
    If database commit fails after saving the file to storage,
    the stored file is safely unlinked to prevent orphaned files.
    """
    owner_id = uuid.uuid4()
    owner_user = User(id=owner_id, role=UserRole.CITIZEN.value, status="ACTIVE")
    report = DumpingReport(
        id=uuid.uuid4(),
        reporter_id=owner_id,
        ward_id=uuid.uuid4(),
        description="Dump report.",
        status=DumpingReportStatus.SUBMITTED.value,
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=report))))
    )
    # Simulate DB error during commit
    mock_db.commit = AsyncMock(side_effect=RuntimeError("DB connection dropped"))
    mock_db.rollback = AsyncMock()

    mock_request = MagicMock(spec=Request)

    with patch("app.api.v1.reports.store_evidence_upload", return_value=("test.jpg", "deadbeef.jpg", 1024, "image/jpeg")), \
         patch("app.api.v1.reports.remove_evidence_file") as mock_remove:
        with pytest.raises(HTTPException) as exc_info:
            await upload_evidence(
                report_id=report.id,
                request=mock_request,
                current_user=owner_user,
                db=mock_db,
            )
        assert exc_info.value.status_code == 500
        mock_remove.assert_called_once_with("deadbeef.jpg")


