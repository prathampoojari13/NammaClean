"""
Unit tests for Worker Attendance Email OTP Demonstration & Security Boundaries:
- Verifies development-mode OTP display in API responses.
- Verifies production-mode and staging-mode concealment of OTP code.
- Verifies role-based access restrictions (401 unauthenticated, 403 unauthorized roles).
- Verifies OTP verification, rate limiting, expiry, and attempt bounds.
- Verifies single-use redemption and worker isolation.
"""

import uuid
import unittest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from app.core.config import settings
from app.models.enums import UserRole, UserStatus
from app.models.user import User
from app.schemas.attendance import (
    AttendanceOtpIssueResponse,
    AttendanceOtpVerifyRequest,
    AttendanceOtpVerifyResponse,
)
from app.api.v1.attendance import (
    request_attendance_otp,
    verify_attendance_otp,
)
from app.api.deps import require_roles, _get_auth_exception
from app.services.otp_service import (
    otp_manager,
    RATE_LIMIT_COOLDOWN_SECONDS,
    MAX_VERIFICATION_ATTEMPTS,
)


def run_sync(coro):
    """Executes a coroutine that does not block on external I/O."""
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value


class TestAttendanceOtpDevDemonstration(unittest.TestCase):
    """Verifies development-mode OTP behavior and strict production concealment."""

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.worker_id = uuid.uuid4()
        self.other_worker_id = uuid.uuid4()
        self.citizen_id = uuid.uuid4()
        self.supervisor_id = uuid.uuid4()

        # Users
        self.worker_user = User(
            id=self.worker_id,
            email="worker.yelahanka@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.other_worker_user = User(
            id=self.other_worker_id,
            email="worker2.yelahanka@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.citizen_user = User(
            id=self.citizen_id,
            email="citizen.bengaluru@gmail.com",
            password_hash="mock_hash",
            role=UserRole.CITIZEN.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        self.supervisor_user = User(
            id=self.supervisor_id,
            email="supervisor.yelahanka@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.WARD_SUPERVISOR.value,
            status=UserStatus.ACTIVE.value,
            created_at=self.now,
            updated_at=self.now,
        )

        # Clear in-memory OTP manager states
        otp_manager._challenges.clear()
        otp_manager._last_requested_at.clear()

        # Store baseline settings
        self.original_env = settings.APP_ENV
        self.original_debug = settings.APP_DEBUG
        settings.APP_ENV = "development"
        settings.APP_DEBUG = True

    def tearDown(self):
        settings.APP_ENV = self.original_env
        settings.APP_DEBUG = self.original_debug
        otp_manager._challenges.clear()
        otp_manager._last_requested_at.clear()

    def test_dev_mode_otp_returned_to_worker(self):
        """In local development mode, dev_otp is populated with a 6-digit code."""
        settings.APP_ENV = "development"
        settings.APP_DEBUG = True

        res = run_sync(request_attendance_otp(current_user=self.worker_user))
        self.assertIsInstance(res, AttendanceOtpIssueResponse)
        self.assertIsNotNone(res.challenge_id)
        self.assertIsNotNone(res.dev_otp)
        self.assertEqual(len(res.dev_otp), 6)
        self.assertTrue(res.dev_otp.isdigit())
        self.assertEqual(res.worker_email, "worker.yelahanka@bbmp.gov.in")
        self.assertEqual(res.expires_in_seconds, 300)

    def test_production_mode_otp_concealed(self):
        """In production environment, dev_otp MUST be None / null."""
        settings.APP_ENV = "production"
        settings.APP_DEBUG = False

        res = run_sync(request_attendance_otp(current_user=self.worker_user))
        self.assertIsInstance(res, AttendanceOtpIssueResponse)
        self.assertIsNotNone(res.challenge_id)
        self.assertIsNone(res.dev_otp, "dev_otp MUST be None in production")

    def test_staging_mode_otp_concealed(self):
        """In staging environment, dev_otp MUST be None / null."""
        settings.APP_ENV = "staging"
        settings.APP_DEBUG = True

        res = run_sync(request_attendance_otp(current_user=self.worker_user))
        self.assertIsInstance(res, AttendanceOtpIssueResponse)
        self.assertIsNotNone(res.challenge_id)
        self.assertIsNone(res.dev_otp, "dev_otp MUST be None in staging")

    def test_production_mode_with_debug_flag_still_concealed(self):
        """If APP_ENV is production, dev_otp remains None even if APP_DEBUG is accidentally True."""
        settings.APP_ENV = "production"
        settings.APP_DEBUG = True

        res = run_sync(request_attendance_otp(current_user=self.worker_user))
        self.assertIsNone(res.dev_otp, "Production environment must never expose dev_otp regardless of debug flag")

    def test_role_authorization_rejection(self):
        """Only SANITATION_WORKER role is authorized for worker attendance."""
        role_dep = require_roles(UserRole.SANITATION_WORKER)

        # 1. Citizen -> 403 Forbidden
        with self.assertRaises(HTTPException) as ctx:
            run_sync(role_dep(current_user=self.citizen_user))
        self.assertEqual(ctx.exception.status_code, 403)

        # 2. Supervisor -> 403 Forbidden
        with self.assertRaises(HTTPException) as ctx:
            run_sync(role_dep(current_user=self.supervisor_user))
        self.assertEqual(ctx.exception.status_code, 403)

        # 3. Sanitation Worker -> Success
        authorized_user = run_sync(role_dep(current_user=self.worker_user))
        self.assertEqual(authorized_user.id, self.worker_id)

    def test_otp_rate_limiting_cooldown(self):
        """Requesting an OTP within the 30-second cooldown period returns HTTP 429."""
        # First request succeeds
        res1 = run_sync(request_attendance_otp(current_user=self.worker_user))
        self.assertIsNotNone(res1.challenge_id)

        # Immediate second request fails with 429
        with self.assertRaises(HTTPException) as ctx:
            run_sync(request_attendance_otp(current_user=self.worker_user))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("seconds before requesting a new verification code", ctx.exception.detail)

    def test_successful_otp_verification(self):
        """Worker can verify the issued dev_otp successfully."""
        issue_res = run_sync(request_attendance_otp(current_user=self.worker_user))
        raw_code = issue_res.dev_otp

        req = AttendanceOtpVerifyRequest(challenge_id=issue_res.challenge_id, otp=raw_code)
        verify_res = run_sync(verify_attendance_otp(payload=req, current_user=self.worker_user))
        self.assertIsInstance(verify_res, AttendanceOtpVerifyResponse)
        self.assertTrue(verify_res.verified)

    def test_incorrect_otp_attempt_limits_and_lockout(self):
        """Incorrect OTP code tracks remaining attempts and locks out after 3 tries."""
        issue_res = run_sync(request_attendance_otp(current_user=self.worker_user))
        cid = issue_res.challenge_id

        # Attempt 1: wrong code -> 400 with 2 remaining
        with self.assertRaises(HTTPException) as ctx1:
            run_sync(verify_attendance_otp(
                payload=AttendanceOtpVerifyRequest(challenge_id=cid, otp="000000"),
                current_user=self.worker_user,
            ))
        self.assertEqual(ctx1.exception.status_code, 400)
        self.assertIn("2 attempt(s) remaining", ctx1.exception.detail)

        # Attempt 2: wrong code -> 400 with 1 remaining
        with self.assertRaises(HTTPException) as ctx2:
            run_sync(verify_attendance_otp(
                payload=AttendanceOtpVerifyRequest(challenge_id=cid, otp="000001"),
                current_user=self.worker_user,
            ))
        self.assertEqual(ctx2.exception.status_code, 400)
        self.assertIn("1 attempt(s) remaining", ctx2.exception.detail)

        # Attempt 3: wrong code -> 400 with Maximum attempts exceeded
        with self.assertRaises(HTTPException) as ctx3:
            run_sync(verify_attendance_otp(
                payload=AttendanceOtpVerifyRequest(challenge_id=cid, otp="000002"),
                current_user=self.worker_user,
            ))
        self.assertEqual(ctx3.exception.status_code, 400)
        self.assertIn("Maximum attempts exceeded", ctx3.exception.detail)

        # Attempt 4: Even correct code is locked out
        with self.assertRaises(HTTPException) as ctx4:
            run_sync(verify_attendance_otp(
                payload=AttendanceOtpVerifyRequest(challenge_id=cid, otp=issue_res.dev_otp),
                current_user=self.worker_user,
            ))
        self.assertEqual(ctx4.exception.status_code, 400)
        self.assertIn("Maximum verification attempts exceeded", ctx4.exception.detail)

    def test_otp_expiration_enforcement(self):
        """Expired challenge cannot be verified."""
        issue_res = run_sync(request_attendance_otp(current_user=self.worker_user))
        cid = issue_res.challenge_id

        # Manually expire the challenge in memory
        ch = otp_manager._challenges[cid]
        ch.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        with self.assertRaises(HTTPException) as ctx:
            run_sync(verify_attendance_otp(
                payload=AttendanceOtpVerifyRequest(challenge_id=cid, otp=issue_res.dev_otp),
                current_user=self.worker_user,
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("expired", ctx.exception.detail.lower())

    def test_challenge_worker_isolation(self):
        """A worker cannot verify a challenge issued to another worker."""
        issue_res = run_sync(request_attendance_otp(current_user=self.worker_user))
        cid = issue_res.challenge_id

        with self.assertRaises(HTTPException) as ctx:
            run_sync(verify_attendance_otp(
                payload=AttendanceOtpVerifyRequest(challenge_id=cid, otp=issue_res.dev_otp),
                current_user=self.other_worker_user,
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("belongs to another worker account", ctx.exception.detail)

    def test_single_use_redemption(self):
        """Challenge cannot be redeemed twice."""
        issue_res = run_sync(request_attendance_otp(current_user=self.worker_user))
        cid = issue_res.challenge_id

        # Verify first
        req = AttendanceOtpVerifyRequest(challenge_id=cid, otp=issue_res.dev_otp)
        v_res = run_sync(verify_attendance_otp(payload=req, current_user=self.worker_user))
        self.assertTrue(v_res.verified)

        # First redemption succeeds
        redeemed1 = otp_manager.validate_and_redeem(cid, self.worker_id)
        self.assertTrue(redeemed1)

        # Second redemption fails
        redeemed2 = otp_manager.validate_and_redeem(cid, self.worker_id)
        self.assertFalse(redeemed2, "A redeemed challenge cannot be redeemed a second time")


if __name__ == "__main__":
    unittest.main()
