"""
Authentication and registration endpoints for NammaClean API v1.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.database import get_db
from app.core.security import verify_password, create_access_token, hash_password
from app.models.enums import UserStatus
from app.models.user import User, normalize_email
from app.schemas.user import UserRegisterRequest, UserResponse
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.user_service import register_citizen, DuplicateEmailError

from app.core.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Constant dummy hash used to equalize execution timing and prevent user-enumeration attacks
_DUMMY_ARGON2_HASH = hash_password("dummy_password_for_timing_mitigation_constant_time")

# Rate limiters: 10 login attempts and 5 registration attempts per 60 seconds per client IP
login_rate_limiter = RateLimiter(max_requests=10, window_seconds=60, key_prefix="auth_login")
register_rate_limiter = RateLimiter(max_requests=5, window_seconds=60, key_prefix="auth_register")


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Citizen Account Registration",
    description="Registers a new citizen account with email and password.",
    dependencies=[Depends(register_rate_limiter)],
)
async def register_citizen_endpoint(
    payload: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Registers a new citizen user.

    Transaction Ownership:
    The API layer owns the transaction boundary for this request:
    - Commits the transaction upon successful registration.
    - Rolls back the transaction on duplicate conflict or unexpected errors.
    - Maps DuplicateEmailError to HTTP 409 Conflict with sanitized messaging.
    - Sanitizes internal exceptions to ensure no SQL queries or credentials are leaked.
    """
    try:
        user = await register_citizen(db, payload)
        await db.commit()
        await db.refresh(user)
        return UserResponse.model_validate(user)
    except DuplicateEmailError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error during citizen registration: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during registration. Please try again.",
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="User Authentication & Token Issuance",
    description="Authenticates active users and issues a signed HS256 JWT access token.",
    dependencies=[Depends(login_rate_limiter)],
)
async def login_endpoint(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Authenticates a user via email and password credentials.

    Security & Business Rules:
    - Normalizes the email address before database lookup.
    - Constant-time verification prevents user-enumeration timing discrepancies.
    - Restricts login strictly to accounts with status == ACTIVE.
    - Rejects disabled or pending-verification accounts with generic 401 Unauthorized.
    - Issues a signed HS256 JWT access token with standard claims (sub, iat, exp, jti).
    - Read-only database operation: does not commit unrelated transaction changes.
    - Sanitizes internal exceptions to avoid leaking database internals.
    """
    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
    )

    try:
        normalized_email = normalize_email(payload.email)
        plain_password = payload.password.get_secret_value()

        stmt = select(User).where(User.email == normalized_email)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if user is None:
            # Equalize execution timing against enumeration by performing a dummy hash verification
            verify_password(plain_password, _DUMMY_ARGON2_HASH)
            raise generic_error

        if not verify_password(plain_password, user.password_hash):
            raise generic_error

        # Permit login strictly for ACTIVE accounts
        if user.status != UserStatus.ACTIVE.value:
            raise generic_error

        # Issue signed HS256 access token with user UUID as subject
        token = create_access_token(
            subject=user.id,
            extra_claims={"role": user.role},
        )
        return TokenResponse(access_token=token, token_type="bearer")

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error during login: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during login. Please try again.",
        )

