"""
SQLAlchemy models for Pourakarmika (Sanitation Worker) recurring work schedules
and date-specific attendance overrides.
"""

import uuid
from datetime import datetime, date, timezone
from typing import Optional, TYPE_CHECKING, List
from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    CheckConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.ward import Ward
    from app.models.route import CollectionRoute


def utc_now() -> datetime:
    """Returns current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class WorkerSchedule(Base):
    """
    Recurring weekly work schedule for sanitation workers.
    Enforces shift windows, check-in windows, assigned ward, and optional collection route.
    """
    __tablename__ = "worker_schedules"

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
    route_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collection_routes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Days of week: stored as JSON array of ISO weekday integers [1..7] (1=Monday, 6=Saturday, 7=Sunday)
    days_of_week: Mapped[List[int]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: [1, 2, 3, 4, 5, 6],
    )
    shift_start_time: Mapped[str] = mapped_column(
        String(10),  # e.g. "07:00"
        nullable=False,
        default="07:00",
    )
    shift_end_time: Mapped[str] = mapped_column(
        String(10),  # e.g. "14:00"
        nullable=False,
        default="14:00",
    )
    check_in_start_time: Mapped[str] = mapped_column(
        String(10),  # e.g. "06:45"
        nullable=False,
        default="06:45",
    )
    check_in_end_time: Mapped[str] = mapped_column(
        String(10),  # e.g. "07:30"
        nullable=False,
        default="07:30",
    )
    check_out_start_time: Mapped[Optional[str]] = mapped_column(
        String(10),  # e.g. "13:45"
        nullable=True,
    )
    check_out_end_time: Mapped[Optional[str]] = mapped_column(
        String(10),  # e.g. "15:00"
        nullable=True,
    )
    grace_period_minutes: Mapped[int] = mapped_column(
        Integer,
        default=10,
        server_default=text("10"),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(50),
        default="Asia/Kolkata",
        server_default=text("'Asia/Kolkata'"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        default=date.today,
    )
    effective_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
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
    worker: Mapped["User"] = relationship("User", foreign_keys=[worker_id])
    ward: Mapped["Ward"] = relationship("Ward", foreign_keys=[ward_id])
    route: Mapped[Optional["CollectionRoute"]] = relationship("CollectionRoute", foreign_keys=[route_id])
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<WorkerSchedule id={self.id} worker_id={self.worker_id} shift={self.shift_start_time}-{self.shift_end_time} active={self.is_active}>"


class ScheduleOverride(Base):
    """
    Date-specific schedule override (Day off, Holiday, Leave, Special shift).
    Takes precedence over recurring weekly schedule.
    """
    __tablename__ = "schedule_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    override_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    # Types: DAY_OFF, HOLIDAY, LEAVE, SPECIAL_SHIFT
    override_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    shift_start_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    shift_end_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    check_in_start_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    check_in_end_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
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

    worker: Mapped["User"] = relationship("User", foreign_keys=[worker_id])
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<ScheduleOverride id={self.id} worker_id={self.worker_id} date={self.override_date} type={self.override_type}>"
