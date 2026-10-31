"""
User and registration services for NammaClean.
Handles citizen registration and user persistence workflows.
"""

import uuid
from typing import Optional
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User, normalize_email
from app.schemas.user import UserRegisterRequest


class DuplicateEmailError(ValueError):
    """Raised when an attempt is made to register an account with an existing email."""
    pass


async def register_citizen(
    session: AsyncSession,
    registration_data: UserRegisterRequest,
) -> User:
    """
    Registers a new citizen user in the database.

    Transaction Ownership Convention:
    The service strictly adds the user entity and performs an atomic `session.flush()`
    within a nested savepoint (`session.begin_nested()`). This checks all database-level
    constraints (uniqueness, check constraints) immediately without prematurely committing
    or rolling back the caller's transaction. The service never calls `session.commit()`
    or `session.rollback()`; transaction boundaries are owned exclusively by the outer caller
    (e.g., FastAPI request handler or test fixture).

    Security & Business Rules:
    - Normalizes the email address using `normalize_email()`.
    - Hashes the password using Argon2id via `hash_password()`.
    - Server explicitly forces `role=UserRole.CITIZEN.value`.
    - Assigns `status=UserStatus.ACTIVE.value` as the initial account status.
    - Uses UUID v4 for the primary key.
    - Handles duplicate emails safely via pre-check and atomic database
      uniqueness constraint enforcement (handling race conditions safely).
    - Never logs passwords, credentials, or hashes.
    """
    normalized_email = normalize_email(registration_data.email)

    # 1. Pre-check for duplicate email before invoking password hashing
    stmt = select(User).where(User.email == normalized_email)
    result = await session.execute(stmt)
    if result.scalars().first() is not None:
        raise DuplicateEmailError("An account with this email address already exists.")

    # 2. Extract plaintext password securely and hash with Argon2id
    plain_password = (
        registration_data.password.get_secret_value()
        if isinstance(registration_data.password, SecretStr)
        else str(registration_data.password)
    )
    pwd_hash = hash_password(plain_password)

    # 3. Create user entity with server-enforced role and status
    new_user = User(
        id=uuid.uuid4(),
        email=normalized_email,
        password_hash=pwd_hash,
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )

    # 4. Atomic savepoint flush to catch race conditions without poisoning caller session
    try:
        async with session.begin_nested():
            session.add(new_user)
            await session.flush()
    except IntegrityError as exc:
        raise DuplicateEmailError("An account with this email address already exists.") from exc

    return new_user

