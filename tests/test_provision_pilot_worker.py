"""
Comprehensive unit and integration tests for the administrative pilot worker provisioning tool.
Tests:
1. Complete creation of Ward 4, Muster Point, Worker, Ward Assignment, and Schedule.
2. Idempotency: Second run reuses all existing records without duplicates.
3. Password policy enforcement (minimum 12 characters, max 128) and Argon2id hash verification.
4. Role conflict protection: Refuses to overwrite an existing account with non-worker role (e.g. CITIZEN).
5. Official ID conflict protection: Refuses to assign an employee ID already taken by another user.
6. Transaction rollback: Session rollback leaves no partial records.
7. Production URL safety check: Rejects non-local database targets without --confirm-production.
"""

import uuid
import pytest
from datetime import date
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.security import verify_password, hash_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint
from app.models.schedule import WorkerSchedule
from app.services.schedule_service import get_resolved_worker_schedule, validate_check_in_window
from scripts.provision_pilot_worker import (
    provision_pilot_worker,
    validate_password_policy,
    is_production_database_url,
    ProvisioningError,
    PILOT_WARD_CODE,
    PILOT_MUSTER_NAME,
    PILOT_WORKER_EMAIL,
    PILOT_WORKER_OFFICIAL_ID,
)


def test_password_policy_validation():
    """Verify password policy rejects short/long passwords and accepts valid passwords."""
    with pytest.raises(ValueError, match="at least 12 characters"):
        validate_password_policy("pratik123")  # 9 chars

    with pytest.raises(ValueError, match="at least 12 characters"):
        validate_password_policy("")

    with pytest.raises(ValueError, match="exceed 128 characters"):
        validate_password_policy("a" * 129)

    # Valid password
    validate_password_policy("CleanBangalore@2026!")


def test_production_database_url_detector():
    """Verify is_production_database_url distinguishes local vs remote targets."""
    assert is_production_database_url("postgresql+psycopg2://admin:pass@localhost:5433/nammaclean_test_db") is False
    assert is_production_database_url("postgresql+psycopg2://admin:pass@127.0.0.1:5433/nammaclean_test_db") is False
    assert is_production_database_url("postgresql://user:pass@dpg-dc3dofgm7kps73e003k0-a.singapore-postgres.render.com/nammaclean") is True
    assert is_production_database_url("postgres://user:pass@ep-cool-fog-123456.us-east-1.aws.neon.tech/nammaclean") is True


