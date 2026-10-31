"""
User profile and account endpoints for NammaClean API v1.
"""

import logging
from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse

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
    - Returns only explicitly approved public fields: id, email, role, status, created_at, updated_at.
    - Never returns password_hash, password values, JWTs, or internal credentials.
    - Returns HTTP 401 Unauthorized for missing, expired, or invalid credentials.
    - Rejects disabled or pending-verification accounts via get_current_user().
    - Never trusts client-supplied query/body parameters to determine user identity.
    """
    return UserResponse.model_validate(current_user)
