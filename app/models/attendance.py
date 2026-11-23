"""
SQLAlchemy models for Pourakarmika attendance and roll-call muster stations.
"""

import uuid
from datetime import datetime, date, timezone
from typing import Optional, TYPE_CHECKING, Any
from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    Date,
    Float,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.core.database import Base
from app.models.enums import AttendanceStatus

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.ward import Ward


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class MusterPoint(Base):
    """
    MusterPoint entity representing designated physical roll-call and reporting stations
    where Pourakarmikas report for daily shift check-in and check-out within a Ward.
    Coordinates are stored as PostGIS Point geometry (WGS 84 / EPSG:4326).
    """
    __tablename__ = "muster_points"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    location: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    geofence_radius_meters: Mapped[int] = mapped_column(
        Integer,
        default=150,
        server_default=text("150"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
        index=True,
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
    ward: Mapped["Ward"] = relationship(
        "Ward",
        back_populates="muster_points",
    )
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        foreign_keys="AttendanceRecord.muster_point_id",
        back_populates="muster_point",
    )
    qr_tokens: Mapped[list["AttendanceQrToken"]] = relationship(
        "AttendanceQrToken",
        back_populates="muster_point",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "geofence_radius_meters > 0",
            name="ck_muster_points_positive_geofence_radius",
        ),
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("geofence_radius_meters", 150)
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<MusterPoint id={self.id} ward_id={self.ward_id} name={self.name} radius={self.geofence_radius_meters}m active={self.is_active}>"


class AttendanceRecord(Base):
    """
    AttendanceRecord entity representing daily check-in, check-out, geofence verification,
    and supervisory review of Pourakarmika (sanitation worker) shifts.

    Design details on Foreign-Key Deletion & Data Retention:
    - `worker_id` (users.id): RESTRICT. Prevents accidental deletion of worker accounts
      if historical payroll, civic employment, and attendance audits exist.
    - `ward_id` (wards.id): RESTRICT. Prevents deleting wards that possess civic audit trails.
    - `muster_point_id` (muster_points.id): SET NULL. Decommissioning or relocating a muster
      station does not destroy or cascade-delete past attendance logs; historical records retain
      recorded GPS coordinates while setting muster_point_id to NULL.
    - `reviewed_by` (users.id): SET NULL. If a supervisor account is deactivated or deleted,
      the record preserves the approval status, timestamps, and notes while setting reviewed_by to NULL.
    """
    __tablename__ = "attendance_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    muster_point_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("muster_points.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    attendance_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    check_in_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    check_out_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    check_in_location: Mapped[Optional[Any]] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True),
        nullable=True,
    )
    check_out_location: Mapped[Optional[Any]] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True),
        nullable=True,
    )
    check_in_distance_meters: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    check_out_distance_meters: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=AttendanceStatus.PRESENT.value,
        server_default=text("'PRESENT'"),
        index=True,
    )
    exception_reason: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_notes: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
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

    # Explicit relationships with foreign_keys specified to avoid ambiguity
    worker: Mapped["User"] = relationship(
        "User",
        foreign_keys=[worker_id],
        back_populates="attendance_records",
    )
    reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[reviewed_by],
        back_populates="reviewed_attendances",
    )
    ward: Mapped["Ward"] = relationship(
        "Ward",
        foreign_keys=[ward_id],
        back_populates="attendance_records",
    )
    muster_point: Mapped[Optional["MusterPoint"]] = relationship(
        "MusterPoint",
        foreign_keys=[muster_point_id],
        back_populates="attendance_records",
    )

    __table_args__ = (
        # 1. At most one attendance record per worker per attendance date
        UniqueConstraint("worker_id", "attendance_date", name="uq_worker_daily_attendance"),
        # 2. Check constraint on valid status
        CheckConstraint(
            "status IN ('PRESENT', 'ABSENT', 'HALF_DAY', 'EXCEPTION_PENDING', 'REJECTED')",
            name="ck_attendance_valid_status",
        ),
        # 3. Check-out cannot exist without check-in
        CheckConstraint(
            "check_out_at IS NULL OR check_in_at IS NOT NULL",
            name="ck_attendance_checkout_requires_checkin",
        ),
        # 4. Check-out is not earlier than check-in
        CheckConstraint(
            "check_out_at IS NULL OR check_in_at IS NULL OR check_out_at >= check_in_at",
            name="ck_attendance_checkout_gte_checkin",
        ),
        # 5. Recorded distances cannot be negative
        CheckConstraint(
            "check_in_distance_meters IS NULL OR check_in_distance_meters >= 0",
            name="ck_attendance_check_in_distance_non_negative",
        ),
        CheckConstraint(
            "check_out_distance_meters IS NULL OR check_out_distance_meters >= 0",
            name="ck_attendance_check_out_distance_non_negative",
        ),
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", AttendanceStatus.PRESENT.value)
        kwargs.setdefault("created_at", utc_now())
        kwargs.setdefault("updated_at", utc_now())
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<AttendanceRecord id={self.id} worker_id={self.worker_id} date={self.attendance_date} status={self.status}>"


class AttendanceQrToken(Base):
    """
    AttendanceQrToken entity representing cryptographically secure, time-limited,
    single-use QR tokens issued by authorized municipal officials for roll-call attendance.

    Security & Lifecycle Invariants:
    - High-entropy cryptographic token, stored securely as a SHA-256 hash.
    - Bound to a specific active MusterPoint and administrative Ward.
    - Expires automatically 5 minutes after issuance.
    - Single-use: atomically records redeemed_at, redeemed_by, and attendance_record_id upon check-in.
    - Replay-resistant: cannot be reused or concurrently redeemed.
    """
    __tablename__ = "attendance_qr_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    muster_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("muster_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issued_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    redeemed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    attendance_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    muster_point: Mapped["MusterPoint"] = relationship("MusterPoint", back_populates="qr_tokens")
    ward: Mapped["Ward"] = relationship("Ward")
    issuer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[issued_by])
    redeemer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[redeemed_by])
    attendance_record: Mapped[Optional["AttendanceRecord"]] = relationship(
        "AttendanceRecord", foreign_keys=[attendance_record_id]
    )

    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="ck_qr_token_expiry_after_issue"),
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("created_at", utc_now())
        kwargs.setdefault("updated_at", utc_now())
        super().__init__(**kwargs)

    @property
    def is_expired(self) -> bool:
        """Returns True if the current time has passed the expiration instant."""
        return utc_now() > self.expires_at

    @property
    def is_redeemed(self) -> bool:
        """Returns True if this token has already been redeemed."""
        return self.redeemed_at is not None

    def __repr__(self) -> str:
        return f"<AttendanceQrToken id={self.id} muster_point_id={self.muster_point_id} expired={self.is_expired} redeemed={self.is_redeemed}>"

