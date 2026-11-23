import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING, Any
from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.collection_point import CollectionPoint
    from app.models.route import CollectionRoute
    from app.models.attendance import MusterPoint, AttendanceRecord


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class Ward(Base):
    """
    Ward entity representing municipal administrative boundaries.
    Boundary geometry is stored as a MultiPolygon in WGS 84 (EPSG:4326).
    """
    __tablename__ = "wards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    ward_code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    boundary: Mapped[Optional[Any]] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=True),
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

    # Relationships
    user_assignments: Mapped[list["UserWardAssignment"]] = relationship(
        "UserWardAssignment",
        back_populates="ward",
        cascade="all, delete-orphan",
    )
    collection_points: Mapped[list["CollectionPoint"]] = relationship(
        "CollectionPoint",
        back_populates="ward",
        cascade="all, delete-orphan",
    )
    routes: Mapped[list["CollectionRoute"]] = relationship(
        "CollectionRoute",
        back_populates="ward",
        cascade="all, delete-orphan",
    )
    muster_points: Mapped[list["MusterPoint"]] = relationship(
        "MusterPoint",
        back_populates="ward",
        cascade="all, delete-orphan",
    )
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        foreign_keys="AttendanceRecord.ward_id",
        back_populates="ward",
    )

    @property
    def name(self) -> str:
        """Citizen-facing alias for display_name."""
        return self.display_name

    @property
    def ward_number(self) -> str:
        """Citizen-facing alias for ward_code."""
        return self.ward_code

    def __repr__(self) -> str:
        return f"<Ward id={self.id} code={self.ward_code} name={self.display_name}>"


class UserWardAssignment(Base):
    """
    Association entity linking operational personnel (drivers, workers, supervisors)
    to specific wards.

    Design details on Historical Assignments:
    - `assigned_at`: Start timestamp of assignment.
    - `revoked_at`: NULL while assignment is actively in effect. When an assignment
      ends or is transferred, `revoked_at` is set to the revocation timestamp.
    - Partial Unique Index: `uq_active_user_ward_assignment` enforces that a user
      cannot have duplicate *active* (`revoked_at IS NULL`) assignments to the same ward.
      Past historical assignments (`revoked_at IS NOT NULL`) remain preserved in the audit
      trail without blocking future re-assignments.
    """
    __tablename__ = "user_ward_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="ward_assignments")
    ward: Mapped["Ward"] = relationship("Ward", back_populates="user_assignments")

    __table_args__ = (
        # Partial unique index: A user can only have one ACTIVE assignment per ward.
        # Historical records (revoked_at IS NOT NULL) do not block re-assignment.
        Index(
            "uq_active_user_ward_assignment",
            "user_id",
            "ward_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<UserWardAssignment id={self.id} user_id={self.user_id} ward_id={self.ward_id} active={self.revoked_at is None}>"
