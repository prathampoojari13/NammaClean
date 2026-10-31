"""
Evidence storage service for development and testing.
Provides secure local filesystem storage for citizen-submitted photographic evidence.

NOTE ON STORAGE LIFECYCLE:
Local filesystem storage is intended for local development and demonstration.
Files stored in this directory are not guaranteed to persist across production
container restarts or instance replacements. For production deployments, an object
storage adapter (e.g. S3 / GCS / Azure Blob) should be configured.
"""

import os
import uuid
import logging
import email
from pathlib import Path
from typing import Tuple
from fastapi import Request, UploadFile, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

# Permitted MIME types and their validated file signatures (magic bytes)
ALLOWED_MIME_TYPES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],  # WebP files begin with 'RIFF' and contain 'WEBP' at offset 8
}

MIME_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def get_evidence_storage_dir() -> Path:
    """
    Returns the resolved absolute path to the local evidence storage directory.
    Creates parent directories if they do not exist.
    """
    storage_path = Path(settings.EVIDENCE_STORAGE_PATH).resolve()
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


def validate_image_magic_bytes(header: bytes, content_type: str) -> bool:
    """
    Validates that the file header matches known binary signatures for the declared content type.
    Protects against disguised executable or script uploads.
    """
    if content_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    elif content_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    elif content_type == "image/webp":
        return len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    return False


async def store_evidence_upload(request: Request) -> Tuple[str, str, int, str]:
    """
    Accepts, validates, and stores an uploaded evidence photo directly from the HTTP request.
    Supports:
    1. Direct binary image streams (Content-Type: image/jpeg, image/png, image/webp)
    2. Multipart form uploads (Content-Type: multipart/form-data) via standard library parsing
    Does not require external multipart dependencies.
    """
    raw_content_type = request.headers.get("content-type", "")
    content_type_clean = raw_content_type.split(";")[0].strip().lower()

    if content_type_clean == "multipart/form-data":
        body = await request.body()
        if len(body) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )
        header_bytes = f"Content-Type: {raw_content_type}\r\n\r\n".encode("utf-8")
        msg = email.message_from_bytes(header_bytes + body)
        file_part = None
        for part in msg.walk():
            if part.get_content_disposition() == "form-data" and part.get_filename():
                file_part = part
                break

        if not file_part:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file found in multipart upload.",
            )

        declared_type = (file_part.get_content_type() or "").lower().strip()
        raw_filename = file_part.get_filename() or "evidence.jpg"
        payload = file_part.get_payload(decode=True) or b""

        if declared_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported image type '{declared_type}'. Allowed types: JPEG, PNG, WebP.",
            )

        if len(payload) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        max_bytes = settings.MAX_EVIDENCE_FILE_SIZE_BYTES
        if len(payload) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File exceeds maximum allowed size of {max_bytes // (1024 * 1024)} MB.",
            )

        if not validate_image_magic_bytes(payload[:16], declared_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match the declared image format.",
            )

        ext = MIME_TO_EXTENSION[declared_type]
        storage_key = f"{uuid.uuid4().hex}{ext}"
        storage_dir = get_evidence_storage_dir()
        destination_path = storage_dir / storage_key
        sanitized_filename = Path(raw_filename).name[:255] or f"evidence{ext}"

        with open(destination_path, "wb") as f:
            f.write(payload)

        return sanitized_filename, storage_key, len(payload), declared_type

    elif content_type_clean in ALLOWED_MIME_TYPES:
        declared_type = content_type_clean
        ext = MIME_TO_EXTENSION[declared_type]
        storage_key = f"{uuid.uuid4().hex}{ext}"
        storage_dir = get_evidence_storage_dir()
        destination_path = storage_dir / storage_key

        raw_filename = request.headers.get("x-file-name")
        if not raw_filename:
            cd = request.headers.get("content-disposition", "")
            if "filename=" in cd:
                raw_filename = cd.split("filename=")[-1].strip('"\'; ')
        sanitized_filename = Path(raw_filename or f"evidence{ext}").name[:255] or f"evidence{ext}"

        total_bytes = 0
        max_bytes = settings.MAX_EVIDENCE_FILE_SIZE_BYTES
        header_checked = False

        try:
            with open(destination_path, "wb") as out_file:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    if not header_checked:
                        if not validate_image_magic_bytes(chunk[:16], declared_type):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="File content does not match the declared image format.",
                            )
                        header_checked = True

                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File exceeds maximum allowed size of {max_bytes // (1024 * 1024)} MB.",
                        )
                    out_file.write(chunk)

            if total_bytes == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty.",
                )

            return sanitized_filename, storage_key, total_bytes, declared_type
        except Exception:
            if destination_path.exists():
                try:
                    destination_path.unlink()
                except OSError:
                    pass
            raise
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image type '{content_type_clean}'. Allowed types: JPEG, PNG, WebP.",
        )


