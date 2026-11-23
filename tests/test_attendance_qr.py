"""
Unit tests for QR-based Pourakarmika Attendance Milestone:
- POST /api/v1/wards/{ward_id}/muster-points/{muster_point_id}/qr-code
- POST /api/v1/attendance/qr-check-in

Database-independent unit tests verifying:
1. Authorized QR issuance by MUNICIPAL_ADMIN and assigned WARD_SUPERVISOR (HTTP 201, 5-minute expiry).
2. Unauthorized issuance by WARD_SUPERVISOR for an unassigned ward (HTTP 403).
3. Unauthorized issuance by CITIZEN or SANITATION_WORKER (HTTP 403).
4. Inactive muster point issuance rejection (HTTP 400).
5. Missing ward or muster point rejection (HTTP 404).
6. Successful single-use redemption by SANITATION_WORKER inside geofence (PRESENT).
7. Successful single-use redemption by SANITATION_WORKER outside geofence (EXCEPTION_PENDING).
8. Expired token rejection (HTTP 400, older than 5 minutes).
9. Invalid / unrecognized token rejection (HTTP 400).
10. Replay prevention: reusing an already redeemed token is rejected with HTTP 409 Conflict.
11. Cross-ward rejection: worker not actively assigned to muster point's ward is rejected with HTTP 403.
12. Inactive worker account rejection (HTTP 403).
13. Duplicate daily attendance rejection (HTTP 409).
14. Consistency: failed check-in leaves token unredeemed.
15. Authoritative server clock: expired token with backdated device_timestamp is rejected.
16. Authoritative server clock: expiry boundary tests (1s before vs 1s after expiry).
17. Authoritative server clock: check_in_at and redeemed_at derived strictly from server time, ignoring device_timestamp.
"""

import math
import uuid
import unittest
from datetime import datetime, date, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from geoalchemy2.elements import WKTElement

from app.main import app
from app.core.database import get_db
from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord, AttendanceQrToken
from app.services.attendance_service import (
    hash_qr_token,
    get_kolkata_workday_date,
    generate_qr_token,
    redeem_qr_attendance,
    InvalidQrTokenError,
    ExpiredQrTokenError,
    QrTokenAlreadyRedeemedError,
)
from app.api.v1.attendance import qr_issue_rate_limiter, qr_check_in_rate_limiter


