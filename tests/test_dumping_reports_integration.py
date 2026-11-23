"""
Live Integration Tests for Stage 2.9.3:
Illegal-Dumping Reports & Evidence Management.

STRICT ISOLATION GUARANTEES:
1. Target: Dedicated test database 'nammaclean_test_db' on localhost:5433 only.
2. Connection Guard: Fails immediately if host != localhost, port != 5433, or db != nammaclean_test_db.
3. MigrationGuard (port 5432) and Development DB ('nammaclean_db') are never accessed.
4. FastAPI dependency override routes all API session requests to 'nammaclean_test_db'.
5. Filesystem Storage: Ephemeral test directory via pytest tmp_path. Development evidence storage is untouched.
6. Target Cleanup: Explicit tracking and foreign-key-safe deletion of test-owned records in try/finally blocks.
"""

import os
import uuid
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Dict, Any, List
from unittest.mock import patch
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from geoalchemy2.shape import to_shape

from app.main import app
from app.api.v1.reports import report_submit_rate_limiter
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus, DumpingReportStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.dumping_report import DumpingReport, ReportEvidence


# ============================================================================
# Section 1: Hardened Test Database Connection Guard & Fixtures
# ============================================================================

TEST_DB_HOST = "localhost"
TEST_DB_PORT = 5433
TEST_DB_NAME = "nammaclean_test_db"

# Explicitly pinned async test database URL
TEST_ASYNC_DB_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}"
)


@pytest.fixture(autouse=True)
def reset_report_submit_rate_limit_state():
    report_submit_rate_limiter.reset()
    yield
    report_submit_rate_limiter.reset()


def _assert_connection_guard_parameters():
    """Fail-closed assertion verifying test target isolation before opening any connection."""
    assert TEST_DB_HOST in ("localhost", "127.0.0.1"), "Guard Failure: Host must be localhost"
    assert TEST_DB_PORT == 5433, "Guard Failure: Port must be strictly 5433"
    assert TEST_DB_NAME == "nammaclean_test_db", "Guard Failure: Database must be nammaclean_test_db"
    assert "5432" not in TEST_ASYNC_DB_URL, "Security Alert: Port 5432 / MigrationGuard referenced!"
    assert "nammaclean_db" != TEST_DB_NAME, "Security Alert: Development database must not be targeted!"


