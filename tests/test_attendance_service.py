"""
Unit tests for the Foundational Attendance Service for Pourakarmikas.

Database-independent tests verifying:
1. Asia/Kolkata workday date calculation.
2. Haversine great-circle distance calculation.
3. Coordinate validation (WGS 84 bounds).
4. Geofence proximity calculation and PostGIS coordinate order.
5. Check-in eligibility validation:
   - Active sanitation worker role and status
   - Active ward assignment
   - Muster point existence, active status, and ward association
   - Workday uniqueness
6. Check-in recording:
   - Inside geofence -> PRESENT
   - Outside geofence -> EXCEPTION_PENDING
   - Geometry storage with POINT(longitude latitude) SRID 4326
   - Atomic savepoint flush and concurrent duplicate handling
7. Check-out recording:
   - Check-out without prior check-in (AttendanceNotFoundError)
   - Duplicate check-out (DuplicateCheckOutError)
   - Timestamp earlier than check-in (InvalidAttendanceTimeError)
   - Exception status preservation (EXCEPTION_PENDING is not erased)
   - Transition to EXCEPTION_PENDING when check-out breaches geofence
"""

import math
import uuid
import unittest
from datetime import datetime, date, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape

from app.models.enums import UserRole, UserStatus, AttendanceStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint, AttendanceRecord
from app.services.attendance_service import (
    normalize_to_utc,
    get_kolkata_workday_date,
    validate_coordinates,
    calculate_haversine_distance_meters,
    extract_point_coordinates,
    validate_gps_proximity,
    validate_check_in_eligibility,
    record_check_in,
    record_check_out,
    review_attendance_record,
    get_daily_attendance_roster,
    AttendanceServiceError,
    WorkerIneligibleError,
    WardAssignmentError,
    MusterPointError,
    DuplicateAttendanceError,
    AttendanceNotFoundError,
    DuplicateCheckOutError,
    MissingCheckInError,
    AttendanceNotReviewableError,
    InvalidCoordinateError,
    InvalidAttendanceTimeError,
)


