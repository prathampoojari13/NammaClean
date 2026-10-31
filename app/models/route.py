"""
CollectionRoute and RouteStop models for municipal collection route management.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING, Any
from sqlalchemy import (
    String,
    Boolean,
    Integer,
    DateTime,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.ward import Ward
    from app.models.collection_point import CollectionPoint


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class CollectionRoute(Base):
    """
    CollectionRoute entity representing a scheduled or operational collection path
    within a Ward, defined as a WGS 84 LineString geometry.
    """
    __tablename__ = "collection_routes"

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
    route_code: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    route_path: Mapped[Any] = mapped_column(
        Geometry("LINESTRING", srid=4326, spatial_index=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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
    is_simulated: Mapped[bool] = mapped_column(
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
    ward: Mapped["Ward"] = relationship(
        "Ward",
        back_populates="routes",
    )
    stops: Mapped[list["RouteStop"]] = relationship(
        "RouteStop",
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="RouteStop.stop_sequence.asc()",
    )

    def __repr__(self) -> str:
        return f"<CollectionRoute id={self.id} ward_id={self.ward_id} name={self.name} active={self.is_active}>"


class RouteStop(Base):
    """
    RouteStop entity representing an ordered collection point along a collection route.
    Enforces sequential ordering and arrival offset timing.
    """
    __tablename__ = "route_stops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collection_routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collection_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stop_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    planned_arrival_offset_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
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
    route: Mapped["CollectionRoute"] = relationship(
        "CollectionRoute",
        back_populates="stops",
    )
    collection_point: Mapped["CollectionPoint"] = relationship(
        "CollectionPoint",
    )

    __table_args__ = (
        UniqueConstraint(
            "route_id",
            "stop_sequence",
            name="uq_route_stops_route_sequence",
        ),
        CheckConstraint(
            "stop_sequence > 0",
            name="ck_route_stops_positive_sequence",
        ),
        CheckConstraint(
            "planned_arrival_offset_minutes IS NULL OR planned_arrival_offset_minutes >= 0",
            name="ck_route_stops_non_negative_offset",
        ),
    )

    def __repr__(self) -> str:
        return f"<RouteStop id={self.id} route_id={self.route_id} seq={self.stop_sequence}>"