@pytest.mark.asyncio
async def test_provision_pilot_worker_full_pipeline_and_idempotency(
    async_db_session: AsyncSession,
):
    """
    Verifies that provision_pilot_worker:
    1. Creates all 5 records cleanly in run 1.
    2. Reuses all 5 records cleanly in run 2 (idempotency).
    3. Produces a schedule whose check-in window is open for roll-call attendance.
    """
    test_password = "SecureWorkerPassword@2026!"

    # Clean up any pre-existing pilot artifacts from test database to test from zero
    res_u = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    existing_user = res_u.scalars().first()
    if existing_user:
        await async_db_session.execute(delete(WorkerSchedule).where(WorkerSchedule.worker_id == existing_user.id))
        await async_db_session.execute(delete(UserWardAssignment).where(UserWardAssignment.user_id == existing_user.id))
        await async_db_session.delete(existing_user)
        await async_db_session.flush()

    res_w = await async_db_session.execute(select(Ward).where(Ward.ward_code == PILOT_WARD_CODE))
    existing_ward = res_w.scalars().first()
    if existing_ward:
        await async_db_session.execute(delete(MusterPoint).where(MusterPoint.ward_id == existing_ward.id))
        await async_db_session.delete(existing_ward)
        await async_db_session.flush()

    # --- RUN 1: Fresh Creation ---
    summary_1 = await async_db_session.run_sync(
        lambda sync_s: provision_pilot_worker(sync_s, worker_password=test_password)
    )

    assert summary_1["ward"]["action"] == "CREATED"
    assert summary_1["muster_point"]["action"] == "CREATED"
    assert summary_1["worker"]["action"] == "CREATED"
    assert summary_1["ward_assignment"]["action"] == "CREATED"
    assert summary_1["schedule"]["action"] == "CREATED"

    # Verify database state
    res_worker = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    worker = res_worker.scalars().first()
    assert worker is not None
    assert worker.role == UserRole.SANITATION_WORKER.value
    assert worker.status == UserStatus.ACTIVE.value
    assert worker.official_id == PILOT_WORKER_OFFICIAL_ID
    assert verify_password(test_password, worker.password_hash) is True

    res_ward2 = await async_db_session.execute(select(Ward).where(Ward.ward_code == PILOT_WARD_CODE))
    ward = res_ward2.scalars().first()
    assert ward is not None
    assert worker.ward_id == ward.id

    res_mp = await async_db_session.execute(select(MusterPoint).where(MusterPoint.ward_id == ward.id))
    mp = res_mp.scalars().first()
    assert mp is not None
    assert mp.name == PILOT_MUSTER_NAME
    assert mp.geofence_radius_meters == 150
    assert mp.is_active is True

    res_assign = await async_db_session.execute(
        select(UserWardAssignment).where(
            UserWardAssignment.user_id == worker.id,
            UserWardAssignment.ward_id == ward.id,
            UserWardAssignment.revoked_at.is_(None),
        )
    )
    assign = res_assign.scalars().first()
    assert assign is not None

    res_sched = await async_db_session.execute(
        select(WorkerSchedule).where(WorkerSchedule.worker_id == worker.id)
    )
    sched = res_sched.scalars().first()
    assert sched is not None
    assert sched.is_active is True
    assert set(sched.days_of_week) == {1, 2, 3, 4, 5, 6, 7}

    # Verify check-in window is open for testing
    resolved = await get_resolved_worker_schedule(async_db_session, worker.id, date.today())
    assert resolved.is_scheduled_workday is True
    can_proceed, flag, msg = validate_check_in_window(resolved)
    assert can_proceed is True

    # --- RUN 2: Idempotent Execution ---
    summary_2 = await async_db_session.run_sync(
        lambda sync_s: provision_pilot_worker(sync_s, worker_password=None)
    )

    assert summary_2["ward"]["action"] == "REUSED"
    assert summary_2["muster_point"]["action"] == "REUSED"
    assert summary_2["worker"]["action"] == "REUSED"
    assert summary_2["ward_assignment"]["action"] == "REUSED"
    assert summary_2["schedule"]["action"] == "REUSED"

    # Confirm IDs match across runs
    assert summary_1["ward"]["id"] == summary_2["ward"]["id"]
    assert summary_1["worker"]["id"] == summary_2["worker"]["id"]


