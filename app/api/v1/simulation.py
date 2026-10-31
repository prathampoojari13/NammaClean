"""
Endpoints for controlled GPS Simulation Engine.
Restricted exclusively to Municipal Administrators.
Disabled by default unless SIMULATION_ENABLED is explicitly set to True.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import settings
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.simulation import (
    SimulationTickRequest,
    SimulationTickResponse,
    SeedDemoFleetRequest,
    SeedDemoFleetResponse,
)
from app.services.simulation_service import (
    step_simulation,
    seed_demo_fleet,
    SimulationDisabledError,
    NonDemoAssetError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulation", tags=["Simulation Engine"])


@router.post(
    "/tick",
    response_model=SimulationTickResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger Simulation Tick",
    description="Advances simulated vehicles along demo routes by a deterministic time step. Restricted to Municipal Admins.",
)
async def trigger_simulation_tick(
    payload: SimulationTickRequest,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SimulationTickResponse:
    """
    Triggers a simulation step for demo vehicles.
    Requires SIMULATION_ENABLED=True in configuration; otherwise returns HTTP 400.
    Simulates only vehicles designated as demo records (is_simulated == True).
    """
    if not settings.SIMULATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GPS simulation engine is disabled by configuration.",
        )

    try:
        return await step_simulation(
            db=db,
            vehicle_id=payload.vehicle_id,
            step_seconds=payload.step_seconds,
        )
    except SimulationDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except NonDemoAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        await db.rollback()
        logger.error("Simulation tick failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while executing simulation tick.",
        )


@router.post(
    "/seed-demo",
    response_model=SeedDemoFleetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seed Demo Fleet in Ward",
    description="Initializes demo vehicle and route records in the target ward. Restricted to Municipal Admins.",
)
async def seed_demo_fleet_endpoint(
    payload: SeedDemoFleetRequest,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SeedDemoFleetResponse:
    """
    Seeds a demo vehicle and demo route in a ward for simulation testing.
    All created assets are explicitly flagged as is_simulated=True and approved for display.
    """
    if not settings.SIMULATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GPS simulation engine is disabled by configuration.",
        )

    try:
        return await seed_demo_fleet(db=db, ward_id=payload.ward_id)
    except SimulationDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to seed demo fleet: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while seeding demo fleet.",
        )
