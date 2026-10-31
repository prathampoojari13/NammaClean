"""
CollectionPoint model for municipal waste collection points within wards.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING, Any
from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    ForeignKey,
    CheckConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.core.database import Base
from app.models.enums import CollectionPointType

if TYPE_CHECKING:
    from app.models.ward import Ward


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class CollectionPoint(Base):
    """
    CollectionPoint entity representing designated municipal waste collection locations
    (community bins, DWCCs, door-to-door micro-points, transfer stations) within a Ward.
    """
    __tablename__ = "collection_points"

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
    point_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    location: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=True),
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
        back_populates="collection_points",
    )

    __table_args__ = (
        CheckConstraint(
            "point_type IN ('COMMUNITY_BIN', 'DOOR_TO_DOOR_PICKUP', 'COMMERCIAL_POINT', 'DRY_WASTE_COLLECTION_CENTRE', 'TRANSFER_STATION')",
            name="ck_collection_points_valid_type",
        ),
    )

    def __repr__(self) -> str:
        return f"<CollectionPoint id={self.id} ward_id={self.ward_id} name={self.name} type={self.point_type} active={self.is_active}>"
