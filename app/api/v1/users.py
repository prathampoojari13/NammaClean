"""
User profile and account endpoints for NammaClean API v1.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User, utc_now
from app.models.ward import Ward
from app.schemas.user import UserResponse, UserProfileUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Current User Profile",
    description="Returns the authenticated user's database-backed profile information.",
)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Returns the profile information of the currently authenticated user.

    Security & Business Rules:
    - Authenticates the caller strictly via get_current_user() using a signed Bearer JWT.
    - Resolves identity and attributes from the authoritative database record.
    - Returns only explicitly approved public fields: id, email, role, status, ward_id, locality, address, created_at, updated_at.
    - Never returns password_hash, password values, JWTs, or internal credentials.
    - Returns HTTP 401 Unauthorized for missing, expired, or invalid credentials.
    - Rejects disabled or pending-verification accounts via get_current_user().
    - Never trusts client-supplied query/body parameters to determine user identity.
    """
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Current User Profile",
    description="Updates locality, address, or selected ward for the currently authenticated user.",
)
async def update_current_user_profile(
    payload: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Updates the authenticated caller's own profile (locality, address, selected ward).

    Security & Business Rules:
    - Authenticates caller strictly via get_current_user() using signed Bearer JWT.
    - Operates exclusively on current_user resolved from token subject; prevents editing another user's profile.
    - Privileged fields (role, status, email, password_hash, id) cannot be updated via extra='forbid'.
    - Validates that the selected ward exists if ward_id is provided (HTTP 404 if not found).
    - Supports setting ward_id to None if the user unassigns their ward.
    - Updates updated_at timestamp upon modification.
    """
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        return UserResponse.model_validate(current_user)

    if "ward_id" in update_data:
        # Operational personnel cannot alter their assigned ward
        if current_user.role in ("SANITATION_WORKER", "DRIVER", "WARD_SUPERVISOR"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operational personnel cannot modify their assigned administrative ward.",
            )
        ward_id = update_data["ward_id"]
        if ward_id is not None:
            stmt = select(Ward).where(Ward.id == ward_id)
            res = await db.execute(stmt)
            ward = res.scalars().first()
            if ward is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Ward with id '{ward_id}' not found.",
                )
            current_user.ward_id = ward_id
        else:
            current_user.ward_id = None

    if "locality" in update_data:
        current_user.locality = update_data["locality"]

    if "address" in update_data:
        current_user.address = update_data["address"]

    if "full_name" in update_data:
        current_user.full_name = update_data["full_name"]

    if "phone_number" in update_data:
        current_user.phone_number = update_data["phone_number"]

    current_user.updated_at = utc_now()

    await db.commit()
    await db.refresh(current_user)

    return UserResponse.model_validate(current_user)
