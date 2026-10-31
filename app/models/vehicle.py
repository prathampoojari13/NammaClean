"""
Vehicle and VehiclePosition models for waste fleet management and GPS telemetry.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING, Any
from sqlalchemy import (
    String,
    Boolean,
    Float,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.core.database import Base
from app.models.enums import VehicleStatus, VehicleType

if TYPE_CHECKING:
    from app.models.ward import Ward
    from app.models.user import User


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class Vehicle(Base):
    """
    Vehicle entity representing collection trucks, auto-tippers, and sweepers.
    Maintains current operational status and an atomic cached snapshot of its
    last-known location and freshness timestamp.
    """
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    registration_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    vehicle_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=VehicleStatus.IDLE.value,
        index=True,
        nullable=False,
    )
    assigned_ward_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_driver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    current_location: Mapped[Optional[Any]] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True),
        nullable=True,
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_simulated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
        index=True,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
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
    assigned_ward: Mapped[Optional["Ward"]] = relationship("Ward")
    assigned_driver: Mapped[Optional["User"]] = relationship("User")
    positions: Mapped[list["VehiclePosition"]] = relationship(
        "VehiclePosition",
        back_populates="vehicle",
        cascade="all, delete-orphan",
        order_by="desc(VehiclePosition.recorded_at)",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('IDLE', 'ON_DUTY', 'COLLECTING', 'MAINTENANCE', 'OFFLINE')",
            name="ck_vehicles_valid_status",
        ),
        CheckConstraint(
            "vehicle_type IN ('AUTO_TIPPER', 'COMPACTOR_TRUCK', 'MECHANICAL_SWEEPER', 'LORRY')",
            name="ck_vehicles_valid_type",
        ),
    )

    def __repr__(self) -> str:
        return f"<Vehicle id={self.id} reg={self.registration_number} type={self.vehicle_type} status={self.status}>"


class VehiclePosition(Base):
    """
    Historical time-series telemetry record of a vehicle's GPS positions.
    Maintains immutable breadcrumb trail with explicit simulation tagging.
    """
    __tablename__ = "vehicle_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    speed_kmh: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    heading: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    is_simulated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="positions")

    __table_args__ = (
        Index(
            "ix_vehicle_positions_vehicle_recorded_at",
            "vehicle_id",
            text("recorded_at DESC"),
        ),
        CheckConstraint(
            "speed_kmh IS NULL OR speed_kmh >= 0.0",
            name="ck_vehicle_positions_speed_non_negative",
        ),
        CheckConstraint(
            "heading IS NULL OR (heading >= 0.0 AND heading <= 360.0)",
            name="ck_vehicle_positions_heading_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<VehiclePosition id={self.id} vehicle_id={self.vehicle_id} recorded_at={self.recorded_at} simulated={self.is_simulated}>"
