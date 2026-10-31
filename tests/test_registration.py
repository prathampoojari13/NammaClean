"""
Tests for NammaClean Stage 2.4.1: Registration schemas and service foundation.
Verifies Pydantic registration input validation, email normalization, password constraints,
rejection of client-controlled privileged fields, and register_citizen service behavior.
"""

import uuid
import pytest
from pydantic import ValidationError, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import verify_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User
from app.schemas.user import UserRegisterRequest, UserResponse
from app.services.user_service import register_citizen, DuplicateEmailError


# --- Schema Validation Tests ---

def test_registration_schema_valid_input():
    """Verify that valid email and password produce a validated schema."""
    req = UserRegisterRequest(
        email="citizen@example.com",
        password="SecurePassword123!",
    )
    assert req.email == "citizen@example.com"
    assert isinstance(req.password, SecretStr)
    assert req.password.get_secret_value() == "SecurePassword123!"
    # Verify password is not exposed in repr or str
    assert "SecurePassword123!" not in repr(req)
    assert "SecurePassword123!" not in str(req)


def test_registration_schema_email_normalization():
    """Verify that email addresses are trimmed and lowercased automatically."""
    req = UserRegisterRequest(
        email="  Citizen.Bangalore+Tag@EXAMPLE.COM  ",
        password="SecurePassword123!",
    )
    assert req.email == "citizen.bangalore+tag@example.com"


@pytest.mark.parametrize("invalid_email", [
    "",
    "   ",
    "plainaddress",
    "@missingusername.com",
    "username@.com",
    "username@domain",
    "user name@domain.com",
])
def test_registration_schema_invalid_and_empty_emails(invalid_email: str):
    """Verify that empty, blank, or malformed email addresses are rejected."""
    with pytest.raises(ValidationError):
        UserRegisterRequest(email=invalid_email, password="SecurePassword123!")


def test_registration_schema_password_length_validation():
    """Verify that password length rules (12 to 128 characters) are strictly enforced."""
    valid_email = "citizen@example.com"

    # Too short: 11 characters
    with pytest.raises(ValidationError, match="at least 12 characters"):
        UserRegisterRequest(email=valid_email, password="ShortPass1!")

    # Boundary valid: exactly 12 characters
    req_12 = UserRegisterRequest(email=valid_email, password="A1234567890!")
    assert len(req_12.password.get_secret_value()) == 12

    # Boundary valid: exactly 128 characters
    long_128 = "A" * 127 + "!"
    req_128 = UserRegisterRequest(email=valid_email, password=long_128)
    assert len(req_128.password.get_secret_value()) == 128

    # Too long: 129 characters
    too_long = "A" * 128 + "!"
    with pytest.raises(ValidationError, match="not exceed 128 characters"):
        UserRegisterRequest(email=valid_email, password=too_long)


