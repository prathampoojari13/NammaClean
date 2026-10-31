"""
Pydantic schemas for citizen illegal dumping reports and evidence management.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
from geoalchemy2.shape import to_shape

from app.models.enums import DumpingReportStatus
from app.models.dumping_report import DumpingReport, ReportEvidence


class DumpingReportCreateRequest(BaseModel):
    """
    Schema for citizen submission of an illegal dumping report.
    Rejects unexpected, privileged, or server-controlled workflow fields.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    description: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Detailed description of the dumping incident or waste overflow (10-1000 characters).",
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="WGS 84 latitude coordinate of incident (-90 to +90).",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="WGS 84 longitude coordinate of incident (-180 to +180).",
    )
    ward_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional municipal ward ID where the incident occurred.",
    )

    @field_validator("description")
    @classmethod
    def validate_description_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 10:
            raise ValueError("Description must contain at least 10 non-whitespace characters.")
        return stripped


class DumpingReportStatusUpdateRequest(BaseModel):
    """
    Schema for authorized officials (Admins and Supervisors) to transition report status.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    status: DumpingReportStatus = Field(
        ...,
        description="Target lifecycle status.",
    )
    official_notes: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional internal review or cleanup action notes.",
    )


class ReportEvidenceResponse(BaseModel):
    """
    Safe public representation of attached evidence metadata.
    Excludes server storage paths or secrets.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_id: uuid.UUID
    file_name: str
    file_size_bytes: int
    content_type: str
    created_at: datetime


class DumpingReportResponse(BaseModel):
    """
    Response representation of an illegal dumping incident report.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reporter_id: Optional[uuid.UUID] = None
    ward_id: Optional[uuid.UUID] = None
    latitude: float
    longitude: float
    description: str
    status: str
    official_notes: Optional[str] = None
    status_history: List[Dict[str, Any]] = []
    evidence: List[ReportEvidenceResponse] = []
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, r: DumpingReport) -> "DumpingReportResponse":
        shape = to_shape(r.location)
        evidence_list = [
            ReportEvidenceResponse.model_validate(e)
            for e in (r.evidence or [])
        ]
        return cls(
            id=r.id,
            reporter_id=r.reporter_id,
            ward_id=r.ward_id,
            latitude=shape.y,
            longitude=shape.x,
            description=r.description,
            status=r.status,
            official_notes=r.official_notes,
            status_history=r.status_history or [],
            evidence=evidence_list,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
