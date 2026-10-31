"""
Pydantic schemas for CollectionPoint resources.
"""

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

from geoalchemy2.shape import to_shape

from app.models.enums import CollectionPointType
from app.models.collection_point import CollectionPoint


class CollectionPointCreateRequest(BaseModel):
    """
    Schema for creating a collection point within a designated ward.
    Restricted to authorized municipal administrators and ward supervisors.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Descriptive identifier for the collection point.",
    )
    point_type: CollectionPointType = Field(
        ...,
        description="Categorization of the collection point.",
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="WGS 84 latitude coordinate (-90 to +90).",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="WGS 84 longitude coordinate (-180 to +180).",
    )
    is_active: bool = Field(
        default=True,
        description="Operating status flag for the collection point.",
    )
    is_published: bool = Field(
        default=False,
        description="Whether this collection point is approved for public display.",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Name cannot be empty or contain only whitespace.")
        return stripped


class CollectionPointUpdateRequest(BaseModel):
    """
    Schema for partial update of a collection point.
    Rejects unexpected fields and protected publication transitions.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="Updated name for collection point.",
    )
    point_type: Optional[CollectionPointType] = Field(
        default=None,
        description="Updated classification.",
    )
    latitude: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Updated WGS 84 latitude.",
    )
    longitude: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Updated WGS 84 longitude.",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Active/deactivated status flag.",
    )
    ward_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional target ward ID for reassignment (role-verified).",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Name cannot be empty or contain only whitespace.")
            return stripped
        return v

    def model_post_init(self, __context) -> None:
        if (self.latitude is not None and self.longitude is None) or (
            self.longitude is not None and self.latitude is None
        ):
            raise ValueError("Both latitude and longitude must be provided together.")



class CollectionPointResponse(BaseModel):
    """
    Public representation of a collection point, returning coordinates
    as explicit WGS 84 latitude and longitude.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_id: uuid.UUID
    name: str
    point_type: str
    latitude: float
    longitude: float
    is_active: bool
    is_published: bool = False
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, cp: CollectionPoint) -> "CollectionPointResponse":
        """Converts a CollectionPoint ORM model into CollectionPointResponse."""
        shape = to_shape(cp.location)
        return cls(
            id=cp.id,
            ward_id=cp.ward_id,
            name=cp.name,
            point_type=cp.point_type,
            latitude=shape.y,
            longitude=shape.x,
            is_active=cp.is_active,
            is_published=bool(cp.is_published),
            created_at=cp.created_at,
            updated_at=cp.updated_at,
        )
