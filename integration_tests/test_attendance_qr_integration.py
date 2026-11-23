"""
PostgreSQL and PostGIS Integration Test Harness for Stage 2.10:
QR-Based Roll-Call Attendance for Pourakarmikas.

================================================================================
STRICT ISOLATION & FAIL-CLOSED TARGET POLICY:
1. Target: Dedicated disposable integration database 'nammaclean_qr_integration_db'
   on host port 5433 (PostGIS Docker container).
2. Forbidden Targets:
   - Port 5432 (MigrationGuard / host PostgreSQL) is strictly prohibited.
   - Database 'nammaclean_db' (development database) is strictly prohibited.
   - Database 'nammaclean_test_db' (existing regression database) is strictly prohibited.
3. Fail-Closed Engine Guard:
   - Fails immediately if host is not localhost/127.0.0.1.
   - Fails immediately if port is not 5433.
   - Fails immediately if database name is not 'nammaclean_qr_integration_db'.
   - Fails immediately if live catalog check does not match 'nammaclean_qr_integration_db'.
   - Fails immediately if migration revision is not 'b7e4d2c9f1a8'.
   - Fails immediately if PostGIS extension is not installed.
4. Concurrency Verification:
   - Uses two independent AsyncSession connections and separate PostgreSQL backends.
   - Verifies row-lock contention via pg_blocking_pids(pid_b) and pg_stat_activity.
5. Rollback Consistency:
   - Exercises actual redeem_qr_attendance service inside an outer transaction.
   - Verifies both attendance record and QR token changes roll back upon failure.
6. Daily Attendance Uniqueness:
   - Uses a deterministic synchronization barrier around validate_check_in_eligibility.
   - Proves database-enforced unique constraint uq_worker_daily_attendance arbitrates the race.
   - Confirms losing transaction translates IntegrityError into DuplicateAttendanceError.
   - Confirms losing token remains unredeemed and unlinked.
7. PostGIS Geometry & Geodesic Distance:
   - Verifies SRID 4326, geometry type, and axis order (X=lon, Y=lat).
   - Compares PostGIS ST_Distance against Python calculate_haversine_distance_meters.
   - Verifies service-level out-of-geofence check-in persists EXCEPTION_PENDING and valid POINT.
8. Schema & Referential Integrity:
   - Verifies check constraints, token_hash uniqueness, and CASCADE / SET NULL delete rules.
================================================================================
"""

import os
import uuid
import math
import secrets
import asyncio
from datetime import datetime, date, timezone, timedelta
from typing import AsyncGenerator, Dict, Any, List, Optional, Tuple

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import IntegrityError
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point

from app.services import attendance_service as att_service
from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord, AttendanceQrToken
from app.services.attendance_service import (
    hash_qr_token,
    generate_qr_token,
    redeem_qr_attendance,
    record_check_in,
    calculate_haversine_distance_meters,
    get_kolkata_workday_date,
    InvalidQrTokenError,
    ExpiredQrTokenError,
    QrTokenAlreadyRedeemedError,
    DuplicateAttendanceError,
    WorkerIneligibleError,
    WardAssignmentError,
    MusterPointError,
)


# ==============================================================================
# Section 1: Fail-Closed Target Connection Guard
# ==============================================================================

INTEGRATION_DB_HOST = "localhost"
INTEGRATION_DB_PORT = 5433
INTEGRATION_DB_NAME = "nammaclean_qr_integration_db"
EXPECTED_ALEMBIC_REVISION = "b7e4d2c9f1a8"

# Construct dedicated async connection URL from app settings credentials
INTEGRATION_ASYNC_DB_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{INTEGRATION_DB_HOST}:{INTEGRATION_DB_PORT}/{INTEGRATION_DB_NAME}"
)


def _assert_integration_target_isolation() -> None:
    """
    Fail-closed static assertion verifying that the test harness targets ONLY
    'nammaclean_qr_integration_db' on port 5433 and never accesses forbidden targets.
    """
    assert INTEGRATION_DB_HOST in ("localhost", "127.0.0.1"), (
        f"Guard Failure: Host must be localhost, found '{INTEGRATION_DB_HOST}'!"
    )
    assert INTEGRATION_DB_PORT == 5433, (
        f"Guard Failure: Port must be strictly 5433, found {INTEGRATION_DB_PORT}!"
    )
    assert INTEGRATION_DB_NAME == "nammaclean_qr_integration_db", (
        f"Guard Failure: Target database must be 'nammaclean_qr_integration_db', found '{INTEGRATION_DB_NAME}'!"
    )
    assert "5432" not in INTEGRATION_ASYNC_DB_URL, (
        "Security Alert: Port 5432 (MigrationGuard / host PostgreSQL) detected in URL!"
    )
    assert "nammaclean_db" not in INTEGRATION_ASYNC_DB_URL, (
        "Security Alert: Development database 'nammaclean_db' detected in URL!"
    )
    assert "nammaclean_test_db" not in INTEGRATION_ASYNC_DB_URL, (
        "Security Alert: Existing test database 'nammaclean_test_db' detected in URL!"
    )


# ==============================================================================
# Section 2: Fixtures (Engine, SessionMaker, Preflight Verification)
# ==============================================================================

