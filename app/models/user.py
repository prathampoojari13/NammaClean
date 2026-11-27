import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    String,
    DateTime,
    CheckConstraint,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import UserRole, UserStatus

if TYPE_CHECKING:
    from app.models.ward import Ward, UserWardAssignment
    from app.models.attendance import AttendanceRecord


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def normalize_email(raw_email: Optional[str]) -> str:
    """
    Normalizes an email address by stripping surrounding whitespace and converting to lowercase.
    Raises ValueError if email is empty or invalid.
    """
    if not raw_email or not raw_email.strip():
        raise ValueError("Email address cannot be empty or contain only whitespace.")
    return raw_email.strip().lower()


class User(Base):
    """
    User entity representing citizens, sanitation workers, drivers,
    supervisors, and municipal administrators.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=UserStatus.ACTIVE.value,
        index=True,
    )
    ward_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    locality: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    address: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    full_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    official_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        unique=True,
        nullable=True,
        index=True,
    )
    phone_number: Mapped[Optional[str]] = mapped_column(
        String(20),
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
    ward: Mapped[Optional["Ward"]] = relationship(
        "Ward",
        foreign_keys=[ward_id],
    )
    ward_assignments: Mapped[list["UserWardAssignment"]] = relationship(
        "UserWardAssignment",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        foreign_keys="AttendanceRecord.worker_id",
        back_populates="worker",
    )
    reviewed_attendances: Mapped[list["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        foreign_keys="AttendanceRecord.reviewed_by",
        back_populates="reviewer",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('CITIZEN', 'SANITATION_WORKER', 'DRIVER', 'WARD_SUPERVISOR', 'MUNICIPAL_ADMIN')",
            name="ck_users_valid_role",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED', 'PENDING_VERIFICATION')",
            name="ck_users_valid_status",
        ),
    )

    def __init__(self, **kwargs):
        # Ensure email is consistently normalized before being assigned
        if "email" in kwargs and kwargs["email"] is not None:
            kwargs["email"] = normalize_email(kwargs["email"])
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role} status={self.status}>"