@pytest.mark.asyncio
async def test_provision_refuses_conflicting_role_overwrite(
    async_db_session: AsyncSession,
):
    """Verify that if an account exists with a conflicting role (e.g. CITIZEN), it will not be overwritten."""
    # Setup an existing citizen with the same email
    res_ex = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    existing = res_ex.scalars().first()
    if existing:
        await async_db_session.delete(existing)
        await async_db_session.flush()

    citizen = User(
        email=PILOT_WORKER_EMAIL,
        password_hash=hash_password("CitizenPassword@2026!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
        full_name="Citizen Pratik",
    )
    async_db_session.add(citizen)
    await async_db_session.flush()

    with pytest.raises(ProvisioningError, match="Refusing to overwrite existing user identity"):
        await async_db_session.run_sync(
            lambda sync_s: provision_pilot_worker(sync_s, worker_password="NewPassword@2026!")
        )

    # Verify original citizen role was preserved
    res_unchanged = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    unchanged = res_unchanged.scalars().first()
    assert unchanged.role == UserRole.CITIZEN.value


@pytest.mark.asyncio
async def test_provision_refuses_conflicting_official_id(
    async_db_session: AsyncSession,
):
    """Verify that if official ID BBMP-WRK-042 is already assigned to another user, provisioning aborts."""
    # Clean up target email if exists
    res_t = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    target = res_t.scalars().first()
    if target:
        await async_db_session.delete(target)
        await async_db_session.flush()

    # Create another worker holding BBMP-WRK-042
    other_worker = User(
        email=f"other_worker_{uuid.uuid4().hex[:6]}@test.local",
        password_hash=hash_password("OtherPassword@2026!"),
        role=UserRole.SANITATION_WORKER.value,
        status=UserStatus.ACTIVE.value,
        official_id=PILOT_WORKER_OFFICIAL_ID,
    )
    async_db_session.add(other_worker)
    await async_db_session.flush()

    with pytest.raises(ProvisioningError, match="already registered to another account"):
        await async_db_session.run_sync(
            lambda sync_s: provision_pilot_worker(sync_s, worker_password="NewPassword@2026!")
        )


@pytest.mark.asyncio
async def test_provision_dry_run_does_not_persist(
    async_db_session: AsyncSession,
):
    """Verify that running with dry_run=True performs rollback and creates zero persistent rows."""
    # Clean up target email and ward
    res_u = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    existing_u = res_u.scalars().first()
    if existing_u:
        await async_db_session.delete(existing_u)
        await async_db_session.flush()

    res_w = await async_db_session.execute(select(Ward).where(Ward.ward_code == PILOT_WARD_CODE))
    existing_w = res_w.scalars().first()
    if existing_w:
        await async_db_session.delete(existing_w)
        await async_db_session.flush()

    # Execute dry run
    summary = await async_db_session.run_sync(
        lambda sync_s: provision_pilot_worker(
            sync_s,
            worker_password="ValidTestPassword@2026!",
            dry_run=True,
        )
    )
    assert summary["worker"]["action"] == "CREATED"

    # Verify database has no persisted records
    res_u2 = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    assert res_u2.scalars().first() is None

    res_w2 = await async_db_session.execute(select(Ward).where(Ward.ward_code == PILOT_WARD_CODE))
    assert res_w2.scalars().first() is None


@pytest.mark.asyncio
async def test_provision_existing_worker_password_preserved_unless_flag(
    async_db_session: AsyncSession,
):
    """
    Verify that an existing worker's password is never overwritten unless
    update_password=True is explicitly supplied.
    """
    initial_password = "OriginalWorkerPassword@2026!"
    new_attempted_password = "NewAttemptedPassword@2026!"

    # Clean up target email
    res_u = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    existing_u = res_u.scalars().first()
    if existing_u:
        await async_db_session.execute(delete(WorkerSchedule).where(WorkerSchedule.worker_id == existing_u.id))
        await async_db_session.execute(delete(UserWardAssignment).where(UserWardAssignment.user_id == existing_u.id))
        await async_db_session.delete(existing_u)
        await async_db_session.flush()

    # Step 1: Initial provision
    summary_1 = await async_db_session.run_sync(
        lambda sync_s: provision_pilot_worker(
            sync_s,
            worker_password=initial_password,
        )
    )
    assert summary_1["worker"]["action"] == "CREATED"

    # Step 2: Run again with different password but update_password=False
    summary_2 = await async_db_session.run_sync(
        lambda sync_s: provision_pilot_worker(
            sync_s,
            worker_password=new_attempted_password,
            update_password=False,
        )
    )
    assert summary_2["worker"]["action"] == "REUSED"

    # Verify password was NOT changed
    res_worker = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    worker = res_worker.scalars().first()
    assert verify_password(initial_password, worker.password_hash) is True
    assert verify_password(new_attempted_password, worker.password_hash) is False

    # Step 3: Run again with update_password=True
    summary_3 = await async_db_session.run_sync(
        lambda sync_s: provision_pilot_worker(
            sync_s,
            worker_password=new_attempted_password,
            update_password=True,
        )
    )
    assert summary_3["worker"]["action"] == "UPDATED"

    # Verify password HAS now been updated
    await async_db_session.refresh(worker)
    assert verify_password(new_attempted_password, worker.password_hash) is True
    assert verify_password(initial_password, worker.password_hash) is False


@pytest.mark.asyncio
async def test_provision_canonical_morning_schedule_mode(
    async_db_session: AsyncSession,
):
    """Verify that schedule_mode='canonical-morning' provisions 07:00-14:00 Mon-Sat schedule."""
    # Clean up worker and schedule
    res_u = await async_db_session.execute(select(User).where(User.email == PILOT_WORKER_EMAIL))
    existing_u = res_u.scalars().first()
    if existing_u:
        await async_db_session.execute(delete(WorkerSchedule).where(WorkerSchedule.worker_id == existing_u.id))
        await async_db_session.execute(delete(UserWardAssignment).where(UserWardAssignment.user_id == existing_u.id))
        await async_db_session.delete(existing_u)
        await async_db_session.flush()

    summary = await async_db_session.run_sync(
        lambda sync_s: provision_pilot_worker(
            sync_s,
            worker_password="TestSchedulePass@2026!",
            schedule_mode="canonical-morning",
        )
    )
    assert summary["schedule"]["action"] == "CREATED"

    res_sched = await async_db_session.execute(
        select(WorkerSchedule).where(WorkerSchedule.worker_id == uuid.UUID(summary["worker"]["id"]))
    )
    sched = res_sched.scalars().first()
    assert sched is not None
    assert sched.days_of_week == [1, 2, 3, 4, 5, 6]
    assert sched.shift_start_time == "07:00"
    assert sched.shift_end_time == "14:00"
    assert sched.check_in_start_time == "06:45"
    assert sched.check_in_end_time == "07:30"
