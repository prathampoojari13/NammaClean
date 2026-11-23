"""
Unit tests for Pourakarmika Attendance Lifecycle Endpoints:
- POST /api/v1/attendance/check-out
- GET /api/v1/wards/{ward_id}/attendance/daily
- POST /api/v1/attendance/{record_id}/review

Database-independent tests verifying:
1. Authentication & Role-Based Access Control (401, 403).
2. Supervisor ward authorization checks (403 for unassigned wards).
3. JWT-derived identity enforcement (workers can only check out their own attendance).
4. Shift check-out validation, duplicate prevention, and geofence tracking (200, 404, 409, 422).
5. Daily attendance roster queries, date default/filter, summary counts, and N+1 prevention (200).
6. Supervisor exception review lifecycle:
   - Approval of EXCEPTION_PENDING -> PRESENT
   - Rejection of EXCEPTION_PENDING -> REJECTED
   - Mandatory rejection notes validation (422)
   - Rejection of already-resolved records (409)
   - Reviewer identity and timestamp audit trail.
"""

import uuid
import unittest
from datetime import datetime, date, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from geoalchemy2.elements import WKTElement

from app.main import app
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord
from app.api.v1.attendance import (
    check_out_rate_limiter,
    roster_rate_limiter,
    review_rate_limiter,
)
from app.services.attendance_service import (
    get_kolkata_workday_date,
    utc_now,
    AttendanceNotFoundError,
    DuplicateCheckOutError,
    AttendanceNotReviewableError,
)


