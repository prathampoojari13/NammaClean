"""
SQLAlchemy models for citizen illegal dumping reports and evidence attachments.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING, Any, List, Dict
from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    CheckConstraint,
    JSON,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.core.database import Base
from app.models.enums import DumpingReportStatus

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.ward import Ward


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class DumpingReport(Base):
    """
    DumpingReport entity representing civic reports of illegal waste dumping or overflow.
    Incident coordinates are stored as WGS 84 Point geometry (EPSG:4326).
    """
    __tablename__ = "dumping_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    reporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ward_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    location: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=DumpingReportStatus.SUBMITTED.value,
        index=True,
    )
    official_notes: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )
    status_history: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Relationships
    reporter: Mapped[Optional["User"]] = relationship("User")
    ward: Mapped[Optional["Ward"]] = relationship("Ward")
    evidence: Mapped[list["ReportEvidence"]] = relationship(
        "ReportEvidence",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ReportEvidence.created_at.asc()",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('SUBMITTED', 'UNDER_REVIEW', 'ACTION_SCHEDULED', 'RESOLVED', 'REJECTED')",
            name="ck_dumping_reports_valid_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<DumpingReport id={self.id} status={self.status} ward={self.ward_id}>"


class ReportEvidence(Base):
    """
    ReportEvidence entity representing uploaded photographic evidence attached to a report.
    Files are stored in private storage with random server-controlled keys.
    """
    __tablename__ = "report_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dumping_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    report: Mapped["DumpingReport"] = relationship(
        "DumpingReport",
        back_populates="evidence",
    )

    __table_args__ = (
        CheckConstraint(
            "file_size_bytes > 0",
            name="ck_evidence_positive_size",
        ),
    )

    def __repr__(self) -> str:
        return f"<ReportEvidence id={self.id} report_id={self.report_id} key={self.storage_key}>"