@pytest_asyncio.fixture(scope="function")
async def integration_engine():
    """
    Function-scoped isolated SQLAlchemy async engine for nammaclean_qr_integration_db.
    Executes live catalog preflight verification before yielding and disposes pool on teardown.
    """
    _assert_integration_target_isolation()

    engine = create_async_engine(
        INTEGRATION_ASYNC_DB_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    # Physical pre-flight verification on live connection
    try:
        async with engine.connect() as conn:
            # 1. Verify current database and user
            res = await conn.execute(text("SELECT current_database(), current_user;"))
            curr_db, curr_user = res.fetchone()
            if curr_db != INTEGRATION_DB_NAME:
                await engine.dispose()
                raise RuntimeError(
                    f"FATAL: Database guard failed! Expected '{INTEGRATION_DB_NAME}', connected to '{curr_db}'. Aborting."
                )

            # 2. Confirm Alembic revision reaches QR milestone (b7e4d2c9f1a8)
            rev_res = await conn.execute(text("SELECT version_num FROM alembic_version;"))
            actual_rev = rev_res.scalar_one_or_none()
            if actual_rev != EXPECTED_ALEMBIC_REVISION:
                await engine.dispose()
                raise RuntimeError(
                    f"FATAL: Database guard failed! Expected revision '{EXPECTED_ALEMBIC_REVISION}', found '{actual_rev}'. "
                    "Ensure migrations are applied to nammaclean_qr_integration_db before running integration tests."
                )

            # 3. Confirm PostGIS extension is active
            gis_res = await conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'postgis';"))
            if not gis_res.scalar_one_or_none():
                await engine.dispose()
                raise RuntimeError("FATAL: PostGIS extension not active in nammaclean_qr_integration_db! Aborting.")
    except Exception as exc:
        await engine.dispose()
        raise RuntimeError(
            f"Preflight failure on {INTEGRATION_DB_NAME} (localhost:{INTEGRATION_DB_PORT}): {exc}"
        ) from exc

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
def integration_session_factory(integration_engine):
    """Provides an async sessionmaker bound strictly to nammaclean_qr_integration_db."""
    return async_sessionmaker(
        bind=integration_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture(scope="function")
async def integration_session(integration_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Yields a function-scoped direct async database session with automatic cleanup."""
    async with integration_session_factory() as session:
        yield session
        if session.is_active:
            await session.rollback()
        await session.close()


# ==============================================================================
# Section 3: Entity Tracker for Surgical Cleanup
# ==============================================================================

class QrIntegrationEntityTracker:
    """Collects entity IDs created during a test to ensure safe foreign-key reverse cleanup."""
    def __init__(self):
        self.qr_token_ids: List[uuid.UUID] = []
        self.attendance_record_ids: List[uuid.UUID] = []
        self.muster_point_ids: List[uuid.UUID] = []
        self.assignment_ids: List[uuid.UUID] = []
        self.user_ids: List[uuid.UUID] = []
        self.ward_ids: List[uuid.UUID] = []

    async def cleanup(self, session_factory):
        """Executes foreign-key safe reverse deletion of all tracked test records."""
        async with session_factory() as session:
            try:
                # 1. Attendance QR tokens
                if self.qr_token_ids:
                    await session.execute(
                        delete(AttendanceQrToken).where(AttendanceQrToken.id.in_(self.qr_token_ids))
                    )
                # 2. Attendance records
                if self.attendance_record_ids:
                    await session.execute(
                        delete(AttendanceRecord).where(AttendanceRecord.id.in_(self.attendance_record_ids))
                    )
                # 3. Muster points
                if self.muster_point_ids:
                    await session.execute(
                        delete(MusterPoint).where(MusterPoint.id.in_(self.muster_point_ids))
                    )
                # 4. User ward assignments
                if self.assignment_ids:
                    await session.execute(
                        delete(UserWardAssignment).where(UserWardAssignment.id.in_(self.assignment_ids))
                    )
                # 5. Users
                if self.user_ids:
                    await session.execute(
                        delete(User).where(User.id.in_(self.user_ids))
                    )
                # 6. Wards
                if self.ward_ids:
                    await session.execute(
                        delete(Ward).where(Ward.id.in_(self.ward_ids))
                    )
                await session.commit()
            except Exception:
                await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def entity_tracker(integration_session_factory) -> AsyncGenerator[QrIntegrationEntityTracker, None]:
    """Provides a tracker that cleans up all created test entities after each test case."""
    tracker = QrIntegrationEntityTracker()
    yield tracker
    await tracker.cleanup(integration_session_factory)


# ==============================================================================
# Section 4: Seed Helpers
# ==============================================================================

async def create_test_ward(session: AsyncSession, tracker: QrIntegrationEntityTracker) -> Ward:
    """Creates a temporary ward for testing."""
    ward = Ward(
        id=uuid.uuid4(),
        ward_code=f"W-{uuid.uuid4().hex[:6].upper()}",
        display_name="Test Ward Bellandur",
        boundary=None,
    )
    session.add(ward)
    await session.commit()
    await session.refresh(ward)
    tracker.ward_ids.append(ward.id)
    return ward


async def create_test_user(
    session: AsyncSession,
    tracker: QrIntegrationEntityTracker,
    role: UserRole,
    email_prefix: str = "user",
) -> User:
    """Creates a temporary user with the specified role and ACTIVE status."""
    now = utc_now()
    user = User(
        id=uuid.uuid4(),
        email=f"{email_prefix}_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("IntegrationTestPass123!"),
        role=role.value,
        status=UserStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    tracker.user_ids.append(user.id)
    return user


async def assign_user_to_ward(
    session: AsyncSession,
    tracker: QrIntegrationEntityTracker,
    user_id: uuid.UUID,
    ward_id: uuid.UUID,
) -> UserWardAssignment:
    """Creates an active ward assignment for a user."""
    assignment = UserWardAssignment(
        id=uuid.uuid4(),
        user_id=user_id,
        ward_id=ward_id,
        revoked_at=None,
    )
    session.add(assignment)
    await session.commit()
    await session.refresh(assignment)
    tracker.assignment_ids.append(assignment.id)
    return assignment


async def create_test_muster_point(
    session: AsyncSession,
    tracker: QrIntegrationEntityTracker,
    ward_id: uuid.UUID,
    latitude: float = 12.9260,
    longitude: float = 77.6740,
    radius_meters: int = 150,
) -> MusterPoint:
    """Creates an active muster point with PostGIS Point geometry."""
    now = utc_now()
    point_geom = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
    mp = MusterPoint(
        id=uuid.uuid4(),
        ward_id=ward_id,
        name=f"Muster Station {uuid.uuid4().hex[:6]}",
        location=point_geom,
        geofence_radius_meters=radius_meters,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(mp)
    await session.commit()
    await session.refresh(mp)
    tracker.muster_point_ids.append(mp.id)
    return mp


# ==============================================================================
# Section 5: Integration Test Cases
# ==============================================================================

@pytest.mark.asyncio
async def test_qr_token_row_lock_contention_and_serialization(
    integration_session_factory,
    entity_tracker,
):
    """
    TEST 1: Deterministic PostgreSQL Row-Lock Contention.

    Guarantees:
    1. Uses two independent AsyncSession connections with distinct PostgreSQL backend PIDs.
    2. Transaction A acquires exclusive row lock on AttendanceQrToken (SELECT ... FOR UPDATE).
    3. Transaction B attempts redemption of the exact same token and blocks in PostgreSQL.
    4. A monitor session confirms via pg_blocking_pids(pid_b) and pg_stat_activity that
       pid_b is waiting on pid_a with wait_event_type = 'Lock'.
    5. Transaction A commits check-in, releasing the row lock.
    6. Transaction B unblocks, re-evaluates the locked row, reads redeemed_at IS NOT NULL,
       and raises QrTokenAlreadyRedeemedError.
    7. Exactly 1 attendance record persists (Worker 1); Worker 2 gets zero attendance.
    """
    _assert_integration_target_isolation()

    # Step 1: Seed base entities in a setup session
    async with integration_session_factory() as setup_session:
        ward = await create_test_ward(setup_session, entity_tracker)
        supervisor = await create_test_user(setup_session, entity_tracker, UserRole.WARD_SUPERVISOR, "sup")
        await assign_user_to_ward(setup_session, entity_tracker, supervisor.id, ward.id)
        worker_1 = await create_test_user(setup_session, entity_tracker, UserRole.SANITATION_WORKER, "w1")
        worker_2 = await create_test_user(setup_session, entity_tracker, UserRole.SANITATION_WORKER, "w2")
        await assign_user_to_ward(setup_session, entity_tracker, worker_1.id, ward.id)
        await assign_user_to_ward(setup_session, entity_tracker, worker_2.id, ward.id)
        mp = await create_test_muster_point(setup_session, entity_tracker, ward.id, 12.9260, 77.6740, 150)

        # Generate a valid single-use QR token
        qr_token, raw_token = await generate_qr_token(setup_session, mp.id, ward.id, supervisor)
        await setup_session.commit()
        entity_tracker.qr_token_ids.append(qr_token.id)

    # Step 2: Open independent sessions and obtain backend PIDs
    async with integration_session_factory() as session_a, \
               integration_session_factory() as session_b, \
               integration_session_factory() as session_mon:

        pid_a = (await session_a.execute(text("SELECT pg_backend_pid();"))).scalar()
        pid_b = (await session_b.execute(text("SELECT pg_backend_pid();"))).scalar()
        assert pid_a != pid_b, "Isolation Failure: Both sessions share the same PostgreSQL backend!"

        token_hash = hash_qr_token(raw_token)
        lock_a_acquired = asyncio.Event()
        b_blocked_confirmed = asyncio.Event()
        outcome_b: Dict[str, Any] = {"exception": None}

        # Task A: Acquires row lock, waits for B's contention proof, then commits
        async def task_a_workflow():
            # Acquire exclusive row lock in PostgreSQL
            stmt = select(AttendanceQrToken).where(AttendanceQrToken.token_hash == token_hash).with_for_update()
            res = await session_a.execute(stmt)
            token = res.scalars().first()
            assert token is not None
            lock_a_acquired.set()

            # Wait until monitor confirms Transaction B is blocked waiting for pid_a
            await asyncio.wait_for(b_blocked_confirmed.wait(), timeout=5.0)

            # Perform check-in and commit
            server_now = utc_now()
            record = await record_check_in(
                session=session_a,
                worker_id=worker_1.id,
                ward_id=ward.id,
                muster_point_id=mp.id,
                latitude=12.9260,
                longitude=77.6740,
                check_in_time=server_now,
            )
            entity_tracker.attendance_record_ids.append(record.id)
            token.redeemed_at = server_now
            token.redeemed_by = worker_1.id
            token.attendance_record_id = record.id
            token.updated_at = server_now
            await session_a.commit()

        # Task B: Competing redemption that must block at PostgreSQL level and fail upon unblocking
        async def task_b_workflow():
            await lock_a_acquired.wait()
            try:
                # This call executes SELECT ... FOR UPDATE and BLOCKS in PostgreSQL until Task A commits
                await redeem_qr_attendance(
                    session=session_b,
                    worker_id=worker_2.id,
                    raw_token=raw_token,
                    latitude=12.9260,
                    longitude=77.6740,
                )
            except Exception as exc:
                outcome_b["exception"] = exc
            finally:
                if session_b.is_active:
                    await session_b.rollback()

        task_a = asyncio.create_task(task_a_workflow())
        task_b = asyncio.create_task(task_b_workflow())

        try:
            # Step 3: Monitor session polls PostgreSQL to confirm live contention
            await asyncio.wait_for(lock_a_acquired.wait(), timeout=3.0)

            contention_verified = False
            for _ in range(50):
                res = await session_mon.execute(
                    text("""
                        SELECT 
                            a.pid AS blocked_pid,
                            a.wait_event_type,
                            a.wait_event,
                            pg_blocking_pids(a.pid) AS blockers
                        FROM pg_stat_activity a
                        WHERE a.pid = :pid_b;
                    """),
                    {"pid_b": pid_b},
                )
                row = res.mappings().first()
                if row and pid_a in (row["blockers"] or []):
                    assert row["wait_event_type"] == "Lock"
                    assert row["wait_event"] in ("tuple", "transactionid")
                    contention_verified = True
                    break
                await asyncio.sleep(0.05)

            assert contention_verified, (
                f"Contention Verification Failed: Backend pid_b ({pid_b}) was not blocked by pid_a ({pid_a})!"
            )
            b_blocked_confirmed.set()

            # Await both tasks to complete
            await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=10.0)

        finally:
            # Clean up tasks and sessions safely
            for task in (task_a, task_b):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        # Step 4: Verify outcome
        assert isinstance(outcome_b["exception"], QrTokenAlreadyRedeemedError), (
            f"Expected QrTokenAlreadyRedeemedError, got {type(outcome_b['exception']).__name__}: {outcome_b['exception']}"
        )

        # Step 5: Database verification via fresh session
        async with integration_session_factory() as verify_session:
            # Exactly 1 attendance record for Worker 1
            att_w1 = (await verify_session.execute(
                select(AttendanceRecord).where(AttendanceRecord.worker_id == worker_1.id)
            )).scalars().all()
            assert len(att_w1) == 1
            assert att_w1[0].status == AttendanceStatus.PRESENT.value

            # Zero attendance records for Worker 2
            att_w2 = (await verify_session.execute(
                select(AttendanceRecord).where(AttendanceRecord.worker_id == worker_2.id)
            )).scalars().all()
            assert len(att_w2) == 0

            # Token redeemed by Worker 1
            persisted_token = (await verify_session.execute(
                select(AttendanceQrToken).where(AttendanceQrToken.id == qr_token.id)
            )).scalars().first()
            assert persisted_token.redeemed_at is not None
            assert persisted_token.redeemed_by == worker_1.id


@pytest.mark.asyncio
async def test_qr_redemption_atomic_rollback_consistency(
    integration_session_factory,
    entity_tracker,
):
    """
    TEST 2: Atomic Rollback Consistency.

    Guarantees:
    1. Exercises the actual redeem_qr_attendance service inside an outer transaction.
    2. Proves that AttendanceRecord and updated AttendanceQrToken exist in the session's
       flushed snapshot prior to commit.
    3. Simulates an outer transaction exception (e.g. server crash or serialization failure)
       and triggers an explicit rollback.
    4. Uses a fresh independent session to verify that neither the attendance record nor
       the token redemption changes persisted in PostgreSQL.
    """
    _assert_integration_target_isolation()

    # Step 1: Seed base entities
    async with integration_session_factory() as setup_session:
        ward = await create_test_ward(setup_session, entity_tracker)
        supervisor = await create_test_user(setup_session, entity_tracker, UserRole.WARD_SUPERVISOR, "sup")
        await assign_user_to_ward(setup_session, entity_tracker, supervisor.id, ward.id)
        worker = await create_test_user(setup_session, entity_tracker, UserRole.SANITATION_WORKER, "w")
        await assign_user_to_ward(setup_session, entity_tracker, worker.id, ward.id)
        mp = await create_test_muster_point(setup_session, entity_tracker, ward.id, 12.9260, 77.6740, 150)

        qr_token, raw_token = await generate_qr_token(setup_session, mp.id, ward.id, supervisor)
        await setup_session.commit()
        entity_tracker.qr_token_ids.append(qr_token.id)

    # Step 2: Execute redeem_qr_attendance and inject controlled rollback
    class ControlledFailureException(Exception):
        """Simulated exception injected prior to outer transaction commit."""
        pass

    async with integration_session_factory() as session:
        try:
            async with session.begin():
                record, token, dist, is_within = await redeem_qr_attendance(
                    session=session,
                    worker_id=worker.id,
                    raw_token=raw_token,
                    latitude=12.9260,
                    longitude=77.6740,
                )
                # Confirm changes exist in current flushed transaction snapshot
                assert record.id is not None
                assert token.redeemed_at is not None
                assert token.redeemed_by == worker.id

                # Controlled exception injection before outer commit
                raise ControlledFailureException("Simulated connection drop before outer commit")
        except ControlledFailureException:
            pass  # Session rollback automatically executed by session.begin() context manager

    # Step 3: Fresh independent session verification
    async with integration_session_factory() as verify_session:
        # 1. No attendance record persists
        att_res = await verify_session.execute(
            select(AttendanceRecord).where(AttendanceRecord.worker_id == worker.id)
        )
        assert att_res.scalars().first() is None, "Atomicity Failure: Attendance record survived rollback!"

        # 2. QR token remains completely unredeemed
        token_res = await verify_session.execute(
            select(AttendanceQrToken).where(AttendanceQrToken.id == qr_token.id)
        )
        persisted_token = token_res.scalars().first()
        assert persisted_token is not None
        assert persisted_token.redeemed_at is None, "Atomicity Failure: Token marked redeemed after rollback!"
        assert persisted_token.redeemed_by is None
        assert persisted_token.attendance_record_id is None


@pytest.mark.asyncio
async def test_concurrent_daily_attendance_uniqueness_constraint(
    integration_session_factory,
    entity_tracker,
):
    """
    TEST 3: Concurrent Daily Attendance Uniqueness.

    Guarantees:
    1. Issues two separate valid QR tokens (Token 1 and Token 2) for the same muster point.
    2. Two independent database sessions and transactions attempt redemption for the same worker
       on the same civic workday.
    3. Uses a deterministic synchronization barrier around validate_check_in_eligibility to guarantee
       that BOTH sessions execute and pass their application-level SELECT queries before EITHER
       attempts insertion.
    4. Session 1 inserts and commits its attendance record.
    5. Session 2 attempts insertion of the duplicate (worker_id, attendance_date) record, forcing
       PostgreSQL's physical unique constraint uq_worker_daily_attendance to arbitrate the race.
    6. Confirms the losing transaction reaches is_duplicate_attendance_integrity_error and translates
       the PostgreSQL UniqueViolation into DuplicateAttendanceError, with the underlying IntegrityError
       chained as __cause__.
    7. In a fresh session, verifies that exactly 1 attendance record exists (from Session 1) and that
       Token 2 remains completely unredeemed.
    8. Uses bounded timeouts and guaranteed cleanup of sessions, tasks, and the synchronization seam.
    """
    _assert_integration_target_isolation()

    # Step 1: Seed base entities
    async with integration_session_factory() as setup_session:
        ward = await create_test_ward(setup_session, entity_tracker)
        supervisor = await create_test_user(setup_session, entity_tracker, UserRole.WARD_SUPERVISOR, "sup")
        await assign_user_to_ward(setup_session, entity_tracker, supervisor.id, ward.id)
        worker = await create_test_user(setup_session, entity_tracker, UserRole.SANITATION_WORKER, "w")
        await assign_user_to_ward(setup_session, entity_tracker, worker.id, ward.id)
        mp = await create_test_muster_point(setup_session, entity_tracker, ward.id, 12.9260, 77.6740, 150)

        token_1, raw_token_1 = await generate_qr_token(setup_session, mp.id, ward.id, supervisor)
        token_2, raw_token_2 = await generate_qr_token(setup_session, mp.id, ward.id, supervisor)
        await setup_session.commit()
        entity_tracker.qr_token_ids.extend([token_1.id, token_2.id])

    # Step 2: Open two independent sessions with distinct backends
    async with integration_session_factory() as session_1, \
               integration_session_factory() as session_2:

        pid_1 = (await session_1.execute(text("SELECT pg_backend_pid();"))).scalar()
        pid_2 = (await session_2.execute(text("SELECT pg_backend_pid();"))).scalar()
        assert pid_1 != pid_2, "Isolation Failure: Both sessions share the same PostgreSQL backend!"

        # Synchronization barrier primitives
        s1_eligibility_passed = asyncio.Event()
        s2_eligibility_passed = asyncio.Event()
        s1_can_proceed = asyncio.Event()
        s2_can_proceed = asyncio.Event()

        orig_validate = att_service.validate_check_in_eligibility

        async def synchronized_validate(
            session: AsyncSession,
            worker_id: uuid.UUID,
            ward_id: uuid.UUID,
            muster_point_id: uuid.UUID,
            check_in_time: Optional[datetime] = None,
        ):
            # Run the actual validation query against the database
            res = await orig_validate(
                session=session,
                worker_id=worker_id,
                ward_id=ward_id,
                muster_point_id=muster_point_id,
                check_in_time=check_in_time,
            )
            # Signal barrier arrival and await coordinator release
            if session == session_1:
                s1_eligibility_passed.set()
                await asyncio.wait_for(s1_can_proceed.wait(), timeout=5.0)
            elif session == session_2:
                s2_eligibility_passed.set()
                await asyncio.wait_for(s2_can_proceed.wait(), timeout=5.0)
            return res

        outcome_1: Dict[str, Any] = {"record": None, "token": None, "exception": None}
        outcome_2: Dict[str, Any] = {"record": None, "token": None, "exception": None}

        async def task_1_workflow():
            try:
                rec, tok, dist, within = await redeem_qr_attendance(
                    session=session_1,
                    worker_id=worker.id,
                    raw_token=raw_token_1,
                    latitude=12.9260,
                    longitude=77.6740,
                )
                await session_1.commit()
                outcome_1["record"] = rec
                outcome_1["token"] = tok
                entity_tracker.attendance_record_ids.append(rec.id)
            except Exception as exc:
                outcome_1["exception"] = exc
                if session_1.is_active:
                    await session_1.rollback()

        async def task_2_workflow():
            try:
                rec, tok, dist, within = await redeem_qr_attendance(
                    session=session_2,
                    worker_id=worker.id,
                    raw_token=raw_token_2,
                    latitude=12.9260,
                    longitude=77.6740,
                )
                await session_2.commit()
                outcome_2["record"] = rec
                outcome_2["token"] = tok
                entity_tracker.attendance_record_ids.append(rec.id)
            except Exception as exc:
                outcome_2["exception"] = exc
            finally:
                if session_2.is_active:
                    await session_2.rollback()

        # Install narrowly scoped test seam
        att_service.validate_check_in_eligibility = synchronized_validate

        task_1 = asyncio.create_task(task_1_workflow())
        task_2 = asyncio.create_task(task_2_workflow())

        try:
            # Wait for both sessions to pass the application-level SELECT query
            await asyncio.wait_for(
                asyncio.gather(s1_eligibility_passed.wait(), s2_eligibility_passed.wait()),
                timeout=5.0,
            )

            # Release Session 1 to perform its insert and commit
            s1_can_proceed.set()
            await asyncio.wait_for(task_1, timeout=5.0)
            assert outcome_1["exception"] is None, f"Task 1 unexpectedly failed: {outcome_1['exception']}"

            # Release Session 2 to attempt its insert against the committed record
            s2_can_proceed.set()
            await asyncio.wait_for(task_2, timeout=5.0)

        finally:
            # Restore production validation function immediately
            att_service.validate_check_in_eligibility = orig_validate

            # Ensure tasks are safely cancelled and drained if any exception occurred
            for t in (task_1, task_2):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

        # Step 3: Verify the exception caught by Session 2
        exc_2 = outcome_2["exception"]
        assert exc_2 is not None, "Task 2 should have failed with DuplicateAttendanceError!"
        assert isinstance(exc_2, DuplicateAttendanceError), (
            f"Expected DuplicateAttendanceError, got {type(exc_2).__name__}: {exc_2}"
        )
        assert "already has an attendance record" in str(exc_2)

        # Prove that PostgreSQL's unique constraint uq_worker_daily_attendance was actually reached
        # If the check had stopped at the application SELECT level, __cause__ would be None!
        assert exc_2.__cause__ is not None, (
            "Integrity Seam Failure: exc.__cause__ is None! "
            "Session 2 stopped at the application-level SELECT rather than hitting PostgreSQL's unique constraint."
        )
        assert isinstance(exc_2.__cause__, IntegrityError), (
            f"Expected exc.__cause__ to be IntegrityError, got {type(exc_2.__cause__).__name__}"
        )
        assert "uq_worker_daily_attendance" in str(exc_2.__cause__).lower(), (
            f"Expected 'uq_worker_daily_attendance' in cause, got: {exc_2.__cause__}"
        )

    # Step 4: Fresh independent session verification
    async with integration_session_factory() as verify_session:
        # Exactly one attendance record exists
        records = (await verify_session.execute(
            select(AttendanceRecord).where(AttendanceRecord.worker_id == worker.id)
        )).scalars().all()
        assert len(records) == 1
        assert records[0].id == outcome_1["record"].id

        # Token 1 is redeemed
        t1 = (await verify_session.execute(
            select(AttendanceQrToken).where(AttendanceQrToken.id == token_1.id)
        )).scalars().first()
        assert t1.redeemed_at is not None
        assert t1.redeemed_by == worker.id
        assert t1.attendance_record_id == outcome_1["record"].id

        # Token 2 is NOT redeemed (preserves single-use voucher for future use)
        t2 = (await verify_session.execute(
            select(AttendanceQrToken).where(AttendanceQrToken.id == token_2.id)
        )).scalars().first()
        assert t2.redeemed_at is None
        assert t2.redeemed_by is None
        assert t2.attendance_record_id is None


@pytest.mark.asyncio
async def test_postgis_geometry_storage_and_haversine_distance_parity(
    integration_session_factory,
    entity_tracker,
):
    """
    TEST 4: PostGIS Geometry Storage & Distance Calculation Parity.

    Guarantees:
    1. Verifies PostGIS POINT geometry storage, SRID 4326, and X=lon, Y=lat mapping.
    2. Tests representative coordinate pairs (identical, close, geofence boundary, and outside).
    3. Compares PostGIS ST_Distance(geography) against Python calculate_haversine_distance_meters.
    4. Explains why a tolerance of <= 0.6 meters holds for local distances (< 500m)
       due to ellipsoidal WGS 84 (PostGIS) vs. spherical mean radius (Haversine).
    """
    _assert_integration_target_isolation()

    # Step 1: Create a muster station at Bellandur
    mp_lat, mp_lon = 12.9260, 77.6740
    async with integration_session_factory() as session:
        ward = await create_test_ward(session, entity_tracker)
        mp = await create_test_muster_point(session, entity_tracker, ward.id, mp_lat, mp_lon, 150)

        # Step 2: Query raw PostGIS spatial functions
        raw_res = await session.execute(
            text("""
                SELECT 
                    ST_GeometryType(location) AS geom_type,
                    ST_SRID(location) AS srid,
                    ST_X(location::geometry) AS lon,
                    ST_Y(location::geometry) AS lat
                FROM muster_points
                WHERE id = :mp_id;
            """),
            {"mp_id": mp.id},
        )
        row = raw_res.mappings().first()
        assert row["geom_type"] == "ST_Point"
        assert row["srid"] == 4326
        assert round(row["lon"], 4) == mp_lon
        assert round(row["lat"], 4) == mp_lat

        # Step 3: Test representative coordinate pairs against PostGIS geography ST_Distance
        test_points = [
            # (name, lat, lon, expected_geofence)
            ("Exact Station Point", 12.9260, 77.6740, True),
            ("Nearby Inside Geofence (~15.5m)", 12.9261, 77.6741, True),
            ("Geofence Boundary (~141.2m)", 12.9260, 77.6753, True),
            ("Outside Geofence (~304.3m)", 12.9260, 77.6768, False),
        ]

        for name, lat, lon, expected_inside in test_points:
            # Python Haversine calculation (mean spherical radius R = 6,371,000m)
            py_dist = calculate_haversine_distance_meters(lat, lon, mp_lat, mp_lon)

            # Native PostGIS WGS 84 ellipsoidal geodesic calculation
            gis_res = await session.execute(
                text("""
                    SELECT ST_Distance(
                        location::geography,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                    ) AS gis_dist
                    FROM muster_points
                    WHERE id = :mp_id;
                """),
                {"mp_id": mp.id, "lon": lon, "lat": lat},
            )
            gis_dist = gis_res.scalar()

            # Defensible mathematical tolerance:
            # Over distances < 500m, spherical Haversine vs. WGS 84 ellipsoidal geodesic
            # divergence is mathematically bounded to <= 0.35% (less than 0.6 meters).
            diff = abs(py_dist - gis_dist)
            assert diff <= 0.6, (
                f"Distance parity failure on '{name}': Python={py_dist:.2f}m, "
                f"PostGIS={gis_dist:.2f}m, diff={diff:.2f}m > 0.6m"
            )

            # Geofence boundary verification
            assert (py_dist <= mp.geofence_radius_meters) == expected_inside


@pytest.mark.asyncio
async def test_postgis_geofence_out_of_bounds_exception_persistence(
    integration_session_factory,
    entity_tracker,
):
    """
    TEST 5: Service-Layer PostGIS Geofence Out-of-Bounds Persistence.

    Guarantees:
    1. Redeems a valid QR token using coordinates situated ~304m from the muster station
       (exceeding the 150m geofence radius).
    2. Proves that the service does NOT reject the transaction, but records attendance with
       status EXCEPTION_PENDING and captures distance telemetry in exception_reason.
    3. Confirms is_within_geofence returns False to the caller.
    4. Verifies in a fresh session via raw PostGIS SQL that:
       - check_in_location is stored as a valid PostGIS POINT with SRID 4326.
       - Longitude is mapped to ST_X and latitude is mapped to ST_Y.
       - check_in_distance_meters reflects the out-of-bounds distance.
       - QR token is atomically marked redeemed and linked to the AttendanceRecord.
    """
    _assert_integration_target_isolation()

    mp_lat, mp_lon = 12.9260, 77.6740
    outside_lat, outside_lon = 12.9260, 77.6768  # ~304.3 meters east of muster station

    # Step 1: Seed base entities
    async with integration_session_factory() as setup_session:
        ward = await create_test_ward(setup_session, entity_tracker)
        supervisor = await create_test_user(setup_session, entity_tracker, UserRole.WARD_SUPERVISOR, "sup")
        await assign_user_to_ward(setup_session, entity_tracker, supervisor.id, ward.id)
        worker = await create_test_user(setup_session, entity_tracker, UserRole.SANITATION_WORKER, "w")
        await assign_user_to_ward(setup_session, entity_tracker, worker.id, ward.id)
        mp = await create_test_muster_point(setup_session, entity_tracker, ward.id, mp_lat, mp_lon, 150)

        qr_token, raw_token = await generate_qr_token(setup_session, mp.id, ward.id, supervisor)
        await setup_session.commit()
        entity_tracker.qr_token_ids.append(qr_token.id)

    # Step 2: Redeem QR token with coordinates outside geofence
    async with integration_session_factory() as session:
        record, token, distance_m, is_within = await redeem_qr_attendance(
            session=session,
            worker_id=worker.id,
            raw_token=raw_token,
            latitude=outside_lat,
            longitude=outside_lon,
        )
        assert is_within is False, "Expected is_within to be False for out-of-geofence check-in!"
        assert record.status == AttendanceStatus.EXCEPTION_PENDING.value
        assert "exceeds radius 150m" in record.exception_reason
        assert record.check_in_distance_meters > 150.0

        assert token.redeemed_at is not None
        assert token.redeemed_by == worker.id
        assert token.attendance_record_id == record.id

        await session.commit()
        entity_tracker.attendance_record_ids.append(record.id)

    # Step 3: Fresh session verification against live PostgreSQL/PostGIS catalog
    async with integration_session_factory() as verify_session:
        # 1. Query raw PostGIS spatial functions on attendance_records
        res = await verify_session.execute(
            text("""
                SELECT 
                    status,
                    exception_reason,
                    check_in_distance_meters,
                    ST_GeometryType(check_in_location) AS geom_type,
                    ST_SRID(check_in_location) AS srid,
                    ST_X(check_in_location::geometry) AS lon,
                    ST_Y(check_in_location::geometry) AS lat
                FROM attendance_records
                WHERE id = :record_id;
            """),
            {"record_id": record.id},
        )
        row = res.mappings().first()
        assert row is not None, "Attendance record not found in fresh verification session!"
        assert row["status"] == AttendanceStatus.EXCEPTION_PENDING.value
        assert "Check-in outside geofence" in row["exception_reason"]
        assert "exceeds radius 150m" in row["exception_reason"]
        assert row["check_in_distance_meters"] > 150.0
        assert row["geom_type"] == "ST_Point"
        assert row["srid"] == 4326
        assert round(row["lon"], 4) == outside_lon
        assert round(row["lat"], 4) == outside_lat

        # 2. Verify QR token persistence and atomic link
        token_res = await verify_session.execute(
            select(AttendanceQrToken).where(AttendanceQrToken.id == qr_token.id)
        )
        persisted_token = token_res.scalars().first()
        assert persisted_token is not None
        assert persisted_token.redeemed_at is not None
        assert persisted_token.redeemed_by == worker.id
        assert persisted_token.attendance_record_id == record.id


@pytest.mark.asyncio
async def test_schema_constraints_and_foreign_key_delete_rules(
    integration_session_factory,
    entity_tracker,
):
    """
    TEST 6: Schema Constraints & Foreign-Key Delete Rules.

    Guarantees:
    1. Verifies that migration b7e4d2c9f1a8 has created all tables, check constraints,
       and unique indexes:
       - ck_qr_token_expiry_after_issue rejects expires_at <= issued_at.
       - ix_attendance_qr_tokens_token_hash rejects duplicate token hashes.
    2. Verifies foreign-key delete rules:
       - Deleting an attendance record nullifies attendance_record_id on the QR token (ON DELETE SET NULL).
       - Deleting a muster point cascades and deletes its QR tokens (ON DELETE CASCADE).
    """
    _assert_integration_target_isolation()

    async with integration_session_factory() as session:
        ward = await create_test_ward(session, entity_tracker)
        supervisor = await create_test_user(session, entity_tracker, UserRole.WARD_SUPERVISOR, "sup")
        await assign_user_to_ward(session, entity_tracker, supervisor.id, ward.id)
        worker = await create_test_user(session, entity_tracker, UserRole.SANITATION_WORKER, "w")
        await assign_user_to_ward(session, entity_tracker, worker.id, ward.id)
        mp = await create_test_muster_point(session, entity_tracker, ward.id, 12.9260, 77.6740, 150)

        mp_id = mp.id
        ward_id = ward.id
        supervisor_id = supervisor.id
        worker_id = worker.id

        now = utc_now()

        # 1. Check constraint verification: expires_at <= issued_at must be rejected by PostgreSQL
        invalid_token = AttendanceQrToken(
            id=uuid.uuid4(),
            token_hash=hash_qr_token(f"nmc_qr_{uuid.uuid4().hex}"),
            muster_point_id=mp_id,
            ward_id=ward_id,
            issued_by=supervisor_id,
            issued_at=now,
            expires_at=now - timedelta(minutes=1),  # Invalid: expires before issue!
            created_at=now,
            updated_at=now,
        )
        session.add(invalid_token)
        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()
        await session.rollback()
        assert "ck_qr_token_expiry_after_issue" in str(exc_info.value).lower()

        # Refresh official user after rollback to avoid expired attribute lazy-load
        supervisor = await session.get(User, supervisor_id)
        worker = await session.get(User, worker_id)

        # 2. Unique index verification: duplicate token_hash must be rejected
        existing_hash = hash_qr_token(f"nmc_qr_{uuid.uuid4().hex}")
        token_a = AttendanceQrToken(
            id=uuid.uuid4(),
            token_hash=existing_hash,
            muster_point_id=mp_id,
            ward_id=ward_id,
            issued_by=supervisor_id,
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        )
        session.add(token_a)
        await session.commit()
        entity_tracker.qr_token_ids.append(token_a.id)

        token_b = AttendanceQrToken(
            id=uuid.uuid4(),
            token_hash=existing_hash,  # Duplicate hash!
            muster_point_id=mp_id,
            ward_id=ward_id,
            issued_by=supervisor_id,
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        )
        session.add(token_b)
        with pytest.raises(IntegrityError) as exc_info_hash:
            await session.commit()
        await session.rollback()
        assert "attendance_qr_tokens" in str(exc_info_hash.value).lower()

        # Refresh official user after rollback to avoid expired attribute lazy-load
        supervisor = await session.get(User, supervisor_id)
        worker = await session.get(User, worker_id)

        # 3. Foreign-Key SET NULL Verification: Deleting AttendanceRecord nullifies attendance_record_id
        valid_token_c, raw_token_c = await generate_qr_token(session, mp_id, ward_id, supervisor)
        await session.commit()
        entity_tracker.qr_token_ids.append(valid_token_c.id)

        record_c, _, _, _ = await redeem_qr_attendance(
            session=session,
            worker_id=worker.id,
            raw_token=raw_token_c,
            latitude=12.9260,
            longitude=77.6740,
        )
        await session.commit()
        entity_tracker.attendance_record_ids.append(record_c.id)

        # Confirm token references the attendance record
        tok_before = (await session.execute(
            select(AttendanceQrToken).where(AttendanceQrToken.id == valid_token_c.id)
        )).scalars().first()
        assert tok_before.attendance_record_id == record_c.id

        # Delete the attendance record directly
        await session.execute(delete(AttendanceRecord).where(AttendanceRecord.id == record_c.id))
        await session.commit()

        # Re-fetch token: token must still exist, but attendance_record_id must be NULL
        tok_after = (await session.execute(
            select(AttendanceQrToken)
            .where(AttendanceQrToken.id == valid_token_c.id)
            .execution_options(populate_existing=True)
        )).scalars().first()
        assert tok_after is not None, "Token was incorrectly deleted when AttendanceRecord was deleted!"
        assert tok_after.attendance_record_id is None, "Foreign Key Failure: attendance_record_id was not SET NULL!"

        # 4. Foreign-Key Cascade Verification: Deleting MusterPoint cascades to AttendanceQrToken
        supervisor = await session.get(User, supervisor_id)
        valid_token_d, _ = await generate_qr_token(session, mp_id, ward_id, supervisor)
        await session.commit()
        token_d_id = valid_token_d.id

        await session.execute(delete(MusterPoint).where(MusterPoint.id == mp_id))
        await session.commit()

        # Token should have been deleted by CASCADE foreign key
        tok_d = (await session.execute(
            select(AttendanceQrToken).where(AttendanceQrToken.id == token_d_id)
        )).scalars().first()
        assert tok_d is None, "Foreign Key Failure: QR token was not deleted when muster point was deleted!"