class TestAttendanceTimeAndGeospatialUtils(unittest.TestCase):
    """Tests for pure utility functions: timezones, distances, and geometries."""

    def test_asia_kolkata_workday_date_boundary(self):
        """
        Verify that late-night UTC timestamps evaluate to the next morning's date
        in Indian Standard Time (UTC+05:30).
        """
        # 23:45 UTC on Oct 31 is 05:15 IST on Nov 01
        dt_utc = datetime(2026, 10, 31, 23, 45, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(dt_utc)
        self.assertEqual(workday, date(2026, 11, 1))

        # 01:00 UTC on Nov 01 is 06:30 IST on Nov 01
        dt_morning_utc = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(get_kolkata_workday_date(dt_morning_utc), date(2026, 11, 1))

    def test_asia_kolkata_workday_date_naive_assumed_utc(self):
        """Verify naive datetime defaults to UTC before converting to Asia/Kolkata."""
        naive_dt = datetime(2026, 10, 31, 23, 30)
        self.assertEqual(get_kolkata_workday_date(naive_dt), date(2026, 11, 1))

    def test_normalize_to_utc(self):
        """Verify datetime normalization to UTC."""
        # None returns current UTC time
        now_norm = normalize_to_utc(None)
        self.assertEqual(now_norm.tzinfo, timezone.utc)

        # Naive datetime is interpreted as UTC
        naive_dt = datetime(2026, 11, 1, 8, 30, 0)
        norm_dt = normalize_to_utc(naive_dt)
        self.assertEqual(norm_dt.tzinfo, timezone.utc)
        self.assertEqual(norm_dt.year, 2026)
        self.assertEqual(norm_dt.month, 11)
        self.assertEqual(norm_dt.day, 1)
        self.assertEqual(norm_dt.hour, 8)

        # Timezone-aware IST datetime converts properly to UTC
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        ist_dt = datetime(2026, 11, 1, 14, 0, 0, tzinfo=ist_tz)
        utc_dt = normalize_to_utc(ist_dt)
        self.assertEqual(utc_dt.tzinfo, timezone.utc)
        self.assertEqual(utc_dt.hour, 8)
        self.assertEqual(utc_dt.minute, 30)

    def test_haversine_distance_calculation(self):
        """Verify Haversine formula against known coordinates in Bengaluru."""
        # Same location -> 0.0 meters
        dist_zero = calculate_haversine_distance_meters(12.9260, 77.6740, 12.9260, 77.6740)
        self.assertAlmostEqual(dist_zero, 0.0, places=3)

        # ~108.38 meters east at latitude 12.926 degrees
        dist_108m = calculate_haversine_distance_meters(12.9260, 77.6740, 12.9260, 77.6750)
        self.assertAlmostEqual(dist_108m, 108.38, delta=1.0)

        # Symmetric distance
        dist_reverse = calculate_haversine_distance_meters(12.9260, 77.6750, 12.9260, 77.6740)
        self.assertAlmostEqual(dist_108m, dist_reverse, places=4)

    def test_haversine_distance_numerical_stability(self):
        """Verify clamping prevents math domain error at antipodal boundary."""
        # North Pole to South Pole (exact antipodes: distance ~ pi * R = ~20,015,087m)
        dist_poles = calculate_haversine_distance_meters(90.0, 0.0, -90.0, 0.0)
        expected_half_circumference = math.pi * 6371000.0
        self.assertAlmostEqual(dist_poles, expected_half_circumference, delta=10.0)

        # Equator exact antipodes
        dist_equator = calculate_haversine_distance_meters(0.0, 0.0, 0.0, 180.0)
        self.assertAlmostEqual(dist_equator, expected_half_circumference, delta=10.0)

    def test_coordinate_validation_valid(self):
        """Valid coordinates in Bangalore should pass without exception."""
        validate_coordinates(12.9260, 77.6740)
        validate_coordinates(-90.0, -180.0)
        validate_coordinates(90.0, 180.0)

    def test_coordinate_validation_out_of_bounds(self):
        """Out-of-bounds coordinates must raise InvalidCoordinateError."""
        with self.assertRaises(InvalidCoordinateError):
            validate_coordinates(91.0, 77.0)

        with self.assertRaises(InvalidCoordinateError):
            validate_coordinates(-90.1, 77.0)

        with self.assertRaises(InvalidCoordinateError):
            validate_coordinates(12.0, 180.1)

        with self.assertRaises(InvalidCoordinateError):
            validate_coordinates(12.0, -180.1)

        with self.assertRaises(InvalidCoordinateError):
            validate_coordinates(float("nan"), 77.0)

        with self.assertRaises(InvalidCoordinateError):
            validate_coordinates(12.0, float("inf"))

    def test_validate_gps_proximity_within_geofence(self):
        """Test proximity calculation when worker is within geofence."""
        mp = MusterPoint(
            id=uuid.uuid4(),
            ward_id=uuid.uuid4(),
            name="Bellandur Gate",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            geofence_radius_meters=150,
        )

        # Worker is ~54 meters away
        worker_lat, worker_lon = 12.9260, 77.6745
        dist, is_within = validate_gps_proximity(worker_lat, worker_lon, mp)
        self.assertTrue(is_within)
        self.assertLess(dist, 150.0)

    def test_validate_gps_proximity_outside_geofence(self):
        """Test proximity calculation when worker breaches geofence radius."""
        mp = MusterPoint(
            id=uuid.uuid4(),
            ward_id=uuid.uuid4(),
            name="Bellandur Gate",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            geofence_radius_meters=100,
        )

        # Worker is ~216 meters away
        worker_lat, worker_lon = 12.9260, 77.6760
        dist, is_within = validate_gps_proximity(worker_lat, worker_lon, mp)
        self.assertFalse(is_within)
        self.assertGreater(dist, 100.0)


class TestAttendanceServiceAsync(unittest.IsolatedAsyncioTestCase):
    """Database-independent async tests for attendance eligibility and recording."""

    def setUp(self):
        self.worker_id = uuid.uuid4()
        self.ward_id = uuid.uuid4()
        self.other_ward_id = uuid.uuid4()
        self.mp_id = uuid.uuid4()

        now = datetime.now(timezone.utc)

        # Active Sanitation Worker
        self.worker = User(
            id=self.worker_id,
            email="worker@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        # Active Muster Point
        self.muster_point = MusterPoint(
            id=self.mp_id,
            ward_id=self.ward_id,
            name="Ward 150 Muster Point 1",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            geofence_radius_meters=150,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        # Active Ward Assignment
        self.assignment = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=self.worker_id,
            ward_id=self.ward_id,
            revoked_at=None,
            assigned_at=now,
        )

        # Mock Session
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()
        self.mock_session.flush = AsyncMock()

        # Mock begin_nested() context manager for savepoint
        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
        nested_cm.__aexit__ = AsyncMock(return_value=None)
        self.mock_session.begin_nested = MagicMock(return_value=nested_cm)

    # --- Check-In Eligibility Tests ---

    async def test_validate_check_in_eligibility_success(self):
        """Eligible worker with active assignment and valid muster point passes eligibility."""
        # 1. Worker lookup, 2. Assignment lookup, 3. MusterPoint lookup, 4. Daily attendance lookup (None)
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp, res_att]

        worker, mp, workday = await validate_check_in_eligibility(
            session=self.mock_session,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
        )

        self.assertEqual(worker.id, self.worker_id)
        self.assertEqual(mp.id, self.mp_id)
        self.assertIsInstance(workday, date)

    async def test_validate_check_in_eligibility_worker_not_found(self):
        """WorkerIneligibleError raised when worker user ID does not exist."""
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_worker

        with self.assertRaises(WorkerIneligibleError) as ctx:
            await validate_check_in_eligibility(
                session=self.mock_session,
                worker_id=uuid.uuid4(),
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
            )
        self.assertIn("not found", str(ctx.exception))

    async def test_validate_check_in_eligibility_wrong_role(self):
        """WorkerIneligibleError raised when user is not a sanitation worker."""
        citizen_user = User(
            id=self.worker_id,
            email="citizen@example.com",
            role=UserRole.CITIZEN.value,
            status=UserStatus.ACTIVE.value,
        )
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = citizen_user
        self.mock_session.execute.return_value = res_worker

        with self.assertRaises(WorkerIneligibleError) as ctx:
            await validate_check_in_eligibility(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
            )
        self.assertIn("only sanitation workers", str(ctx.exception))

    async def test_validate_check_in_eligibility_inactive_status(self):
        """WorkerIneligibleError raised when worker status is DISABLED."""
        disabled_worker = User(
            id=self.worker_id,
            email="disabled@bbmp.gov.in",
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.DISABLED.value,
        )
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = disabled_worker
        self.mock_session.execute.return_value = res_worker

        with self.assertRaises(WorkerIneligibleError) as ctx:
            await validate_check_in_eligibility(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
            )
        self.assertIn("not active", str(ctx.exception))

    async def test_validate_check_in_eligibility_unassigned_ward(self):
        """WardAssignmentError raised when worker has no active assignment to ward."""
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = None  # No active assignment

        self.mock_session.execute.side_effect = [res_worker, res_assign]

        with self.assertRaises(WardAssignmentError) as ctx:
            await validate_check_in_eligibility(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
            )
        self.assertIn("not actively assigned to ward", str(ctx.exception))

    async def test_validate_check_in_eligibility_inactive_muster_point(self):
        """MusterPointError raised when muster point has is_active=False."""
        inactive_mp = MusterPoint(
            id=self.mp_id,
            ward_id=self.ward_id,
            name="Decommissioned Point",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            is_active=False,
        )

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = inactive_mp

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp]

        with self.assertRaises(MusterPointError) as ctx:
            await validate_check_in_eligibility(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
            )
        self.assertIn("is inactive", str(ctx.exception))

    async def test_validate_check_in_eligibility_wrong_ward_muster_point(self):
        """MusterPointError raised when muster point belongs to a different ward."""
        wrong_ward_mp = MusterPoint(
            id=self.mp_id,
            ward_id=self.other_ward_id,  # Belongs to other ward
            name="Other Ward Station",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            is_active=True,
        )

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = wrong_ward_mp

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp]

        with self.assertRaises(MusterPointError) as ctx:
            await validate_check_in_eligibility(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
            )
        self.assertIn("not ward", str(ctx.exception))

    async def test_validate_check_in_eligibility_duplicate_daily_attendance(self):
        """DuplicateAttendanceError raised when worker already checked in today."""
        now = datetime.now(timezone.utc)
        workday = get_kolkata_workday_date(now)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=now,
            status=AttendanceStatus.PRESENT.value,
        )

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp, res_att]

        with self.assertRaises(DuplicateAttendanceError) as ctx:
            await validate_check_in_eligibility(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
            )
        self.assertIn("already has an attendance record", str(ctx.exception))

    # --- Record Check-In Tests ---

    async def test_record_check_in_within_geofence(self):
        """Successful check-in inside geofence sets status PRESENT and stores PostGIS geometry."""
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp, res_att]

        # 50m away from muster point (12.9260, 77.6740)
        worker_lat, worker_lon = 12.9260, 77.67446
        now = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)

        record = await record_check_in(
            session=self.mock_session,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            latitude=worker_lat,
            longitude=worker_lon,
            check_in_time=now,
        )

        self.assertEqual(record.status, AttendanceStatus.PRESENT.value)
        self.assertIsNone(record.exception_reason)
        self.assertEqual(record.check_in_at, now)
        self.assertLess(record.check_in_distance_meters, 150.0)

        # Coordinate order verification: POINT(lon lat)
        shape = to_shape(record.check_in_location)
        self.assertAlmostEqual(shape.x, worker_lon, places=4)
        self.assertAlmostEqual(shape.y, worker_lat, places=4)

        self.mock_session.add.assert_called_once_with(record)
        self.mock_session.flush.assert_awaited_once()

    async def test_record_check_in_outside_geofence(self):
        """Check-in outside geofence marks EXCEPTION_PENDING and logs exception reason."""
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp, res_att]

        # 300m away
        worker_lat, worker_lon = 12.9260, 77.6768
        record = await record_check_in(
            session=self.mock_session,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            latitude=worker_lat,
            longitude=worker_lon,
        )

        self.assertEqual(record.status, AttendanceStatus.EXCEPTION_PENDING.value)
        self.assertIn("Check-in outside geofence", record.exception_reason)
        self.assertGreater(record.check_in_distance_meters, 150.0)

    async def test_record_check_in_concurrent_integrity_error(self):
        """Simulate concurrent duplicate check-in violating uq_worker_daily_attendance."""
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp, res_att]
        self.mock_session.flush.side_effect = IntegrityError(
            "statement",
            {},
            Exception('duplicate key value violates unique constraint "uq_worker_daily_attendance"'),
        )

        with self.assertRaises(DuplicateAttendanceError) as ctx:
            await record_check_in(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
            )
        self.assertIn("already has an attendance record", str(ctx.exception))

    async def test_record_check_in_unrelated_integrity_error_reraised(self):
        """Unrelated database IntegrityError (foreign key, check constraint) is re-raised directly."""
        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        res_att = MagicMock()
        res_att.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [res_worker, res_assign, res_mp, res_att]
        self.mock_session.flush.side_effect = IntegrityError(
            "statement",
            {},
            Exception('insert or update on table "attendance_records" violates foreign key constraint "fk_users"'),
        )

        with self.assertRaises(IntegrityError):
            await record_check_in(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
            )

    # --- Record Check-Out Tests ---

    async def test_record_check_out_success_within_geofence(self):
        """Normal check-out inside geofence updates record and maintains PRESENT status."""
        now = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(now)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc),
            check_in_location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            check_in_distance_meters=20.0,
            status=AttendanceStatus.PRESENT.value,
        )

        # 1. Existing attendance lookup, 2. Worker lookup, 3. Ward assignment lookup, 4. Muster point lookup
        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [res_att, res_worker, res_assign, res_mp]

        updated = await record_check_out(
            session=self.mock_session,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            latitude=12.9260,
            longitude=77.6741,
            check_out_time=now,
        )

        self.assertEqual(updated.check_out_at, now)
        self.assertIsNotNone(updated.check_out_location)
        self.assertLess(updated.check_out_distance_meters, 150.0)
        self.assertEqual(updated.status, AttendanceStatus.PRESENT.value)
        self.mock_session.flush.assert_awaited_once()

    async def test_record_check_out_without_check_in(self):
        """AttendanceNotFoundError raised when check-out attempted without check-in."""
        res_att = MagicMock()
        res_att.scalars().first.return_value = None
        self.mock_session.execute.return_value = res_att

        with self.assertRaises(AttendanceNotFoundError) as ctx:
            await record_check_out(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
            )
        self.assertIn("No attendance check-in found", str(ctx.exception))

    async def test_record_check_out_duplicate(self):
        """DuplicateCheckOutError raised when check-out has already been recorded."""
        now = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(now)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc),
            check_out_at=datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc),
            status=AttendanceStatus.PRESENT.value,
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record
        self.mock_session.execute.return_value = res_att

        with self.assertRaises(DuplicateCheckOutError) as ctx:
            await record_check_out(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
                check_out_time=now,
            )
        self.assertIn("Check-out has already been recorded", str(ctx.exception))

    async def test_record_check_out_timestamp_earlier_than_check_in(self):
        """InvalidAttendanceTimeError raised when check-out time is earlier than check-in time."""
        check_in_at = datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(check_in_at)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=check_in_at,
            status=AttendanceStatus.PRESENT.value,
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [res_att, res_worker, res_assign, res_mp]

        # Check-out attempted at 06:00 (1 hour before check-in)
        earlier_time = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)

        with self.assertRaises(InvalidAttendanceTimeError) as ctx:
            await record_check_out(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
                check_out_time=earlier_time,
            )
        self.assertIn("cannot be earlier than check-in", str(ctx.exception))

    async def test_record_check_out_outside_geofence_triggers_exception(self):
        """Check-out outside geofence transitions status from PRESENT to EXCEPTION_PENDING."""
        check_in_at = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(check_in_at)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=check_in_at,
            status=AttendanceStatus.PRESENT.value,
            exception_reason=None,
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [res_att, res_worker, res_assign, res_mp]

        # 300m away from muster point
        check_out_time = datetime(2026, 11, 1, 14, 30, tzinfo=timezone.utc)
        updated = await record_check_out(
            session=self.mock_session,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            latitude=12.9260,
            longitude=77.6768,
            check_out_time=check_out_time,
        )

        self.assertEqual(updated.status, AttendanceStatus.EXCEPTION_PENDING.value)
        self.assertIn("Check-out outside geofence", updated.exception_reason)

    async def test_record_check_out_preserves_existing_exception_status(self):
        """
        If check-in was already flagged EXCEPTION_PENDING, check-out preserves
        EXCEPTION_PENDING even when check-out GPS is inside the geofence.
        """
        check_in_at = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(check_in_at)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=check_in_at,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
            exception_reason="Check-in outside geofence: distance 250.0m exceeds radius 150m",
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [res_att, res_worker, res_assign, res_mp]

        # Check-out is within geofence
        check_out_time = datetime(2026, 11, 1, 14, 30, tzinfo=timezone.utc)
        updated = await record_check_out(
            session=self.mock_session,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            latitude=12.9260,
            longitude=77.6741,
            check_out_time=check_out_time,
        )

        # Status must still be EXCEPTION_PENDING
        self.assertEqual(updated.status, AttendanceStatus.EXCEPTION_PENDING.value)
        self.assertIn("Check-in outside geofence", updated.exception_reason)

    async def test_record_check_out_ward_mismatch_cross_ward_denied(self):
        """Worker assigned to multiple wards cannot check out an attendance record against a different ward."""
        check_in_at = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(check_in_at)

        # Record belongs to self.ward_id
        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=check_in_at,
            status=AttendanceStatus.PRESENT.value,
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record
        self.mock_session.execute.return_value = res_att

        # Check-out requested for self.other_ward_id
        check_out_time = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
        with self.assertRaises(WardAssignmentError) as ctx:
            await record_check_out(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.other_ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
                check_out_time=check_out_time,
            )
        self.assertIn("does not match check-in ward", str(ctx.exception))
        self.mock_session.flush.assert_not_called()

    async def test_record_check_out_missing_check_in_timestamp_absent_record(self):
        """Check-out on an ABSENT record without check_in_at raises MissingCheckInError."""
        workday = date(2026, 11, 1)

        # Record exists (e.g. marked ABSENT) but check_in_at is None
        absent_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=None,
            status=AttendanceStatus.ABSENT.value,
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = absent_record
        self.mock_session.execute.return_value = res_att

        check_out_time = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
        with self.assertRaises(MissingCheckInError) as ctx:
            await record_check_out(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
                check_out_time=check_out_time,
            )
        # Verify the error does not falsely claim the record does not exist
        self.assertNotIn("not found", str(ctx.exception).lower())
        self.assertIn("no check-in timestamp", str(ctx.exception))
        self.mock_session.flush.assert_not_called()

    async def test_record_check_out_naive_check_out_time_normalized(self):
        """Naive caller-provided check_out_time is normalized without offset comparison TypeError."""
        check_in_at = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(check_in_at)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=check_in_at,
            status=AttendanceStatus.PRESENT.value,
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [res_att, res_worker, res_assign, res_mp]

        # Naive check-out datetime (no tzinfo)
        naive_checkout = datetime(2026, 11, 1, 14, 0)
        updated = await record_check_out(
            session=self.mock_session,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            latitude=12.9260,
            longitude=77.6741,
            check_out_time=naive_checkout,
        )

        self.assertEqual(updated.check_out_at.tzinfo, timezone.utc)
        self.assertEqual(updated.check_out_at.hour, 14)
        self.mock_session.flush.assert_awaited_once()

    async def test_record_check_out_naive_earlier_than_check_in_raises_domain_error(self):
        """Naive check_out_time earlier than aware check_in_at cleanly raises InvalidAttendanceTimeError."""
        check_in_at = datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)
        workday = get_kolkata_workday_date(check_in_at)

        existing_record = AttendanceRecord(
            id=uuid.uuid4(),
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            muster_point_id=self.mp_id,
            attendance_date=workday,
            check_in_at=check_in_at,
            status=AttendanceStatus.PRESENT.value,
        )

        res_att = MagicMock()
        res_att.scalars().first.return_value = existing_record

        res_worker = MagicMock()
        res_worker.scalars().first.return_value = self.worker

        res_assign = MagicMock()
        res_assign.scalars().first.return_value = self.assignment

        res_mp = MagicMock()
        res_mp.scalars().first.return_value = self.muster_point

        self.mock_session.execute.side_effect = [res_att, res_worker, res_assign, res_mp]

        # Naive check-out earlier than check-in
        naive_earlier = datetime(2026, 11, 1, 6, 0)
        with self.assertRaises(InvalidAttendanceTimeError) as ctx:
            await record_check_out(
                session=self.mock_session,
                worker_id=self.worker_id,
                ward_id=self.ward_id,
                muster_point_id=self.mp_id,
                latitude=12.9260,
                longitude=77.6740,
                check_out_time=naive_earlier,
            )
        self.assertIn("cannot be earlier than check-in", str(ctx.exception))