class TestAttendanceQrAPI(unittest.IsolatedAsyncioTestCase):
    """Database-independent tests for QR issuance and redemption APIs."""

    def setUp(self):
        qr_issue_rate_limiter.reset()
        qr_check_in_rate_limiter.reset()

        self.admin_id = uuid.uuid4()
        self.supervisor_id = uuid.uuid4()
        self.worker_id = uuid.uuid4()
        self.citizen_id = uuid.uuid4()
        self.ward_id = uuid.uuid4()
        self.other_ward_id = uuid.uuid4()
        self.mp_id = uuid.uuid4()

        now = datetime.now(timezone.utc)

        # Users
        self.admin_user = User(
            id=self.admin_id,
            email="admin@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.MUNICIPAL_ADMIN.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        self.supervisor_user = User(
            id=self.supervisor_id,
            email="supervisor@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.WARD_SUPERVISOR.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        self.worker_user = User(
            id=self.worker_id,
            email="worker@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        self.citizen_user = User(
            id=self.citizen_id,
            email="citizen@example.com",
            password_hash="mock_hash",
            role=UserRole.CITIZEN.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        # Ward
        self.ward = Ward(
            id=self.ward_id,
            ward_code="WARD-150",
            display_name="Bellandur",
            boundary=None,
        )

        # Active Muster Point (Bellandur: lat 12.9260, lon 77.6740, radius 150m)
        self.muster_point = MusterPoint(
            id=self.mp_id,
            ward_id=self.ward_id,
            name="Bellandur Gate Muster Station",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            geofence_radius_meters=150,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        # Inactive Muster Point
        self.inactive_mp_id = uuid.uuid4()
        self.inactive_muster_point = MusterPoint(
            id=self.inactive_mp_id,
            ward_id=self.ward_id,
            name="Decommissioned Station",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            geofence_radius_meters=150,
            is_active=False,
            created_at=now,
            updated_at=now,
        )

        # Supervisor active ward assignment
        self.supervisor_assignment = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=self.supervisor_id,
            ward_id=self.ward_id,
            revoked_at=None,
        )

        # Worker active ward assignment
        self.worker_assignment = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=self.worker_id,
            ward_id=self.ward_id,
            revoked_at=None,
        )

        # Tokens
        self.raw_qr_token = f"nmc_qr_{uuid.uuid4().hex}"
        self.token_hash = hash_qr_token(self.raw_qr_token)

        self.qr_record = AttendanceQrToken(
            id=uuid.uuid4(),
            token_hash=self.token_hash,
            muster_point_id=self.mp_id,
            ward_id=self.ward_id,
            issued_by=self.supervisor_id,
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            redeemed_at=None,
            redeemed_by=None,
            attendance_record_id=None,
            created_at=now,
            updated_at=now,
        )

        # Mock DB session
        self.mock_session = AsyncMock()
        self.mock_session.commit = AsyncMock()
        self.mock_session.rollback = AsyncMock()
        self.mock_session.refresh = AsyncMock()
        self.mock_session.add = MagicMock()
        self.mock_session.flush = AsyncMock()

        # Mock begin_nested() context manager for savepoints
        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
        nested_cm.__aexit__ = AsyncMock(return_value=None)
        self.mock_session.begin_nested = MagicMock(return_value=nested_cm)

        # Auth setup
        self.current_mock_user = self.admin_user

        async def _override_get_current_user():
            return self.current_mock_user

        async def _override_get_db():
            yield self.mock_session

        app.dependency_overrides[get_current_user] = _override_get_current_user
        app.dependency_overrides[get_db] = _override_get_db

    def tearDown(self):
        app.dependency_overrides.clear()
        qr_issue_rate_limiter.reset()
        qr_check_in_rate_limiter.reset()

    # --- Phase 1: Issuance Tests ---

    async def test_issue_qr_token_authorized_admin(self):
        """MUNICIPAL_ADMIN can issue a roll-call QR token valid for 5 minutes."""
        self.current_mock_user = self.admin_user

        # 1. verify_ward_access (admin passes directly)
        # 2. generate_qr_token -> select MusterPoint
        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point
        self.mock_session.execute.return_value = res_mp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points/{self.mp_id}/qr-code",
                headers={"Authorization": "Bearer mock_token"},
            )

        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertTrue(data["token"].startswith("nmc_qr_"))
        self.assertEqual(data["muster_point_id"], str(self.mp_id))
        self.assertEqual(data["ward_id"], str(self.ward_id))
        self.assertEqual(data["expires_in_seconds"], 300)
        self.mock_session.commit.assert_awaited_once()

    async def test_issue_qr_token_authorized_supervisor(self):
        """Assigned WARD_SUPERVISOR can issue a QR token for their assigned ward."""
        self.current_mock_user = self.supervisor_user

        # 1. verify_ward_access -> checks assignment
        res_assign1 = MagicMock()
        res_assign1.scalars().first.return_value = self.supervisor_assignment

        # 2. generate_qr_token -> checks assignment
        res_assign2 = MagicMock()
        res_assign2.scalars().first.return_value = self.supervisor_assignment

        # 3. generate_qr_token -> checks muster point
        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [res_assign1, res_assign2, res_mp]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points/{self.mp_id}/qr-code",
                headers={"Authorization": "Bearer mock_token"},
            )

        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertTrue(data["token"].startswith("nmc_qr_"))

    async def test_issue_qr_token_cross_ward_supervisor_denied(self):
        """WARD_SUPERVISOR cannot issue QR token for an unassigned ward (HTTP 403)."""
        self.current_mock_user = self.supervisor_user

        # Assignment query returns None
        res_no_assign = MagicMock()
        res_no_assign.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_no_assign

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.other_ward_id}/muster-points/{self.mp_id}/qr-code",
                headers={"Authorization": "Bearer mock_token"},
            )

        self.assertEqual(res.status_code, 403)
        self.assertIn("not actively assigned to this ward", res.json()["detail"])

    async def test_issue_qr_token_unauthorized_role_denied(self):
        """Sanitation worker or citizen cannot issue QR tokens (HTTP 403)."""
        self.current_mock_user = self.worker_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points/{self.mp_id}/qr-code",
                headers={"Authorization": "Bearer mock_token"},
            )

        self.assertEqual(res.status_code, 403)
        self.assertIn("Insufficient permissions", res.json()["detail"])

    async def test_issue_qr_token_inactive_muster_point(self):
        """Cannot issue QR token for an inactive muster point (HTTP 400)."""
        self.current_mock_user = self.admin_user

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.inactive_muster_point
        self.mock_session.execute.return_value = res_mp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points/{self.inactive_mp_id}/qr-code",
                headers={"Authorization": "Bearer mock_token"},
            )

        self.assertEqual(res.status_code, 400)
        self.assertIn("is inactive", res.json()["detail"])

    async def test_issue_qr_token_missing_muster_point(self):
        """Cannot issue QR token for non-existent muster point (HTTP 404)."""
        self.current_mock_user = self.admin_user

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_mp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points/{uuid.uuid4()}/qr-code",
                headers={"Authorization": "Bearer mock_token"},
            )

        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"])

    # --- Phase 2: Redemption Tests ---

    async def test_redeem_qr_check_in_success_inside_geofence(self):
        """Sanitation worker redeems active QR token inside geofence -> PRESENT."""
        self.current_mock_user = self.worker_user

        # 1. Lookup QR token (AttendanceQrToken)
        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record

        # 2. Check muster point active
        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        # 3. record_check_in -> worker lookup
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker_user

        # 4. record_check_in -> worker ward assignment lookup
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.worker_assignment

        # 5. record_check_in -> muster point lookup
        res_mp2 = MagicMock()
        res_mp2.scalars().first.return_value = self.muster_point

        # 6. record_check_in -> daily attendance lookup (None)
        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [
            res_token, res_mp, res_worker, res_assign, res_mp2, res_att
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6741,  # ~11 meters away, inside 150m geofence
                },
            )

        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], AttendanceStatus.PRESENT.value)
        self.assertTrue(data["is_within_geofence"])
        self.assertIsNone(data["exception_reason"])
        self.assertLess(data["distance_meters"], 150.0)
        self.assertIn("within muster point geofence", data["message"])

        # Assert token is marked as redeemed
        self.assertIsNotNone(self.qr_record.redeemed_at)
        self.assertEqual(self.qr_record.redeemed_by, self.worker_id)
        self.mock_session.commit.assert_awaited_once()

    async def test_redeem_qr_check_in_outside_geofence_flags_exception(self):
        """Sanitation worker redeems active QR token outside geofence -> EXCEPTION_PENDING."""
        self.current_mock_user = self.worker_user

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker_user

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.worker_assignment

        res_mp2 = MagicMock()
        res_mp2.scalars().first.return_value = self.muster_point

        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [
            res_token, res_mp, res_worker, res_assign, res_mp2, res_att
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6768,  # ~303 meters away, outside 150m geofence
                },
            )

        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], AttendanceStatus.EXCEPTION_PENDING.value)
        self.assertFalse(data["is_within_geofence"])
        self.assertIn("Check-in outside geofence", data["exception_reason"])
        self.assertGreater(data["distance_meters"], 150.0)

    async def test_redeem_qr_check_in_expired_token(self):
        """Scanning a token older than 5 minutes is rejected with HTTP 400."""
        self.current_mock_user = self.worker_user

        # Expired token (issued 10 minutes ago, expired 5 minutes ago)
        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        self.qr_record.issued_at = past
        self.qr_record.expires_at = past + timedelta(minutes=5)

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record
        self.mock_session.execute.return_value = res_token

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 400)
        self.assertIn("has expired", res.json()["detail"])
        self.mock_session.commit.assert_not_called()

    async def test_redeem_qr_check_in_invalid_token(self):
        """Submitting non-existent QR token returns HTTP 400."""
        self.current_mock_user = self.worker_user

        res_token = MagicMock()
        res_token.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_token

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": "nmc_qr_fake_invalid_token_12345",
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid or unrecognized", res.json()["detail"])

    async def test_redeem_qr_check_in_already_redeemed_replay_prevented(self):
        """Single-use replay prevention: token already redeemed is rejected with HTTP 409 Conflict."""
        self.current_mock_user = self.worker_user

        # Mark token as already redeemed earlier
        self.qr_record.redeemed_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.qr_record.redeemed_by = uuid.uuid4()

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record
        self.mock_session.execute.return_value = res_token

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 409)
        self.assertIn("already been redeemed", res.json()["detail"])
        self.mock_session.commit.assert_not_called()

    async def test_redeem_qr_check_in_worker_not_assigned_to_ward(self):
        """Worker attempting redemption in a ward they are not assigned to is rejected with HTTP 403."""
        self.current_mock_user = self.worker_user

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker_user

        # No active ward assignment
        res_no_assign = MagicMock()
        res_no_assign.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [res_token, res_mp, res_worker, res_no_assign]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 403)
        self.assertIn("not actively assigned to ward", res.json()["detail"])
        # Crucial: token was NOT marked as redeemed
        self.assertIsNone(self.qr_record.redeemed_at)

    async def test_redeem_qr_check_in_duplicate_attendance_attempt(self):
        """Worker attempting second check-in on same workday is rejected with HTTP 409."""
        self.current_mock_user = self.worker_user

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker_user

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.worker_assignment

        res_mp2 = MagicMock()
        res_mp2.scalars().first.return_value = self.muster_point

        # Existing daily attendance record already present
        now = datetime.now(timezone.utc)
        existing_att = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=get_kolkata_workday_date(now),
            check_in_at=now,
            status=AttendanceStatus.PRESENT.value,
        )
        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_att

        self.mock_session.execute.side_effect = [
            res_token, res_mp, res_worker, res_assign, res_mp2, res_att
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 409)
        self.assertIn("already has an attendance record", res.json()["detail"])
        # Token must NOT be marked as redeemed when attendance recording fails
        self.assertIsNone(self.qr_record.redeemed_at)

    async def test_redeem_qr_check_in_inactive_worker_rejected(self):
        """Disabled worker account is rejected with HTTP 403."""
        disabled_worker = User(
            id=self.worker_id,
            email="disabled@bbmp.gov.in",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.DISABLED.value,
        )
        self.current_mock_user = disabled_worker

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = disabled_worker

        self.mock_session.execute.side_effect = [res_token, res_mp, res_worker]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 403)
        self.assertIn("not active", res.json()["detail"])
        self.assertIsNone(self.qr_record.redeemed_at)

    async def test_redeem_qr_check_in_expired_token_with_backdated_device_timestamp(self):
        """
        Security verification: An expired token submitted with a backdated client device_timestamp
        MUST be rejected by the authoritative server clock (HTTP 400).
        """
        self.current_mock_user = self.worker_user

        issue_time = datetime(2026, 11, 1, 9, 0, 0, tzinfo=timezone.utc)
        expiry_time = issue_time + timedelta(minutes=5)  # 09:05:00 UTC
        server_current_time = issue_time + timedelta(minutes=6)  # 09:06:00 UTC (expired!)

        self.qr_record.issued_at = issue_time
        self.qr_record.expires_at = expiry_time
        self.qr_record.redeemed_at = None

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record
        self.mock_session.execute.return_value = res_token

        transport = ASGITransport(app=app)
        with patch("app.services.attendance_service.utc_now", return_value=server_current_time):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post(
                    "/api/v1/attendance/qr-check-in",
                    headers={"Authorization": "Bearer mock_token"},
                    json={
                        "qr_token": self.raw_qr_token,
                        "latitude": 12.9260,
                        "longitude": 77.6740,
                        "device_timestamp": (issue_time + timedelta(minutes=2)).isoformat(),  # 09:02:00 UTC (backdated claim)
                    },
                )

        self.assertEqual(res.status_code, 400)
        self.assertIn("has expired", res.json()["detail"])
        self.assertIsNone(self.qr_record.redeemed_at)
        self.mock_session.commit.assert_not_called()

    async def test_redeem_qr_check_in_expiry_boundaries_before_and_after(self):
        """
        Boundary verification:
        - 1 second before expiry (09:04:59) -> Valid, accepted with HTTP 201.
        - 1 second after expiry (09:05:01) -> Expired, rejected with HTTP 400.
        """
        self.current_mock_user = self.worker_user
        issue_time = datetime(2026, 11, 1, 9, 0, 0, tzinfo=timezone.utc)
        expiry_time = issue_time + timedelta(minutes=5)  # 09:05:00 UTC

        self.qr_record.issued_at = issue_time
        self.qr_record.expires_at = expiry_time
        self.qr_record.redeemed_at = None

        # Case 1: 1 second before expiry (09:04:59 UTC) -> Succeeds
        time_before = expiry_time - timedelta(seconds=1)
        res_token1 = MagicMock()
        res_token1.scalars().first.return_value = self.qr_record
        res_mp1 = MagicMock()
        res_mp1.scalars().first.return_value = self.muster_point
        res_worker1 = MagicMock()
        res_worker1.scalars().first.return_value = self.worker_user
        res_assign1 = MagicMock()
        res_assign1.scalars().first.return_value = self.worker_assignment
        res_mp2 = MagicMock()
        res_mp2.scalars().first.return_value = self.muster_point
        res_att1 = MagicMock()
        res_att1.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [
            res_token1, res_mp1, res_worker1, res_assign1, res_mp2, res_att1
        ]

        transport = ASGITransport(app=app)
        with patch("app.services.attendance_service.utc_now", return_value=time_before):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res_ok = await client.post(
                    "/api/v1/attendance/qr-check-in",
                    headers={"Authorization": "Bearer mock_token"},
                    json={
                        "qr_token": self.raw_qr_token,
                        "latitude": 12.9260,
                        "longitude": 77.6740,
                    },
                )
        self.assertEqual(res_ok.status_code, 201)
        self.assertEqual(self.qr_record.redeemed_at, time_before)

        # Reset token for Case 2
        self.qr_record.redeemed_at = None
        self.mock_session.commit.reset_mock()

        # Case 2: 1 second after expiry (09:05:01 UTC) -> Fails with HTTP 400
        time_after = expiry_time + timedelta(seconds=1)
        res_token2 = MagicMock()
        res_token2.scalars().first.return_value = self.qr_record
        self.mock_session.execute.side_effect = None
        self.mock_session.execute.return_value = res_token2

        with patch("app.services.attendance_service.utc_now", return_value=time_after):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res_exp = await client.post(
                    "/api/v1/attendance/qr-check-in",
                    headers={"Authorization": "Bearer mock_token"},
                    json={
                        "qr_token": self.raw_qr_token,
                        "latitude": 12.9260,
                        "longitude": 77.6740,
                    },
                )
        self.assertEqual(res_exp.status_code, 400)
        self.assertIn("has expired", res_exp.json()["detail"])
        self.assertIsNone(self.qr_record.redeemed_at)
        self.mock_session.commit.assert_not_called()

    async def test_redeem_qr_check_in_official_timestamp_derived_from_server_clock_not_device_timestamp(self):
        """
        Integrity verification: The official check_in_at on the AttendanceRecord and redeemed_at
        on the AttendanceQrToken are strictly derived from authoritative server time (utc_now()),
        completely ignoring any client-provided device_timestamp.
        """
        self.current_mock_user = self.worker_user

        issue_time = datetime(2026, 11, 1, 9, 0, 0, tzinfo=timezone.utc)
        server_scan_time = datetime(2026, 11, 1, 9, 2, 30, tzinfo=timezone.utc)
        spoofed_device_time = datetime(2026, 11, 1, 6, 30, 0, tzinfo=timezone.utc)

        self.qr_record.issued_at = issue_time
        self.qr_record.expires_at = issue_time + timedelta(minutes=5)
        self.qr_record.redeemed_at = None

        res_token = MagicMock()
        res_token.scalars().first.return_value = self.qr_record
        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker_user
        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.worker_assignment
        res_mp2 = MagicMock()
        res_mp2.scalars().first.return_value = self.muster_point
        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [
            res_token, res_mp, res_worker, res_assign, res_mp2, res_att
        ]

        # Track what record was added to session
        added_objects = []
        def capture_add(obj):
            added_objects.append(obj)
        self.mock_session.add.side_effect = capture_add

        transport = ASGITransport(app=app)
        with patch("app.services.attendance_service.utc_now", return_value=server_scan_time):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post(
                    "/api/v1/attendance/qr-check-in",
                    headers={"Authorization": "Bearer mock_token"},
                    json={
                        "qr_token": self.raw_qr_token,
                        "latitude": 12.9260,
                        "longitude": 77.6740,
                        "device_timestamp": spoofed_device_time.isoformat(),
                    },
                )

        self.assertEqual(res.status_code, 201)
        data = res.json()

        # Check response timestamp is server time, NOT spoofed device time
        self.assertEqual(datetime.fromisoformat(data["check_in_at"]), server_scan_time)

        # Check added AttendanceRecord has check_in_at equal to server time
        created_records = [obj for obj in added_objects if isinstance(obj, AttendanceRecord)]
        self.assertEqual(len(created_records), 1)
        self.assertEqual(created_records[0].check_in_at, server_scan_time)
        self.assertNotEqual(created_records[0].check_in_at, spoofed_device_time)

        # Check QR token redeemed_at and updated_at are set to server time
        self.assertEqual(self.qr_record.redeemed_at, server_scan_time)
        self.assertEqual(self.qr_record.updated_at, server_scan_time)
        self.assertNotEqual(self.qr_record.redeemed_at, spoofed_device_time)

    # --- Phase 4: Security, Validation, and Rate Limiting Tests ---

    async def test_issue_qr_token_unauthenticated_returns_401(self):
        """Unauthenticated request to QR issuance endpoint returns HTTP 401 Unauthorized."""
        app.dependency_overrides.pop(get_current_user, None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points/{self.mp_id}/qr-code"
            )
        self.assertEqual(res.status_code, 401)
        self.assertIn("WWW-Authenticate", res.headers)

    async def test_redeem_qr_check_in_unauthenticated_returns_401(self):
        """Unauthenticated request to QR check-in endpoint returns HTTP 401 Unauthorized."""
        app.dependency_overrides.pop(get_current_user, None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )
        self.assertEqual(res.status_code, 401)
        self.assertIn("WWW-Authenticate", res.headers)

    async def test_redeem_qr_check_in_invalid_coordinates_returns_422(self):
        """Check-in request with out-of-range coordinates is rejected with HTTP 422 Unprocessable Entity."""
        self.current_mock_user = self.worker_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 95.0,  # Invalid latitude (> 90.0)
                    "longitude": 77.6740,
                },
            )
        self.assertEqual(res.status_code, 422)

    async def test_issue_qr_token_rate_limiting_returns_429(self):
        """Exceeding QR issuance rate limit (30 req/min) returns HTTP 429 Too Many Requests."""
        self.current_mock_user = self.admin_user

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point
        self.mock_session.execute.return_value = res_mp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 30 allowed requests
            for _ in range(30):
                res = await client.post(
                    f"/api/v1/wards/{self.ward_id}/muster-points/{self.mp_id}/qr-code",
                    headers={"Authorization": "Bearer mock_token"},
                )
                self.assertEqual(res.status_code, 201)

            # 31st request should be rate limited
            res_429 = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points/{self.mp_id}/qr-code",
                headers={"Authorization": "Bearer mock_token"},
            )
            self.assertEqual(res_429.status_code, 429)
            self.assertIn("Retry-After", res_429.headers)

    async def test_redeem_qr_check_in_rate_limiting_returns_429(self):
        """Exceeding QR check-in rate limit (15 req/min) returns HTTP 429 Too Many Requests."""
        self.current_mock_user = self.worker_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Send 15 invalid payloads (which still hit the rate limiter)
            for _ in range(15):
                await client.post(
                    "/api/v1/attendance/qr-check-in",
                    headers={"Authorization": "Bearer mock_token"},
                    json={
                        "qr_token": "too_short",
                        "latitude": 12.9260,
                        "longitude": 77.6740,
                    },
                )

            # 16th request triggers rate limit 429 before any payload/db processing
            res_429 = await client.post(
                "/api/v1/attendance/qr-check-in",
                headers={"Authorization": "Bearer mock_token"},
                json={
                    "qr_token": self.raw_qr_token,
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )
            self.assertEqual(res_429.status_code, 429)
            self.assertIn("Retry-After", res_429.headers)


if __name__ == "__main__":
    unittest.main()