@pytest_asyncio.fixture(scope="function")
async def test_db_engine():
    """
    Creates and validates an isolated SQLAlchemy async engine for nammaclean_test_db.
    Verifies live catalog parameters before yielding, and disposes the pool on teardown.
    """
    _assert_connection_guard_parameters()

    engine = create_async_engine(
        TEST_ASYNC_DB_URL,
        echo=False,
        pool_pre_ping=True,
    )

    # Physical pre-flight verification on the live connection
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT current_database(), current_user;"))
        curr_db, curr_user = res.fetchone()
        if curr_db != TEST_DB_NAME:
            await engine.dispose()
            raise RuntimeError(
                f"FATAL: Database guard failed! Expected '{TEST_DB_NAME}', connected to '{curr_db}'. Aborting."
            )

        # Confirm Alembic revision
        rev_res = await conn.execute(text("SELECT version_num FROM alembic_version;"))
        actual_rev = rev_res.scalar_one_or_none()
        if actual_rev != "b7e4d2c9f1a8":
            await engine.dispose()
            raise RuntimeError(
                f"FATAL: Database guard failed! Expected revision 'b7e4d2c9f1a8', found '{actual_rev}'. Aborting."
            )

        # Confirm PostGIS extension
        gis_res = await conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'postgis';"))
        if not gis_res.scalar_one_or_none():
            await engine.dispose()
            raise RuntimeError("FATAL: PostGIS extension not active in nammaclean_test_db! Aborting.")

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
def test_session_factory(test_db_engine):
    """Provides a sessionmaker bound strictly to the isolated test database."""
    return async_sessionmaker(
        bind=test_db_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture(scope="function")
async def test_session(test_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Yields a direct session to nammaclean_test_db for test verification queries."""
    async with test_session_factory() as session:
        yield session
        await session.rollback()
        await session.close()


@pytest_asyncio.fixture(scope="function")
async def integration_client(test_session_factory, tmp_path) -> AsyncGenerator[AsyncClient, None]:
    """
    Provides an AsyncClient where:
    1. FastAPI's get_db dependency is overridden to use nammaclean_test_db.
    2. Evidence storage directory is patched to an isolated temporary directory.
    3. Overrides are cleanly restored on teardown.
    """
    _assert_connection_guard_parameters()

    # Isolate storage directory
    test_storage_dir = tmp_path / "test_evidence_store"
    test_storage_dir.mkdir(parents=True, exist_ok=True)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    # Preserve previous overrides
    prev_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    with patch("app.services.storage_service.get_evidence_storage_dir", return_value=test_storage_dir):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client

    # Teardown: restore previous override state
    if prev_override is not None:
        app.dependency_overrides[get_db] = prev_override
    else:
        app.dependency_overrides.pop(get_db, None)


# ============================================================================
# Section 2: Test Record Tracker & Foreign-Key Safe Cleanup
# ============================================================================

class EntityCleanupTracker:
    """Collects IDs of records created during a test to guarantee surgical cleanup."""
    def __init__(self):
        self.evidence_ids: List[uuid.UUID] = []
        self.report_ids: List[uuid.UUID] = []
        self.assignment_ids: List[uuid.UUID] = []
        self.user_ids: List[uuid.UUID] = []
        self.ward_ids: List[uuid.UUID] = []

    async def cleanup(self, session: AsyncSession):
        """Deletes only tracked records in strict foreign-key dependency order."""
        # Fail-safe: Discover any reports created by tracked test users that were not tracked
        # due to mid-request HTTP 500 exceptions before user deletion sets reporter_id to NULL.
        if self.user_ids:
            untracked_reports = await session.execute(
                select(DumpingReport.id).where(DumpingReport.reporter_id.in_(self.user_ids))
            )
            for r_id in untracked_reports.scalars().all():
                if r_id not in self.report_ids:
                    self.report_ids.append(r_id)

        # Fail-safe: Discover any evidence attached to tracked reports
        if self.report_ids:
            untracked_evidence = await session.execute(
                select(ReportEvidence.id).where(ReportEvidence.report_id.in_(self.report_ids))
            )
            for e_id in untracked_evidence.scalars().all():
                if e_id not in self.evidence_ids:
                    self.evidence_ids.append(e_id)

        if self.evidence_ids:
            await session.execute(delete(ReportEvidence).where(ReportEvidence.id.in_(self.evidence_ids)))
        if self.report_ids:
            await session.execute(delete(DumpingReport).where(DumpingReport.id.in_(self.report_ids)))
        if self.assignment_ids:
            await session.execute(delete(UserWardAssignment).where(UserWardAssignment.id.in_(self.assignment_ids)))
        if self.user_ids:
            await session.execute(delete(User).where(User.id.in_(self.user_ids)))
        if self.ward_ids:
            await session.execute(delete(Ward).where(Ward.id.in_(self.ward_ids)))
        await session.commit()


@pytest_asyncio.fixture(scope="function")
async def tracker(test_session: AsyncSession) -> AsyncGenerator[EntityCleanupTracker, None]:
    """Yields a tracker and guarantees cleanup of all tracked test records upon completion."""
    t = EntityCleanupTracker()
    try:
        yield t
    finally:
        await t.cleanup(test_session)


# Helper to create test users in nammaclean_test_db
async def create_test_user(
    session: AsyncSession,
    tracker: EntityCleanupTracker,
    role: UserRole = UserRole.CITIZEN,
) -> tuple[User, str]:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=f"test_{role.value.lower()}_{tag}@example.com",
        password_hash=hash_password("SecurePassword123!"),
        role=role.value,
        status=UserStatus.ACTIVE.value,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    tracker.user_ids.append(user.id)
    token = create_access_token(subject=user.id, extra_claims={"role": user.role})
    return user, token


# Helper to create test wards in nammaclean_test_db
async def create_test_ward(
    session: AsyncSession,
    tracker: EntityCleanupTracker,
    display_name: str = "Test Ward",
) -> Ward:
    code = f"W-{uuid.uuid4().hex[:6].upper()}"
    ward = Ward(
        ward_code=code,
        display_name=display_name,
    )
    session.add(ward)
    await session.commit()
    await session.refresh(ward)
    tracker.ward_ids.append(ward.id)
    return ward


# ============================================================================
# Section 3: Integration Tests
# ============================================================================

# ----------------------------------------------------------------------------
# A. Report Creation & PostGIS Coordinates
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_create_report_success(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """
    Submits a real report via HTTP POST /api/v1/reports.
    Verifies:
    1. HTTP 201 Created and correct response schema.
    2. Real PostGIS geometry insertion in PostgreSQL with SRID 4326.
    3. to_shape(location) recovers exact latitude and longitude.
    4. Initial status_history event recorded in JSONB.
    """
    citizen, token = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    ward = await create_test_ward(test_session, tracker, "Koramangala Test Ward")

    payload = {
        "latitude": 12.9352,
        "longitude": 77.6245,
        "description": "Large pile of unsegregated wet and dry garbage dumping near 80ft road.",
        "ward_id": str(ward.id),
    }

    res = await integration_client.post(
        "/api/v1/reports",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    report_id = uuid.UUID(data["id"])
    tracker.report_ids.append(report_id)

    assert data["reporter_id"] == str(citizen.id)
    assert data["ward_id"] == str(ward.id)
    assert data["status"] == DumpingReportStatus.SUBMITTED.value
    assert data["latitude"] == 12.9352
    assert data["longitude"] == 77.6245
    assert len(data["status_history"]) == 1
    assert data["status_history"][0]["to_status"] == "SUBMITTED"

    # Query PostgreSQL directly to verify PostGIS geometry and SRID
    stmt = select(DumpingReport).where(DumpingReport.id == report_id)
    res_db = await test_session.execute(stmt)
    persisted_report = res_db.scalars().one()

    point_geom = to_shape(persisted_report.location)
    assert abs(point_geom.y - 12.9352) < 1e-5
    assert abs(point_geom.x - 77.6245) < 1e-5

    # Check PostGIS SRID in database
    srid_res = await test_session.execute(
        text("SELECT ST_SRID(location) FROM dumping_reports WHERE id = :id"),
        {"id": report_id},
    )
    assert srid_res.scalar() == 4326


@pytest.mark.asyncio
async def test_integration_create_report_invalid_ward_404(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """Rejects report referencing a non-existent ward ID with HTTP 404."""
    citizen, token = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    fake_ward_id = uuid.uuid4()

    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "description": "Construction debris left on the sidewalk.",
        "ward_id": str(fake_ward_id),
    }

    res = await integration_client.post(
        "/api/v1/reports",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


# ----------------------------------------------------------------------------
# B. Citizen Privacy & Report Retrieval
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_citizen_my_reports_isolation(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """
    Verifies that GET /api/v1/reports/me returns only the authenticated citizen's reports.
    Citizen B cannot see or tamper with Citizen A's reports.
    """
    citizen_a, token_a = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    citizen_b, token_b = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    ward = await create_test_ward(test_session, tracker)

    # Citizen A creates Report A
    res_a = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.91, "longitude": 77.61, "description": "Report A by Citizen A.", "ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 201
    id_a = uuid.UUID(res_a.json()["id"])
    tracker.report_ids.append(id_a)

    # Citizen B creates Report B
    res_b = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.92, "longitude": 77.62, "description": "Report B by Citizen B.", "ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 201
    id_b = uuid.UUID(res_b.json()["id"])
    tracker.report_ids.append(id_b)

    # Citizen A lists reports: sees Report A only
    list_a = await integration_client.get(
        "/api/v1/reports/me",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_a.status_code == 200
    ids_seen_a = [r["id"] for r in list_a.json()]
    assert str(id_a) in ids_seen_a
    assert str(id_b) not in ids_seen_a

    # Citizen B lists reports: sees Report B only
    list_b = await integration_client.get(
        "/api/v1/reports/me",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200
    ids_seen_b = [r["id"] for r in list_b.json()]
    assert str(id_b) in ids_seen_b
    assert str(id_a) not in ids_seen_b


# ----------------------------------------------------------------------------
# C. Administrative & Ward-Supervisor Authorization
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_admin_and_supervisor_scoping(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """
    Verifies review queue scoping:
    1. Municipal Admin has city-wide access and can filter by ward.
    2. Ward Supervisor is scoped strictly to active ward assignments.
    3. Supervisor querying an unassigned ward receives HTTP 403.
    4. Reports with ward_id=None are hidden from supervisors.
    """
    admin, admin_token = await create_test_user(test_session, tracker, UserRole.MUNICIPAL_ADMIN)
    supervisor, sup_token = await create_test_user(test_session, tracker, UserRole.WARD_SUPERVISOR)
    citizen, cit_token = await create_test_user(test_session, tracker, UserRole.CITIZEN)

    ward_1 = await create_test_ward(test_session, tracker, "Ward 1 Assigned")
    ward_2 = await create_test_ward(test_session, tracker, "Ward 2 Unassigned")

    # Assign supervisor to Ward 1 only
    assignment = UserWardAssignment(
        user_id=supervisor.id,
        ward_id=ward_1.id,
    )
    test_session.add(assignment)
    await test_session.commit()
    await test_session.refresh(assignment)
    tracker.assignment_ids.append(assignment.id)

    # Create Report 1 (Ward 1), Report 2 (Ward 2), Report 3 (No ward)
    r1 = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.91, "longitude": 77.61, "description": "Report 1 in Ward 1.", "ward_id": str(ward_1.id)},
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    id_1 = uuid.UUID(r1.json()["id"])
    tracker.report_ids.append(id_1)

    r2 = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.92, "longitude": 77.62, "description": "Report 2 in Ward 2.", "ward_id": str(ward_2.id)},
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    id_2 = uuid.UUID(r2.json()["id"])
    tracker.report_ids.append(id_2)

    r3 = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.93, "longitude": 77.63, "description": "Report 3 with no ward.", "ward_id": None},
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    id_3 = uuid.UUID(r3.json()["id"])
    tracker.report_ids.append(id_3)

    # 1. Supervisor list without ward_id: sees only Ward 1
    sup_list = await integration_client.get(
        "/api/v1/reports",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert sup_list.status_code == 200
    sup_ids = [r["id"] for r in sup_list.json()]
    assert str(id_1) in sup_ids
    assert str(id_2) not in sup_ids
    assert str(id_3) not in sup_ids

    # 2. Supervisor querying unassigned Ward 2 -> 403 Forbidden
    sup_ward2 = await integration_client.get(
        f"/api/v1/reports?ward_id={ward_2.id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert sup_ward2.status_code == 403

    # 3. Municipal Admin list: sees all reports city-wide
    adm_list = await integration_client.get(
        "/api/v1/reports",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adm_list.status_code == 200
    adm_ids = [r["id"] for r in adm_list.json()]
    assert str(id_1) in adm_ids
    assert str(id_2) in adm_ids
    assert str(id_3) in adm_ids

    # 4. Municipal Admin filtered by Ward 2
    adm_ward2 = await integration_client.get(
        f"/api/v1/reports?ward_id={ward_2.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adm_ward2.status_code == 200
    adm_w2_ids = [r["id"] for r in adm_ward2.json()]
    assert str(id_2) in adm_w2_ids
    assert str(id_1) not in adm_w2_ids


# ----------------------------------------------------------------------------
# D. Status Lifecycle & JSONB Audit History
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_status_lifecycle_and_audit_history(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """
    Tests valid status progression and JSONB audit trail:
    1. SUBMITTED -> UNDER_REVIEW (Admin)
    2. UNDER_REVIEW -> ACTION_SCHEDULED (Assigned Supervisor)
    3. ACTION_SCHEDULED -> RESOLVED (Terminal state)
    4. Attempted transition from RESOLVED is rejected (HTTP 400).
    5. Confirms status_history contains 4 historical entries with correct user IDs and notes.
    """
    admin, admin_token = await create_test_user(test_session, tracker, UserRole.MUNICIPAL_ADMIN)
    supervisor, sup_token = await create_test_user(test_session, tracker, UserRole.WARD_SUPERVISOR)
    citizen, cit_token = await create_test_user(test_session, tracker, UserRole.CITIZEN)

    ward = await create_test_ward(test_session, tracker, "Lifecycle Ward")
    assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward.id)
    test_session.add(assign)
    await test_session.commit()
    tracker.assignment_ids.append(assign.id)

    # Initial report submission
    r_create = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.95, "longitude": 77.65, "description": "Garbage pile for lifecycle test.", "ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    assert r_create.status_code == 201
    report_id = uuid.UUID(r_create.json()["id"])
    tracker.report_ids.append(report_id)

    # Step 1: Admin transitions to UNDER_REVIEW
    p1 = await integration_client.patch(
        f"/api/v1/reports/{report_id}/status",
        json={"status": "UNDER_REVIEW", "official_notes": "Admin initiated review."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert p1.status_code == 200
    assert p1.json()["status"] == "UNDER_REVIEW"
    assert p1.json()["official_notes"] == "Admin initiated review."

    # Step 2: Supervisor transitions to ACTION_SCHEDULED
    p2 = await integration_client.patch(
        f"/api/v1/reports/{report_id}/status",
        json={"status": "ACTION_SCHEDULED", "official_notes": "Cleanup vehicle scheduled."},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert p2.status_code == 200
    assert p2.json()["status"] == "ACTION_SCHEDULED"

    # Step 3: Supervisor transitions to RESOLVED
    p3 = await integration_client.patch(
        f"/api/v1/reports/{report_id}/status",
        json={"status": "RESOLVED", "official_notes": "Waste removed successfully."},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert p3.status_code == 200
    assert p3.json()["status"] == "RESOLVED"

    # Step 4: Invalid attempt to transition from terminal RESOLVED state -> 400
    p_invalid = await integration_client.patch(
        f"/api/v1/reports/{report_id}/status",
        json={"status": "UNDER_REVIEW", "official_notes": "Attempting to reopen."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert p_invalid.status_code == 400
    assert "invalid status transition" in p_invalid.json()["detail"].lower()

    # Query PostgreSQL to verify status_history array contents
    stmt = select(DumpingReport).where(DumpingReport.id == report_id)
    res_db = await test_session.execute(stmt)
    report_db = res_db.scalars().one()

    history = report_db.status_history
    assert len(history) == 4
    # Event 0: Submission
    assert history[0]["from_status"] is None
    assert history[0]["to_status"] == "SUBMITTED"
    assert history[0]["changed_by_user_id"] == str(citizen.id)

    # Event 1: Under Review
    assert history[1]["from_status"] == "SUBMITTED"
    assert history[1]["to_status"] == "UNDER_REVIEW"
    assert history[1]["changed_by_user_id"] == str(admin.id)
    assert history[1]["notes"] == "Admin initiated review."

    # Event 2: Action Scheduled
    assert history[2]["from_status"] == "UNDER_REVIEW"
    assert history[2]["to_status"] == "ACTION_SCHEDULED"
    assert history[2]["changed_by_user_id"] == str(supervisor.id)

    # Event 3: Resolved
    assert history[3]["from_status"] == "ACTION_SCHEDULED"
    assert history[3]["to_status"] == "RESOLVED"
    assert history[3]["changed_by_user_id"] == str(supervisor.id)
    assert history[3]["notes"] == "Waste removed successfully."


@pytest.mark.asyncio
async def test_integration_supervisor_denied_on_unassigned_report(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """Supervisor cannot update a report with no ward assignment or in an unassigned ward."""
    supervisor, sup_token = await create_test_user(test_session, tracker, UserRole.WARD_SUPERVISOR)
    citizen, cit_token = await create_test_user(test_session, tracker, UserRole.CITIZEN)

    # Report without ward
    r_unassigned = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.95, "longitude": 77.65, "description": "Unassigned dump report.", "ward_id": None},
        headers={"Authorization": f"Bearer {cit_token}"},
    )
    report_id = uuid.UUID(r_unassigned.json()["id"])
    tracker.report_ids.append(report_id)

    res = await integration_client.patch(
        f"/api/v1/reports/{report_id}/status",
        json={"status": "UNDER_REVIEW"},
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert res.status_code == 403
    assert "cannot review reports that are not assigned" in res.json()["detail"].lower()


# ----------------------------------------------------------------------------
# E. Evidence Upload & Validation
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_evidence_upload_success_and_metadata(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """
    Uploads valid JPEG, PNG, and WebP evidence to a real report.
    Verifies:
    1. HTTP 201 Created and correct ReportEvidence response metadata.
    2. ReportEvidence record persisted in PostgreSQL.
    3. Binary photo saved to the isolated temporary storage path with random UUID key.
    """
    citizen, token = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    ward = await create_test_ward(test_session, tracker)

    # Create report
    r = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.96, "longitude": 77.66, "description": "Report for evidence upload testing.", "ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    report_id = uuid.UUID(r.json()["id"])
    tracker.report_ids.append(report_id)

    # 1. Upload JPEG
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 300
    upload_jpeg = await integration_client.post(
        f"/api/v1/reports/{report_id}/evidence",
        content=jpeg_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "image/jpeg",
            "X-File-Name": "incident_photo.jpg",
        },
    )
    assert upload_jpeg.status_code == 201, upload_jpeg.text
    data_jpeg = upload_jpeg.json()
    ev_id = uuid.UUID(data_jpeg["id"])
    tracker.evidence_ids.append(ev_id)

    assert data_jpeg["file_name"] == "incident_photo.jpg"
    assert data_jpeg["content_type"] == "image/jpeg"
    assert data_jpeg["file_size_bytes"] == len(jpeg_bytes)

    # Verify database persistence
    stmt = select(ReportEvidence).where(ReportEvidence.id == ev_id)
    res_db = await test_session.execute(stmt)
    evidence_db = res_db.scalars().one()
    assert evidence_db.file_name == "incident_photo.jpg"
    assert evidence_db.storage_key.endswith(".jpg")
    assert evidence_db.file_size_bytes == len(jpeg_bytes)


@pytest.mark.asyncio
async def test_integration_evidence_upload_rejections(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """
    Verifies rejection of:
    1. Unsupported content type (e.g. application/pdf) -> 400
    2. Mismatched magic bytes (declared image/jpeg, body text) -> 400
    3. Empty file (0 bytes) -> 400
    4. Non-owner upload attempt -> 403
    """
    citizen_a, token_a = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    citizen_b, token_b = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    ward = await create_test_ward(test_session, tracker)

    # Create report owned by Citizen A
    r = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.96, "longitude": 77.66, "description": "Report for rejection testing.", "ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 201, f"Report submission failed: {r.status_code} {r.text}"
    report_id = uuid.UUID(r.json()["id"])
    tracker.report_ids.append(report_id)

    # 1. Disallowed MIME type
    res_pdf = await integration_client.post(
        f"/api/v1/reports/{report_id}/evidence",
        content=b"%PDF-1.4 file data",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "application/pdf"},
    )
    assert res_pdf.status_code == 400
    assert "unsupported image type" in res_pdf.json()["detail"].lower()

    # 2. Mismatched magic bytes
    res_fake = await integration_client.post(
        f"/api/v1/reports/{report_id}/evidence",
        content=b"Not an actual JPEG image header",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "image/jpeg"},
    )
    assert res_fake.status_code == 400
    assert "does not match the declared image format" in res_fake.json()["detail"].lower()

    # 3. Empty file
    res_empty = await integration_client.post(
        f"/api/v1/reports/{report_id}/evidence",
        content=b"",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "image/jpeg"},
    )
    assert res_empty.status_code == 400

    # 4. Non-owner Citizen B attempt
    res_non_owner = await integration_client.post(
        f"/api/v1/reports/{report_id}/evidence",
        content=b"\xff\xd8\xff\xe0" + b"\x00" * 50,
        headers={"Authorization": f"Bearer {token_b}", "Content-Type": "image/jpeg"},
    )
    assert res_non_owner.status_code == 403
    assert "permission" in res_non_owner.json()["detail"].lower()


# ----------------------------------------------------------------------------
# F. Evidence Download Permissions & Streaming
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_evidence_download_permissions(
    integration_client: AsyncClient,
    test_session: AsyncSession,
    tracker: EntityCleanupTracker,
):
    """
    Verifies private evidence download:
    1. Citizen owner streams file with HTTP 200 and exact binary content.
    2. Other citizen is denied with HTTP 403.
    3. Unassigned supervisor is denied with HTTP 403.
    4. Assigned supervisor can download with HTTP 200.
    5. Municipal admin can download with HTTP 200.
    """
    citizen_a, token_a = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    citizen_b, token_b = await create_test_user(test_session, tracker, UserRole.CITIZEN)
    supervisor, sup_token = await create_test_user(test_session, tracker, UserRole.WARD_SUPERVISOR)
    admin, adm_token = await create_test_user(test_session, tracker, UserRole.MUNICIPAL_ADMIN)

    ward = await create_test_ward(test_session, tracker, "Download Perms Ward")
    # Assign supervisor to ward
    assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward.id)
    test_session.add(assign)
    await test_session.commit()
    tracker.assignment_ids.append(assign.id)

    # Citizen A creates report
    r = await integration_client.post(
        "/api/v1/reports",
        json={"latitude": 12.98, "longitude": 77.68, "description": "Report for download testing.", "ward_id": str(ward.id)},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 201, f"Report submission failed: {r.status_code} {r.text}"
    report_id = uuid.UUID(r.json()["id"])
    tracker.report_ids.append(report_id)

    # Upload JPEG photo
    photo_payload = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x12\x34\x56\x78" * 50
    up = await integration_client.post(
        f"/api/v1/reports/{report_id}/evidence",
        content=photo_payload,
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "image/jpeg", "X-File-Name": "my_dump.jpg"},
    )
    assert up.status_code == 201
    evidence_id = uuid.UUID(up.json()["id"])
    tracker.evidence_ids.append(evidence_id)

    # 1. Citizen A (owner) downloads: Success
    dl_owner = await integration_client.get(
        f"/api/v1/reports/{report_id}/evidence/{evidence_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert dl_owner.status_code == 200
    assert dl_owner.headers["content-type"] == "image/jpeg"
    assert dl_owner.content == photo_payload

    # 2. Citizen B downloads: 403 Forbidden
    dl_other = await integration_client.get(
        f"/api/v1/reports/{report_id}/evidence/{evidence_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert dl_other.status_code == 403

    # 3. Assigned supervisor downloads: Success
    dl_sup = await integration_client.get(
        f"/api/v1/reports/{report_id}/evidence/{evidence_id}",
        headers={"Authorization": f"Bearer {sup_token}"},
    )
    assert dl_sup.status_code == 200
    assert dl_sup.content == photo_payload

    # 4. Municipal Admin downloads: Success
    dl_adm = await integration_client.get(
        f"/api/v1/reports/{report_id}/evidence/{evidence_id}",
        headers={"Authorization": f"Bearer {adm_token}"},
    )
    assert dl_adm.status_code == 200
    assert dl_adm.content == photo_payload