async def store_evidence_file(file: UploadFile) -> Tuple[str, str, int, str]:
    """
    Streams, validates, and stores an evidence file locally.

    Safety & Validation:
    - Verifies declared Content-Type is an approved image type.
    - Enforces maximum file size (MAX_EVIDENCE_FILE_SIZE_BYTES) while streaming chunks.
    - Inspects binary magic bytes on initial chunk to verify true content format.
    - Generates a random, server-controlled UUID storage key and filename.
    - Never uses client-provided filenames as filesystem paths, neutralizing path traversal attacks.

    Returns:
        Tuple of (sanitized_original_filename, storage_key, file_size_bytes, validated_content_type)
    """
    declared_content_type = (file.content_type or "").lower().strip()
    if declared_content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image type '{declared_content_type}'. Allowed types: JPEG, PNG, WebP.",
        )

    ext = MIME_TO_EXTENSION[declared_content_type]
    storage_key = f"{uuid.uuid4().hex}{ext}"
    storage_dir = get_evidence_storage_dir()
    destination_path = storage_dir / storage_key

    # Sanitize client-supplied filename for metadata only
    raw_filename = file.filename or "evidence.jpg"
    sanitized_filename = Path(raw_filename).name[:255] or "evidence.jpg"

    total_bytes = 0
    max_bytes = settings.MAX_EVIDENCE_FILE_SIZE_BYTES
    header_checked = False

    try:
        with open(destination_path, "wb") as out_file:
            while True:
                chunk = await file.read(64 * 1024)  # 64 KB read buffer
                if not chunk:
                    break

                if not header_checked:
                    if not validate_image_magic_bytes(chunk[:16], declared_content_type):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="File content does not match the declared image format.",
                        )
                    header_checked = True

                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File exceeds maximum allowed size of {max_bytes // (1024 * 1024)} MB.",
                    )

                out_file.write(chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        return sanitized_filename, storage_key, total_bytes, declared_content_type

    except Exception:
        # Clean up partial/rejected file on disk
        if destination_path.exists():
            try:
                destination_path.unlink()
            except OSError:
                pass
        raise


def get_evidence_file_path(storage_key: str) -> Path:
    """
    Resolves the filesystem path for an evidence storage key.
    Enforces that the path remains strictly inside the evidence storage directory.
    """
    storage_dir = get_evidence_storage_dir()
    safe_name = Path(storage_key).name
    target_path = (storage_dir / safe_name).resolve()

    # Prevent directory traversal attacks
    if not str(target_path).startswith(str(storage_dir)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )

    if not target_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence file not found on storage.",
        )

    return target_path


def remove_evidence_file(storage_key: str) -> None:
    """
    Safely removes an evidence file from local disk.
    """
    try:
        path = get_evidence_file_path(storage_key)
        if path.exists():
            path.unlink()
    except Exception as exc:
        logger.warning("Could not delete evidence file '%s': %s", storage_key, exc)