@pytest.mark.parametrize("privileged_field,value", [
    ("role", "MUNICIPAL_ADMIN"),
    ("status", "ACTIVE"),
    ("password_hash", "$argon2id$somehash"),
    ("id", str(uuid.uuid4())),
    ("is_admin", True),
    ("is_superuser", True),
])
def test_registration_schema_rejects_privileged_fields(privileged_field: str, value):
    """Verify that client requests attempting to supply privileged fields are forbidden."""
    payload = {
        "email": "citizen@example.com",
        "password": "SecurePassword123!",
        privileged_field: value,
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UserRegisterRequest(**payload)


# --- Registration Service Tests ---

@pytest.mark.asyncio
async def test_register_citizen_success_and_safeguards(async_db_session: AsyncSession):
    """
    Verify successful citizen registration with:
    - UUID identifier
    - Normalized email
    - Argon2id password hashing (no plaintext storage)
    - Server-assigned CITIZEN role
    - ACTIVE initial account status
    - Transaction isolation without premature commit
    """
    unique_email = f"citizen_{uuid.uuid4().hex[:8]}@example.com"
    plain_password = "SecurePassword123!"

    req = UserRegisterRequest(
        email=unique_email.upper(),
        password=plain_password,
    )

    user = await register_citizen(async_db_session, req)

    # 1. Identity & Email
    assert isinstance(user.id, uuid.UUID)
    assert user.email == unique_email.lower()

    # 2. Password Hashing Safeguard
    assert user.password_hash.startswith("$argon2id$")
    assert user.password_hash != plain_password
    assert verify_password(plain_password, user.password_hash) is True
    assert verify_password("WrongPassword123!", user.password_hash) is False

    # 3. Role & Status Safeguards
    assert user.role == UserRole.CITIZEN.value
    assert user.status == UserStatus.ACTIVE.value

    # 4. UserResponse projection
    resp = UserResponse.model_validate(user)
    assert resp.id == user.id
    assert resp.email == user.email
    assert resp.role == UserRole.CITIZEN.value
    assert not hasattr(resp, "password_hash")


@pytest.mark.asyncio
async def test_register_citizen_duplicate_email_rejected(async_db_session: AsyncSession):
    """Verify that duplicate registration attempts raise DuplicateEmailError without leaking internals."""
    shared_email = f"duplicate_{uuid.uuid4().hex[:8]}@example.com"

    req1 = UserRegisterRequest(email=shared_email, password="SecurePassword123!")
    await register_citizen(async_db_session, req1)

    # Attempt second registration with same email in different case
    req2 = UserRegisterRequest(email=shared_email.upper(), password="AnotherSecurePassword123!")
    with pytest.raises(DuplicateEmailError, match="already exists"):
        await register_citizen(async_db_session, req2)


@pytest.mark.asyncio
async def test_register_citizen_concurrent_duplicate_handling_via_savepoint(async_db_session: AsyncSession):
    """
    Verify that concurrent race-condition duplicate inserts caught by the DB unique constraint
    are gracefully translated to DuplicateEmailError without corrupting the session transaction.
    """
    unique_email = f"race_{uuid.uuid4().hex[:8]}@example.com"

    # Pre-insert a user directly into the database to simulate another thread's concurrent commit
    direct_user = User(
        email=unique_email,
        password_hash="$argon2id$mockhash",
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(direct_user)
    await async_db_session.flush()

    # Attempt to register with the same email
    req = UserRegisterRequest(email=unique_email, password="SecurePassword123!")
    with pytest.raises(DuplicateEmailError, match="already exists"):
        await register_citizen(async_db_session, req)

    # Confirm the session is NOT poisoned and can still execute queries
    stmt = select(User).where(User.email == unique_email)
    res = await async_db_session.execute(stmt)
    assert res.scalars().first() is not None


@pytest.mark.asyncio
async def test_register_citizen_transaction_ownership(async_db_session: AsyncSession):
    """
    Verify transaction ownership convention:
    - register_citizen never commits the caller's transaction.
    - An outer rollback cleanly removes the newly registered user.
    """
    isolated_email = f"trans_{uuid.uuid4().hex[:8]}@example.com"
    req = UserRegisterRequest(email=isolated_email, password="SecurePassword123!")

    user = await register_citizen(async_db_session, req)
    assert user.id is not None

    # Roll back the session to prove the service did not commit
    await async_db_session.rollback()

    # The user should not exist in the database after rollback
    stmt = select(User).where(User.email == isolated_email)
    res = await async_db_session.execute(stmt)
    assert res.scalars().first() is None


@pytest.mark.asyncio
async def test_register_citizen_does_not_commit_unrelated_staged_work(async_db_session: AsyncSession):
    """
    Verify that register_citizen never commits unrelated changes staged in the session:
    - Stage an unrelated entity in the session.
    - Call register_citizen.
    - An outer rollback cleanly discards both the new user and the unrelated staged work.
    """
    from app.models.ward import Ward

    unrelated_ward_code = f"W-{uuid.uuid4().hex[:6].upper()}"
    unrelated_ward = Ward(
        ward_code=unrelated_ward_code,
        display_name="Temporary Uncommitted Ward",
    )
    async_db_session.add(unrelated_ward)

    # Register citizen on the same session
    req = UserRegisterRequest(
        email=f"staged_check_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
    )
    user = await register_citizen(async_db_session, req)
    assert user.id is not None

    # Outer caller issues rollback
    await async_db_session.rollback()

    # Verify neither the user nor the unrelated ward was committed
    ward_res = await async_db_session.execute(
        select(Ward).where(Ward.ward_code == unrelated_ward_code)
    )
    assert ward_res.scalars().first() is None

    user_res = await async_db_session.execute(
        select(User).where(User.email == req.email)
    )
    assert user_res.scalars().first() is None

