"""
Pydantic schemas for Ward navigation and administrative boundaries.
"""

import uuid
from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, ConfigDict
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from app.models.ward import Ward


class PublicWardResponse(BaseModel):
    """
    Public-safe representation of an administrative municipal ward.
    Exposes ward code, display name, and optional GeoJSON boundary polygon.
    Strictly omits internal staff assignments and sensitive administration records.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_code: str
    display_name: str
    boundary: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, w: Ward, include_boundary: bool = True) -> "PublicWardResponse":
        """
        Converts a Ward ORM entity into a public-safe response model.
        Serializes PostGIS MultiPolygon boundary to standard GeoJSON geometry dictionary.
        """
        boundary_dict = None
        if include_boundary and w.boundary is not None:
            shape = to_shape(w.boundary)
            boundary_dict = mapping(shape)

        return cls(
            id=w.id,
            ward_code=w.ward_code,
            display_name=w.display_name,
            boundary=boundary_dict,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )


class WardSummaryResponse(BaseModel):
    """
    Lightweight, public-safe summary of an administrative ward for citizen selection dropdowns.
    Exposes only essential fields: ID, name, and ward number.
    Strictly omits internal staff assignments, timestamps, and geospatial boundaries.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    ward_number: str

    @classmethod
    def from_orm_model(cls, w: Ward) -> "WardSummaryResponse":
        """
        Converts a Ward ORM entity into a compact citizen-selection summary.
        Maps display_name -> name and ward_code -> ward_number.
        """
        return cls(
            id=w.id,
            name=w.display_name,
            ward_number=w.ward_code,
        )
