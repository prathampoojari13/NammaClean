"""
Common FastAPI dependencies for authentication, authorization, and database access.
"""

import uuid
import logging
from typing import Optional, Callable, Union
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import PyJWTError, ExpiredSignatureError, InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.enums import UserRole, UserStatus
from app.models.user import User

logger = logging.getLogger(__name__)

# Bearer token extractor using standard Authorization header
# auto_error=False allows returning custom 401 Unauthorized with WWW-Authenticate header
http_bearer = HTTPBearer(auto_error=False)


def _get_auth_exception() -> HTTPException:
    """Returns a standardized HTTP 401 Unauthorized exception with WWW-Authenticate header."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Authenticates a user via Bearer JWT token from the Authorization header.

    Workflow:
    1. Extracts Bearer token credentials.
    2. Decodes and verifies token signature, HS256 algorithm, expiry, and required claims.
    3. Resolves the user identity by UUID from the authoritative database record.
    4. Enforces that account status is strictly ACTIVE.
    5. Rejects missing, expired, malformed, non-existent, disabled, or pending accounts
       with a safe, generic HTTP 401 Unauthorized response.

    Returns the authenticated User entity.
    """
    auth_exception = _get_auth_exception()

    if credentials is None or not credentials.credentials:
        raise auth_exception

    if credentials.scheme.lower() != "bearer":
        raise auth_exception

    try:
        payload = decode_access_token(credentials.credentials)
        sub = payload.get("sub")
        if not sub:
            raise auth_exception
        user_id = uuid.UUID(str(sub))
    except (InvalidTokenError, ExpiredSignatureError, PyJWTError, ValueError):
        raise auth_exception

    try:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if user is None:
            raise auth_exception

        if user.status != UserStatus.ACTIVE.value:
            raise auth_exception

        return user
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unexpected error during user authentication: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during authentication.",
        )


def require_roles(*allowed_roles: Union[UserRole, str]) -> Callable:
    """
    Dependency factory that restricts endpoint access to authenticated users possessing
    one of the specified allowed roles.

    Enforces:
    1. Authentication via `get_current_user` (returns 401 Unauthorized for unauthenticated/invalid requests).
    2. Role authorization against the authoritative database-backed `user.role` record.
    3. Rejection of authenticated users with unauthorized roles via HTTP 403 Forbidden.

    Returns the authenticated and authorized User entity upon success.
    """
    if not allowed_roles:
        raise ValueError("require_roles requires at least one allowed role.")

    # Normalize allowed roles to string representations
    role_values = {
        role.value if isinstance(role, UserRole) else str(role)
        for role in allowed_roles
    }

    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in role_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this resource.",
            )
        return current_user

    return role_checker


async def verify_ward_access(user: User, ward_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Verifies that the user has administrative or supervisory access to manage assets in the ward.
    - MUNICIPAL_ADMIN: Granted access across all wards.
    - WARD_SUPERVISOR: Strictly verified against active database record in user_ward_assignments (revoked_at IS NULL).
    - Other roles (CITIZEN, DRIVER, SANITATION_WORKER): Rejected with HTTP 403 Forbidden.
    """
    if user.role == UserRole.MUNICIPAL_ADMIN.value:
        return

    if user.role == UserRole.WARD_SUPERVISOR.value:
        from app.models.ward import UserWardAssignment
        stmt = (
            select(UserWardAssignment)
            .where(
                UserWardAssignment.user_id == user.id,
                UserWardAssignment.ward_id == ward_id,
                UserWardAssignment.revoked_at.is_(None),
            )
        )
        res = await db.execute(stmt)
        assignment = res.scalars().first()
        if assignment is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You are not assigned as supervisor for ward '{ward_id}'. Supervisor is not actively assigned to this ward.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions for this resource.",
    )