class TestAttendanceReviewAndRosterService(unittest.IsolatedAsyncioTestCase):
    """Unit tests for exception review and daily roster service functions."""

    def setUp(self):
        self.mock_session = AsyncMock()
        self.mock_session.flush = AsyncMock()

        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
        nested_cm.__aexit__ = AsyncMock(return_value=None)
        self.mock_session.begin_nested = MagicMock(return_value=nested_cm)

        self.record_id = uuid.uuid4()
        self.reviewer_id = uuid.uuid4()
        self.ward_id = uuid.uuid4()
        self.worker_id = uuid.uuid4()
        self.today = date(2026, 11, 1)

    async def test_review_not_found(self):
        res = MagicMock()
        res.scalars().first.return_value = None
        self.mock_session.execute.return_value = res

        with self.assertRaises(AttendanceNotFoundError):
            await review_attendance_record(
                session=self.mock_session,
                record_id=self.record_id,
                reviewer_id=self.reviewer_id,
                action="APPROVE",
            )

    async def test_review_not_reviewable_state(self):
        record = AttendanceRecord(
            id=self.record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.PRESENT.value,
        )
        res = MagicMock()
        res.scalars().first.return_value = record
        self.mock_session.execute.return_value = res

        with self.assertRaises(AttendanceNotReviewableError):
            await review_attendance_record(
                session=self.mock_session,
                record_id=self.record_id,
                reviewer_id=self.reviewer_id,
                action="APPROVE",
            )

    async def test_review_reject_requires_notes(self):
        record = AttendanceRecord(
            id=self.record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
        )
        res = MagicMock()
        res.scalars().first.return_value = record
        self.mock_session.execute.return_value = res

        with self.assertRaises(ValueError) as ctx:
            await review_attendance_record(
                session=self.mock_session,
                record_id=self.record_id,
                reviewer_id=self.reviewer_id,
                action="REJECT",
                review_notes="",
            )
        self.assertIn("A rejection note is required", str(ctx.exception))

    async def test_review_approve_success(self):
        record = AttendanceRecord(
            id=self.record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
        )
        res = MagicMock()
        res.scalars().first.return_value = record
        self.mock_session.execute.return_value = res

        updated = await review_attendance_record(
            session=self.mock_session,
            record_id=self.record_id,
            reviewer_id=self.reviewer_id,
            action="APPROVE",
            review_notes="Approved after manual verification.",
        )
        self.assertEqual(updated.status, AttendanceStatus.PRESENT.value)
        self.assertEqual(updated.reviewed_by, self.reviewer_id)
        self.assertIsNotNone(updated.reviewed_at)
        self.assertEqual(updated.review_notes, "Approved after manual verification.")

    async def test_review_reject_success(self):
        record = AttendanceRecord(
            id=self.record_id,
            worker_id=self.worker_id,
            ward_id=self.ward_id,
            attendance_date=self.today,
            status=AttendanceStatus.EXCEPTION_PENDING.value,
        )
        res = MagicMock()
        res.scalars().first.return_value = record
        self.mock_session.execute.return_value = res

        updated = await review_attendance_record(
            session=self.mock_session,
            record_id=self.record_id,
            reviewer_id=self.reviewer_id,
            action="REJECT",
            review_notes="Worker absent from duty station.",
        )
        self.assertEqual(updated.status, AttendanceStatus.REJECTED.value)
        self.assertEqual(updated.reviewed_by, self.reviewer_id)
        self.assertEqual(updated.review_notes, "Worker absent from duty station.")

    async def test_get_daily_attendance_roster_service(self):
        counts_row = MagicMock()
        counts_row.total = 3
        counts_row.present = 2
        counts_row.exception_pending = 1
        counts_row.rejected = 0

        res_counts = MagicMock()
        res_counts.first.return_value = counts_row

        r1 = AttendanceRecord(id=uuid.uuid4(), worker_id=self.worker_id, ward_id=self.ward_id, attendance_date=self.today, status=AttendanceStatus.PRESENT.value)
        r2 = AttendanceRecord(id=uuid.uuid4(), worker_id=uuid.uuid4(), ward_id=self.ward_id, attendance_date=self.today, status=AttendanceStatus.PRESENT.value)
        r3 = AttendanceRecord(id=uuid.uuid4(), worker_id=uuid.uuid4(), ward_id=self.ward_id, attendance_date=self.today, status=AttendanceStatus.EXCEPTION_PENDING.value)

        res_records = MagicMock()
        res_records.scalars().unique().all.return_value = [r1, r2, r3]

        self.mock_session.execute.side_effect = [res_counts, res_records]

        records, total, present, exc_pending, rejected = await get_daily_attendance_roster(
            session=self.mock_session,
            ward_id=self.ward_id,
            attendance_date=self.today,
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(total, 3)
        self.assertEqual(present, 2)
        self.assertEqual(exc_pending, 1)
        self.assertEqual(rejected, 0)


if __name__ == "__main__":
    unittest.main()