class TestAttendanceLifecycleAPI(unittest.IsolatedAsyncioTestCase):
    """Database-independent tests for attendance lifecycle endpoints."""

    def setUp(self):
        check_out_rate_limiter.reset()
        roster_rate_limiter.reset()
        review_rate_limiter.reset()

        self.now = datetime.now(timezone.utc)
        self.today = get_kolkata_workday_date(self.now)

        # IDs
        self.admin_id = uuid.uuid4()
        self.supervisor_id = uuid.uuid4()
        self.other_supervisor_id = uuid.uuid4()
        self.worker_id = uuid.uuid4()
        self.other_worker_id = uuid.uuid4()
        self.citizen_id = uuid.uuid4()
        self.ward_id = uuid.uuid4()
        self.other_ward_id = uuid.uuid4()
        self.mp_id = uuid.uuid4()

        # Users
        self.admin_user = User(
            id=self.admin_id,
            email="admin@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.MUNICIPAL_ADMIN.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.supervisor_user = User(
            id=self.supervisor_id,
            email="supervisor@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.WARD_SUPERVISOR.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.other_supervisor_user = User(
            id=self.other_supervisor_id,
            email="other_supervisor@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.WARD_SUPERVISOR.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.worker_user = User(
            id=self.worker_id,
            email="worker@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.other_worker_user = User(
            id=self.other_worker_id,
            email="other_worker@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.citizen_user = User(
            id=self.citizen_id,
            email="citizen@example.com",
            password_hash="mock_hash",
            role=UserRole.CITIZEN.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        # Muster Point (coordinates: 77.6740, 12.9260, radius: 150m)
        self.muster_point = MusterPoint(
            id=self.mp_id,
            ward_id=self.ward_id,
            name="Koramangala Station A",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            geofence_radius_meters=150,
            is_active=True,
            created_at=self.now,
            updated_at=self.now,
        )

        # Ward Assignments
        self.supervisor_assignment = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=self.supervisor_id,
            ward_id=self.ward_id,
            revoked_at=None,
        )
        self.worker_assignment = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=self.worker_id,
            ward_id=self.ward_id,
            revoked_at=None,
        )

        # Existing check-in attendance record for worker
        self.check_in_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=self.today,
            check_in_at=self.now - timedelta(hours=8),
            check_in_distance_meters=25.0,
            status=AttendanceStatus.PRESENT.value,
            created_at=self.now - timedelta(hours=8),
            updated_at=self.now - timedelta(hours=8),
        )
        self.check_in_record.worker = self.worker_user
        self.check_in_record.muster_point = self.muster_point

        # Mock DB session
        self.mock_session = AsyncMock()
        self.mock_session.commit = AsyncMock()
        self.mock_session.rollback = AsyncMock()
        self.mock_session.refresh = AsyncMock()
        self.mock_session.add = MagicMock()
        self.mock_session.flush = AsyncMock()

        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
        nested_cm.__aexit__ = AsyncMock(return_value=None)
        self.mock_session.begin_nested = MagicMock(return_value=nested_cm)

        self.current_mock_user = self.worker_user

        async def _override_get_current_user():
            return self.current_mock_user

        async def _override_get_db():
            yield self.mock_session

        app.dependency_overrides[get_current_user] = _override_get_current_user
        app.dependency_overrides[get_db] = _override_get_db

    def tearDown(self):
        app.dependency_overrides.clear()
        check_out_rate_limiter.reset()
        roster_rate_limiter.reset()
        review_rate_limiter.reset()

    # ==========================================
    # 1. Worker Shift Check-Out Tests
    # ==========================================

    async def test_check_out_unauthenticated_returns_401(self):
        """Unauthenticated request to check-out returns HTTP 401."""
        app.dependency_overrides.pop(get_current_user, None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/check-out",
                json={"latitude": 12.9260, "longitude": 77.6740},
            )
        self.assertEqual(res.status_code, 401)

    async def test_check_out_forbidden_role_returns_403(self):
        """Non-worker (CITIZEN or SUPERVISOR) attempting check-out returns HTTP 403."""
        self.current_mock_user = self.citizen_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/check-out",
                headers={"Authorization": "Bearer mock_token"},
                json={"latitude": 12.9260, "longitude": 77.6740},
            )
        self.assertEqual(res.status_code, 403)

    async def test_check_out_nonexistent_attendance_record_returns_404(self):
        """Worker with no prior check-in on the workday returns HTTP 404."""
        self.current_mock_user = self.worker_user

        # Query for today's record returns None
        res_empty = MagicMock()
        res_empty.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_empty

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/check-out",
                headers={"Authorization": "Bearer mock_token"},
                json={"latitude": 12.9260, "longitude": 77.6740},
            )
        self.assertEqual(res.status_code, 404)
        self.assertIn("No attendance check-in found", res.json()["detail"])

    async def test_check_out_worker_identity_derived_from_jwt(self):
        """Worker identity is strictly derived from the validated JWT; client cannot pass worker_id."""
        self.current_mock_user = self.worker_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Attempting to supply arbitrary worker_id is rejected by Pydantic extra='forbid'
            res = await client.post(
                "/api/v1/attendance/check-out",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "worker_id": str(self.other_worker_id),
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )
        self.assertEqual(res.status_code, 422)

    async def test_check_out_duplicate_attempt_returns_409(self):
        """Attempting check-out when check_out_at is already recorded returns HTTP 409."""
        self.current_mock_user = self.worker_user

        already_checked_out = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=self.today,
            check_in_at=self.now - timedelta(hours=8),
            check_out_at=self.now - timedelta(minutes=10),
            status=AttendanceStatus.PRESENT.value,
        )

        # 1. Endpoint lookup for today_record -> already_checked_out
        res_today = MagicMock()
        res_today.scalars().first.return_value = already_checked_out

        # 2. Service record_check_out lookup -> already_checked_out
        res_att = MagicMock()
        res_att.scalars().first.return_value = already_checked_out

        self.mock_session.execute.side_effect = [res_today, res_att]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/check-out",
                headers={"Authorization": "Bearer mock_token"},
                json={"latitude": 12.9260, "longitude": 77.6740},
            )
        self.assertEqual(res.status_code, 409)
        self.assertIn("already been recorded", res.json()["detail"])

    async def test_check_out_valid_inside_geofence_returns_200(self):
        """Worker checks out within muster point geofence -> 200 OK, PRESENT."""
        self.current_mock_user = self.worker_user

        # 1. Endpoint lookup -> self.check_in_record
        res_today = MagicMock()
        res_today.scalars().first.return_value = self.check_in_record

        # 2. Service lookup -> self.check_in_record
        res_att = MagicMock()
        res_att.scalars().first.return_value = self.check_in_record

        # 3. Worker lookup -> self.worker_user
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker_user

        # 4. Ward assignment lookup -> self.worker_assignment
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.worker_assignment

        # 5. Muster point lookup -> self.muster_point
        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [
            res_today, res_att, res_worker, res_assign, res_mp
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/check-out",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "latitude": 12.9260,  # Exactly at station coordinates
                    "longitude": 77.6740,
                },
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], AttendanceStatus.PRESENT.value)
        self.assertTrue(data["is_within_geofence"])
        self.assertIsNotNone(data["check_out_at"])
        self.assertIn("verified within muster point geofence", data["message"])
        self.mock_session.commit.assert_awaited_once()

    async def test_check_out_valid_outside_geofence_flags_exception_returns_200(self):
        """Worker checks out outside geofence -> 200 OK, status transitions to EXCEPTION_PENDING."""
        self.current_mock_user = self.worker_user

        record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=self.today,
            check_in_at=self.now - timedelta(hours=8),
            status=AttendanceStatus.PRESENT.value,
        )

        res_today = MagicMock()
        res_today.scalars().first.return_value = record
        res_att = MagicMock()
        res_att.scalars().first.return_value = record
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker_user
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.worker_assignment
        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [
            res_today, res_att, res_worker, res_assign, res_mp
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/check-out",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "latitude": 13.0500,  # Far away (> 10 km)
                    "longitude": 77.7500,
                },
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], AttendanceStatus.EXCEPTION_PENDING.value)
        self.assertFalse(data["is_within_geofence"])
        self.assertIn("Check-out outside geofence", data["exception_reason"])
        self.assertIn("Exception logged for supervisor review", data["message"])

    async def test_check_out_invalid_coordinates_returns_422(self):
        """Out-of-range coordinates are rejected with HTTP 422."""
        self.current_mock_user = self.worker_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/check-out",
                headers={"Authorization": "Bearer mock_token"},
                json={"latitude": 95.0, "longitude": 77.6740},
            )
        self.assertEqual(res.status_code, 422)

    # ==========================================
    # 2. Supervisor Daily Attendance Roster Tests
    # ==========================================

    async def test_daily_roster_unauthenticated_returns_401(self):
        """Unauthenticated request to daily roster returns HTTP 401."""
        app.dependency_overrides.pop(get_current_user, None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(f"/api/v1/wards/{self.ward_id}/attendance/daily")
        self.assertEqual(res.status_code, 401)

    async def test_daily_roster_forbidden_role_returns_403(self):
        """Sanitation worker or citizen cannot access daily roster (HTTP 403)."""
        self.current_mock_user = self.worker_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/wards/{self.ward_id}/attendance/daily",
                headers={"Authorization": "Bearer mock_token"},
            )
        self.assertEqual(res.status_code, 403)

    async def test_daily_roster_supervisor_unassigned_ward_returns_403(self):
        """Supervisor cannot view roster for a ward they are not actively assigned to (HTTP 403)."""
        self.current_mock_user = self.other_supervisor_user

        # verify_ward_access checks user_ward_assignments -> returns None
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_assign

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/wards/{self.ward_id}/attendance/daily",
                headers={"Authorization": "Bearer mock_token"},
            )
        self.assertEqual(res.status_code, 403)
        self.assertIn("not assigned as supervisor", res.json()["detail"])

    async def test_daily_roster_authorized_supervisor_returns_200_with_counts(self):
        """Assigned supervisor receives 200 OK with roster records and aggregate counts."""
        self.current_mock_user = self.supervisor_user

        # 1. verify_ward_access -> supervisor_assignment
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.supervisor_assignment

        # 2. get_daily_attendance_roster counts
        counts_row = MagicMock()
        counts_row.total = 2
        counts_row.present = 1
        counts_row.exception_pending = 1
        counts_row.rejected = 0
        res_counts = MagicMock()
        res_counts.first.return_value = counts_row

        # 3. get_daily_attendance_roster records
        record_exc = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.other_worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=self.today,
            check_in_at=self.now - timedelta(hours=7),
            check_in_distance_meters=250.0,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
            exception_reason="Check-in outside geofence: distance 250.0m",
            created_at=self.now - timedelta(hours=7),
            updated_at=self.now - timedelta(hours=7),
        )
        record_exc.worker = self.other_worker_user
        record_exc.muster_point = self.muster_point

        res_records = MagicMock()
        res_records.scalars().unique().all.return_value = [self.check_in_record, record_exc]

        self.mock_session.execute.side_effect = [res_assign, res_counts, res_records]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/wards/{self.ward_id}/attendance/daily?attendance_date={self.today.isoformat()}",
                headers={"Authorization": "Bearer mock_token"},
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["ward_id"], str(self.ward_id))
        self.assertEqual(data["attendance_date"], self.today.isoformat())
        self.assertEqual(data["total_count"], 2)
        self.assertEqual(data["present_count"], 1)
        self.assertEqual(data["exception_pending_count"], 1)
        self.assertEqual(data["rejected_count"], 0)
        self.assertEqual(len(data["records"]), 2)
        self.assertEqual(data["records"][0]["worker_email"], "worker@bbmp.gov.in")
        self.assertEqual(data["records"][1]["status"], AttendanceStatus.EXCEPTION_PENDING.value)

    async def test_daily_roster_authorized_admin_access_any_ward(self):
        """MUNICIPAL_ADMIN bypasses ward assignment and accesses any ward's roster."""
        self.current_mock_user = self.admin_user

        # 1. counts
        counts_row = MagicMock()
        counts_row.total = 0
        counts_row.present = 0
        counts_row.exception_pending = 0
        counts_row.rejected = 0
        res_counts = MagicMock()
        res_counts.first.return_value = counts_row

        # 2. records
        res_records = MagicMock()
        res_records.scalars().unique().all.return_value = []

        self.mock_session.execute.side_effect = [res_counts, res_records]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/wards/{self.ward_id}/attendance/daily",
                headers={"Authorization": "Bearer mock_token"},
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_count"], 0)
        self.assertEqual(len(data["records"]), 0)

    # ==========================================
    # 3. Supervisor Exception Review Tests
    # ==========================================

    async def test_review_unauthenticated_returns_401(self):
        """Unauthenticated review request returns HTTP 401."""
        app.dependency_overrides.pop(get_current_user, None)
        record_id = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                json={"action": "APPROVE"},
            )
        self.assertEqual(res.status_code, 401)

    async def test_review_forbidden_role_returns_403(self):
        """Sanitation worker cannot review attendance exceptions (HTTP 403)."""
        self.current_mock_user = self.worker_user
        record_id = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                headers={"Authorization": "Bearer mock_token"},
                json={"action": "APPROVE"},
            )
        self.assertEqual(res.status_code, 403)

    async def test_review_nonexistent_record_returns_404(self):
        """Reviewing a non-existent attendance record returns HTTP 404."""
        self.current_mock_user = self.supervisor_user
        record_id = uuid.uuid4()

        res_none = MagicMock()
        res_none.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_none

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                headers={"Authorization": "Bearer mock_token"},
                json={"action": "APPROVE"},
            )
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"])

    async def test_review_supervisor_unassigned_ward_returns_403(self):
        """Supervisor reviewing a record for an unassigned ward is rejected with HTTP 403."""
        self.current_mock_user = self.other_supervisor_user
        record_id = uuid.uuid4()

        record = AttendanceRecord(
            id=record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
        )

        # 1. Initial peek query -> record
        res_peek = MagicMock()
        res_peek.scalars().first.return_value = record

        # 2. verify_ward_access -> None (not assigned)
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [res_peek, res_assign]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                headers={"Authorization": "Bearer mock_token"},
                json={"action": "APPROVE"},
            )
        self.assertEqual(res.status_code, 403)
        self.assertIn("not assigned as supervisor", res.json()["detail"])

    async def test_review_already_resolved_record_returns_409(self):
        """Attempting to review a record that is already PRESENT returns HTTP 409 Conflict."""
        self.current_mock_user = self.supervisor_user
        record_id = uuid.uuid4()

        already_resolved = AttendanceRecord(
            id=record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.PRESENT.value,  # Already resolved
        )

        # 1. Initial peek
        res_peek = MagicMock()
        res_peek.scalars().first.return_value = already_resolved

        # 2. verify_ward_access
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.supervisor_assignment

        # 3. service review_attendance_record with_for_update
        res_serv = MagicMock()
        res_serv.scalars().first.return_value = already_resolved

        self.mock_session.execute.side_effect = [res_peek, res_assign, res_serv]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                headers={"Authorization": "Bearer mock_token"},
                json={"action": "APPROVE"},
            )
        self.assertEqual(res.status_code, 409)
        self.assertIn("not in reviewable state", res.json()["detail"])

    async def test_review_approve_transitions_to_present_returns_200(self):
        """Approving an exception record sets status to PRESENT and records reviewer audit trail."""
        self.current_mock_user = self.supervisor_user
        record_id = uuid.uuid4()

        pending_record = AttendanceRecord(
            id=record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
            exception_reason="Check-in outside geofence: distance 180.0m",
        )

        # 1. Initial peek
        res_peek = MagicMock()
        res_peek.scalars().first.return_value = pending_record

        # 2. verify_ward_access
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.supervisor_assignment

        # 3. service review_attendance_record with_for_update
        res_serv = MagicMock()
        res_serv.scalars().first.return_value = pending_record

        self.mock_session.execute.side_effect = [res_peek, res_assign, res_serv]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "action": "APPROVE",
                    "review_notes": "Worker reported signal obstruction at station gate. Verified manually.",
                },
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["previous_status"], AttendanceStatus.EXCEPTION_PENDING.value)
        self.assertEqual(data["new_status"], AttendanceStatus.PRESENT.value)
        self.assertEqual(data["reviewed_by"], str(self.supervisor_id))
        self.assertIsNotNone(data["reviewed_at"])
        self.assertEqual(data["review_notes"], "Worker reported signal obstruction at station gate. Verified manually.")
        self.assertIn("approved", data["message"])
        self.mock_session.commit.assert_awaited_once()

    async def test_review_reject_transitions_to_rejected_returns_200(self):
        """Rejecting an exception record sets status to REJECTED and records justification notes."""
        self.current_mock_user = self.admin_user
        record_id = uuid.uuid4()

        pending_record = AttendanceRecord(
            id=record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
            exception_reason="Check-in outside geofence: distance 1200.0m",
        )

        # 1. Initial peek
        res_peek = MagicMock()
        res_peek.scalars().first.return_value = pending_record

        # 2. Admin access (no ward assignment query needed)

        # 3. service review_attendance_record with_for_update
        res_serv = MagicMock()
        res_serv.scalars().first.return_value = pending_record

        self.mock_session.execute.side_effect = [res_peek, res_serv]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "action": "REJECT",
                    "review_notes": "Telemetry indicated worker was at private residence during shift start.",
                },
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["previous_status"], AttendanceStatus.EXCEPTION_PENDING.value)
        self.assertEqual(data["new_status"], AttendanceStatus.REJECTED.value)
        self.assertEqual(data["reviewed_by"], str(self.admin_id))
        self.assertIn("rejected", data["message"])
        self.mock_session.commit.assert_awaited_once()

    async def test_review_reject_missing_notes_returns_422(self):
        """Rejecting an exception without explanatory notes returns HTTP 422."""
        self.current_mock_user = self.admin_user
        record_id = uuid.uuid4()

        pending_record = AttendanceRecord(
            id=record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
        )

        res_peek = MagicMock()
        res_peek.scalars().first.return_value = pending_record
        self.mock_session.execute.return_value = res_peek

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/attendance/{record_id}/review",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "action": "REJECT",
                    "review_notes": "   ",  # Blank notes rejected
                },
            )
        self.assertEqual(res.status_code, 422)
        self.assertIn("mandatory when rejecting", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
