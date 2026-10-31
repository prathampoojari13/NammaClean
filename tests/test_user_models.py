import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole, UserStatus
from app.models.user import User, normalize_email
from app.models.ward import Ward, UserWardAssignment
from app.core.security import hash_password


# --- 1. Email Normalization Tests ---

def test_normalize_email_trims_and_lowercases():
    """Verify that email normalization trims whitespace and applies case normalization."""
    assert normalize_email("  TestUser@Bengaluru.Gov.IN  ") == "testuser@bengaluru.gov.in"
    assert normalize_email("citizen.one@domain.com") == "citizen.one@domain.com"
    assert normalize_email("\tDRIVER.123@Example.Com\n") == "driver.123@example.com"


def test_normalize_email_rejects_empty():
    """Verify that empty or whitespace-only emails raise ValueError."""
    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_email("")
    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_email("   ")
    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_email(None)


def test_user_constructor_normalizes_email():
    """Verify that instantiating User model automatically normalizes email."""
    user = User(
        email="   POURAKARMIKA@BBMP.ORG   ",
        password_hash=hash_password("SafePass123"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
    )
    assert user.email == "pourakarmika@bbmp.org"


# --- 2. Database Integration Tests: User Model ---

@pytest.mark.asyncio
async def test_create_user_with_uuid_and_timestamps(async_db_session: AsyncSession):
    """Verify that a user is created with a generated UUID and timezone-aware timestamps."""
    unique_email = f"citizen_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=unique_email,
        password_hash=hash_password("CitizenSecretPass!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user)
    await async_db_session.commit()
    await async_db_session.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.email == unique_email
    assert user.password_hash.startswith("$argon2id$")
    assert user.role == UserRole.CITIZEN.value
    assert user.status == UserStatus.ACTIVE.value
    assert isinstance(user.created_at, datetime)
    assert isinstance(user.updated_at, datetime)
    assert user.created_at.tzinfo is not None

    # Cleanup
    await async_db_session.delete(user)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_email_uniqueness_enforced_by_database(async_db_session: AsyncSession):
    """Verify that duplicate normalized emails are rejected by the database unique constraint."""
    shared_email = f"duplicate_{uuid.uuid4().hex[:8]}@example.com"
    user1 = User(
        email=shared_email,
        password_hash=hash_password("Pass1"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user1)
    await async_db_session.commit()

    user2 = User(
        email=shared_email.upper(),  # Same normalized email in different case
        password_hash=hash_password("Pass2"),
        role=UserRole.DRIVER.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(user2)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # Cleanup user1
    await async_db_session.delete(user1)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_valid_roles_accepted_and_invalid_rejected(async_db_session: AsyncSession):
    """Verify that all 5 valid roles are accepted and unapproved roles are rejected by check constraint."""
    valid_roles = [
        UserRole.CITIZEN.value,
        UserRole.SANITATION_WORKER.value,
        UserRole.DRIVER.value,
        UserRole.WARD_SUPERVISOR.value,
        UserRole.MUNICIPAL_ADMIN.value,
    ]
    created_users = []
    for r in valid_roles:
        u = User(
            email=f"user_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("ValidPassword"),
            role=r,
            status=UserStatus.ACTIVE.value,
        )
        async_db_session.add(u)
        created_users.append(u)
    await async_db_session.commit()

    # Invalid role must fail the database check constraint
    invalid_user = User(
        email=f"invalid_role_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword"),
        role="SUPERUSER",  # Unconstrained / unapproved role
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add(invalid_user)
    with pytest.raises((IntegrityError, DBAPIError)):
        await async_db_session.commit()
    await async_db_session.rollback()

    # Cleanup created users
    for u in created_users:
        await async_db_session.delete(u)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_valid_statuses_accepted_and_invalid_rejected(async_db_session: AsyncSession):
    """Verify that all 3 valid statuses are accepted and unapproved statuses are rejected by check constraint."""
    valid_statuses = [
        UserStatus.ACTIVE.value,
        UserStatus.DISABLED.value,
        UserStatus.PENDING_VERIFICATION.value,
    ]
    created_users = []
    for s in valid_statuses:
        u = User(
            email=f"status_user_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("ValidPassword"),
            role=UserRole.CITIZEN.value,
            status=s,
        )
        async_db_session.add(u)
        created_users.append(u)
    await async_db_session.commit()

    # Invalid status must fail database check constraint
    invalid_status_user = User(
        email=f"invalid_status_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword"),
        role=UserRole.CITIZEN.value,
        status="ARCHIVED",  # Unapproved status
    )
    async_db_session.add(invalid_status_user)
    with pytest.raises((IntegrityError, DBAPIError)):
        await async_db_session.commit()
    await async_db_session.rollback()

    # Cleanup
    for u in created_users:
        await async_db_session.delete(u)
    await async_db_session.commit()


# --- 3. Database Integration Tests: Ward & Assignments ---

@pytest.mark.asyncio
async def test_ward_creation_and_code_uniqueness(async_db_session: AsyncSession):
    """Verify ward creation and enforcement of unique ward_code constraint."""
    unique_code = f"TEST_WARD_{uuid.uuid4().hex[:6]}"
    ward1 = Ward(
        ward_code=unique_code,
        display_name="Test Municipal Ward",
    )
    async_db_session.add(ward1)
    await async_db_session.commit()
    await async_db_session.refresh(ward1)

    assert isinstance(ward1.id, uuid.UUID)
    assert ward1.ward_code == unique_code
    assert ward1.display_name == "Test Municipal Ward"

    # Duplicate ward code
    ward2 = Ward(
        ward_code=unique_code,
        display_name="Duplicate Ward Code",
    )
    async_db_session.add(ward2)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # Cleanup
    await async_db_session.delete(ward1)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_user_ward_assignment_foreign_key_integrity(async_db_session: AsyncSession):
    """Verify that ward assignment requires valid existing user and ward records."""
    non_existent_id = uuid.uuid4()
    invalid_assignment = UserWardAssignment(
        user_id=non_existent_id,
        ward_id=non_existent_id,
    )
    async_db_session.add(invalid_assignment)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()


@pytest.mark.asyncio
async def test_duplicate_active_assignment_prevention(async_db_session: AsyncSession):
    """
    Verify that a user cannot have duplicate ACTIVE assignments (revoked_at is NULL)
    to the same ward.
    """
    user = User(
        email=f"worker_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(
        ward_code=f"W_{uuid.uuid4().hex[:6]}",
        display_name="Assigned Test Ward",
    )
    async_db_session.add_all([user, ward])
    await async_db_session.commit()

    # First active assignment
    assignment1 = UserWardAssignment(user_id=user.id, ward_id=ward.id)
    async_db_session.add(assignment1)
    await async_db_session.commit()

    # Attempt second active assignment to the same ward
    assignment2 = UserWardAssignment(user_id=user.id, ward_id=ward.id)
    async_db_session.add(assignment2)
    with pytest.raises(IntegrityError):
        await async_db_session.commit()
    await async_db_session.rollback()

    # Cleanup
    await async_db_session.delete(assignment1)
    await async_db_session.delete(user)
    await async_db_session.delete(ward)
    await async_db_session.commit()


@pytest.mark.asyncio
async def test_historical_assignment_allows_subsequent_reassignment(async_db_session: AsyncSession):
    """
    Verify that revoking an assignment (setting revoked_at) preserves the historical
    record and allows a new active assignment to be made to the same ward later.
    """
    user = User(
        email=f"supervisor_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass123"),
        role=UserRole.WARD_SUPERVISOR.value,
        status=UserStatus.ACTIVE.value,
    )
    ward = Ward(
        ward_code=f"W_{uuid.uuid4().hex[:6]}",
        display_name="Supervisor Test Ward",
    )
    async_db_session.add_all([user, ward])
    await async_db_session.commit()

    # 1. First assignment: active initially, then revoked
    past_assignment = UserWardAssignment(user_id=user.id, ward_id=ward.id)
    async_db_session.add(past_assignment)
    await async_db_session.commit()

    # Revoke assignment (marks it as historical)
    past_assignment.revoked_at = datetime.now(timezone.utc)
    await async_db_session.commit()

    # 2. Subsequent new active assignment to the same ward must succeed
    new_assignment = UserWardAssignment(user_id=user.id, ward_id=ward.id)
    async_db_session.add(new_assignment)
    await async_db_session.commit()
    await async_db_session.refresh(new_assignment)

    assert new_assignment.revoked_at is None
    assert past_assignment.revoked_at is not None

    # Query all assignments for this user
    result = await async_db_session.execute(
        select(UserWardAssignment).where(UserWardAssignment.user_id == user.id)
    )
    all_assignments = result.scalars().all()
    assert len(all_assignments) == 2

    # Cleanup
    await async_db_session.delete(new_assignment)
    await async_db_session.delete(past_assignment)
    await async_db_session.delete(user)
    await async_db_session.delete(ward)
    await async_db_session.commit()
