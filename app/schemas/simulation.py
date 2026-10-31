"""
Pydantic schemas for the controlled GPS Simulation Engine and Publication Controls.
"""

import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class PublicationUpdateRequest(BaseModel):
    """
    Schema for updating the publication approval status of an asset
    (vehicle, collection point, or route).
    """
    model_config = ConfigDict(extra="forbid")

    is_published: bool = Field(
        ...,
        description="Whether this resource is approved for public display.",
    )


class SimulationTickRequest(BaseModel):
    """
    Parameters for triggering a controlled simulation step.
    Restricted to Municipal Administrators.
    """
    model_config = ConfigDict(extra="forbid")

    vehicle_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional single demo vehicle ID to step. If omitted, steps all demo vehicles.",
    )
    step_seconds: int = Field(
        default=30,
        ge=1,
        le=3600,
        description="Interval in seconds to advance along the assigned demo route.",
    )


class SimulatedVehicleStep(BaseModel):
    """
    Telemetry update generated during a simulation tick.
    """
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: uuid.UUID
    route_id: Optional[uuid.UUID] = None
    latitude: float
    longitude: float
    speed_kmh: float
    heading: float
    recorded_at: datetime


class SimulationTickResponse(BaseModel):
    """
    Result of a simulation tick execution.
    """
    model_config = ConfigDict(from_attributes=True)

    simulated_vehicles_count: int
    steps: List[SimulatedVehicleStep]
    timestamp: datetime


class SeedDemoFleetRequest(BaseModel):
    """
    Request to initialize demo vehicle and demo route records in a ward.
    """
    model_config = ConfigDict(extra="forbid")

    ward_id: uuid.UUID = Field(
        ...,
        description="Ward in which to seed demo simulation assets.",
    )


class SeedDemoFleetResponse(BaseModel):
    """
    Response returned after seeding demo fleet assets.
    """
    model_config = ConfigDict(from_attributes=True)

    ward_id: uuid.UUID
    vehicle_id: uuid.UUID
    route_id: uuid.UUID
    registration_number: str
    route_code: str
    message: str
    collection_point_ids: List[uuid.UUID] = []
    stop_count: int = 0

