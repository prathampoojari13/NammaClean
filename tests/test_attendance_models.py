"""
Unit tests for Attendance models: MusterPoint.

Focused, database-independent tests verifying:
1. Model table name, columns, and types.
2. Check constraint 'ck_muster_points_positive_geofence_radius' configuration.
3. Foreign key definition on ward_id targeting wards.id with CASCADE.
4. Default values for geofence_radius_meters (150) and is_active (True).
5. In-memory model instantiation and representation string.
6. Relationship configuration with Ward model.
"""

import uuid
import unittest
from datetime import datetime, date, timezone
from geoalchemy2.elements import WKTElement
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.attendance import MusterPoint, AttendanceRecord
from app.models.enums import AttendanceStatus
from app.models.user import User
from app.models.ward import Ward


class TestMusterPointModel(unittest.TestCase):
    """Database-independent tests for MusterPoint SQLAlchemy model."""

    def test_muster_point_table_and_columns(self):
        """Verify table name and required columns exist on the model."""
        self.assertEqual(MusterPoint.__tablename__, "muster_points")

        col_names = {c.name for c in MusterPoint.__table__.columns}
        expected_columns = {
            "id",
            "ward_id",
            "name",
            "location",
            "geofence_radius_meters",
            "is_active",
            "created_at",
            "updated_at",
        }
        self.assertTrue(expected_columns.issubset(col_names))

    def test_muster_point_foreign_key(self):
        """Verify ward_id foreign key targets wards.id with CASCADE delete."""
        ward_id_col = MusterPoint.__table__.columns["ward_id"]
        fk = list(ward_id_col.foreign_keys)[0]
        self.assertEqual(fk.target_fullname, "wards.id")
        self.assertEqual(fk.ondelete, "CASCADE")

    def test_muster_point_check_constraint(self):
        """Verify geofence_radius_meters positive constraint exists."""
        constraints = [
            c for c in MusterPoint.__table__.constraints
            if isinstance(c, CheckConstraint)
        ]
        constraint_names = {c.name for c in constraints}
        self.assertIn("ck_muster_points_positive_geofence_radius", constraint_names)

        target_constraint = next(
            c for c in constraints
            if c.name == "ck_muster_points_positive_geofence_radius"
        )
        self.assertIn("geofence_radius_meters > 0", str(target_constraint.sqltext))

    def test_muster_point_instantiation_defaults(self):
        """Verify in-memory creation and default values."""
        ward_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        mp = MusterPoint(
            ward_id=ward_id,
            name="Bellandur Muster Depot",
            location=WKTElement("POINT(77.675 12.935)", srid=4326),
            created_at=now,
            updated_at=now,
        )

        self.assertEqual(mp.ward_id, ward_id)
        self.assertEqual(mp.name, "Bellandur Muster Depot")
        self.assertEqual(mp.geofence_radius_meters, 150)
        self.assertTrue(mp.is_active)
        self.assertIn("Bellandur Muster Depot", repr(mp))
        self.assertIn("150m", repr(mp))

    def test_ward_relationship_back_populates(self):
        """Verify relationships between Ward and MusterPoint."""
        ward_mp_rel = Ward.__mapper__.relationships.get("muster_points")
        self.assertIsNotNone(ward_mp_rel)
        self.assertEqual(ward_mp_rel.back_populates, "ward")

        mp_ward_rel = MusterPoint.__mapper__.relationships.get("ward")
        self.assertIsNotNone(mp_ward_rel)
        self.assertEqual(mp_ward_rel.back_populates, "muster_points")


class TestAttendanceRecordModel(unittest.TestCase):
    """Database-independent tests for AttendanceRecord SQLAlchemy model."""

    def test_attendance_record_table_and_columns(self):
        """Verify table name and all 17 required columns exist."""
        self.assertEqual(AttendanceRecord.__tablename__, "attendance_records")

        col_names = {c.name for c in AttendanceRecord.__table__.columns}
        expected_columns = {
            "id",
            "worker_id",
            "ward_id",
            "muster_point_id",
            "attendance_date",
            "check_in_at",
            "check_out_at",
            "check_in_location",
            "check_out_location",
            "check_in_distance_meters",
            "check_out_distance_meters",
            "status",
            "exception_reason",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "created_at",
            "updated_at",
        }
        self.assertTrue(expected_columns.issubset(col_names))

    def test_attendance_record_foreign_keys_and_ondelete(self):
        """Verify foreign key targets and deletion protection rules."""
        cols = AttendanceRecord.__table__.columns

        # worker_id -> users.id with RESTRICT
        worker_fk = list(cols["worker_id"].foreign_keys)[0]
        self.assertEqual(worker_fk.target_fullname, "users.id")
        self.assertEqual(worker_fk.ondelete, "RESTRICT")

        # ward_id -> wards.id with RESTRICT
        ward_fk = list(cols["ward_id"].foreign_keys)[0]
        self.assertEqual(ward_fk.target_fullname, "wards.id")
        self.assertEqual(ward_fk.ondelete, "RESTRICT")

        # muster_point_id -> muster_points.id with SET NULL
        muster_fk = list(cols["muster_point_id"].foreign_keys)[0]
        self.assertEqual(muster_fk.target_fullname, "muster_points.id")
        self.assertEqual(muster_fk.ondelete, "SET NULL")

        # reviewed_by -> users.id with SET NULL
        reviewer_fk = list(cols["reviewed_by"].foreign_keys)[0]
        self.assertEqual(reviewer_fk.target_fullname, "users.id")
        self.assertEqual(reviewer_fk.ondelete, "SET NULL")

    def test_attendance_record_uniqueness_constraint(self):
        """Verify at most one attendance record per worker per day."""
        unique_constraints = [
            c for c in AttendanceRecord.__table__.constraints
            if isinstance(c, UniqueConstraint)
        ]
        uq_names = {c.name for c in unique_constraints}
        self.assertIn("uq_worker_daily_attendance", uq_names)

        target_uq = next(c for c in unique_constraints if c.name == "uq_worker_daily_attendance")
        uq_col_names = {c.name for c in target_uq.columns}
        self.assertEqual(uq_col_names, {"worker_id", "attendance_date"})

    def test_attendance_record_check_constraints(self):
        """Verify business integrity check constraints are configured."""
        check_constraints = [
            c for c in AttendanceRecord.__table__.constraints
            if isinstance(c, CheckConstraint)
        ]
        ck_names = {c.name for c in check_constraints}

        expected_ck = {
            "ck_attendance_valid_status",
            "ck_attendance_checkout_requires_checkin",
            "ck_attendance_checkout_gte_checkin",
            "ck_attendance_check_in_distance_non_negative",
            "ck_attendance_check_out_distance_non_negative",
        }
        self.assertTrue(expected_ck.issubset(ck_names))

        # Check status constraint text
        status_ck = next(c for c in check_constraints if c.name == "ck_attendance_valid_status")
        self.assertIn("'PRESENT'", str(status_ck.sqltext))
        self.assertIn("'EXCEPTION_PENDING'", str(status_ck.sqltext))

        # Check checkout constraints text
        co_req_ck = next(c for c in check_constraints if c.name == "ck_attendance_checkout_requires_checkin")
        self.assertIn("check_out_at IS NULL OR check_in_at IS NOT NULL", str(co_req_ck.sqltext))

        co_gte_ck = next(c for c in check_constraints if c.name == "ck_attendance_checkout_gte_checkin")
        self.assertIn("check_out_at >= check_in_at", str(co_gte_ck.sqltext))

        # Check distance constraints text
        dist_in_ck = next(c for c in check_constraints if c.name == "ck_attendance_check_in_distance_non_negative")
        self.assertIn("check_in_distance_meters >= 0", str(dist_in_ck.sqltext))

    def test_attendance_status_enum(self):
        """Verify AttendanceStatus enum values."""
        self.assertEqual(AttendanceStatus.PRESENT.value, "PRESENT")
        self.assertEqual(AttendanceStatus.ABSENT.value, "ABSENT")
        self.assertEqual(AttendanceStatus.HALF_DAY.value, "HALF_DAY")
        self.assertEqual(AttendanceStatus.EXCEPTION_PENDING.value, "EXCEPTION_PENDING")
        self.assertEqual(AttendanceStatus.REJECTED.value, "REJECTED")

    def test_attendance_record_relationships(self):
        """Verify relationships between User, Ward, MusterPoint, and AttendanceRecord."""
        # AttendanceRecord -> User (worker)
        worker_rel = AttendanceRecord.__mapper__.relationships.get("worker")
        self.assertIsNotNone(worker_rel)
        self.assertEqual(worker_rel.back_populates, "attendance_records")

        # User -> AttendanceRecord (attendance_records)
        user_att_rel = User.__mapper__.relationships.get("attendance_records")
        self.assertIsNotNone(user_att_rel)
        self.assertEqual(user_att_rel.back_populates, "worker")

        # AttendanceRecord -> User (reviewer)
        reviewer_rel = AttendanceRecord.__mapper__.relationships.get("reviewer")
        self.assertIsNotNone(reviewer_rel)
        self.assertEqual(reviewer_rel.back_populates, "reviewed_attendances")

        # User -> AttendanceRecord (reviewed_attendances)
        user_rev_rel = User.__mapper__.relationships.get("reviewed_attendances")
        self.assertIsNotNone(user_rev_rel)
        self.assertEqual(user_rev_rel.back_populates, "reviewer")

        # AttendanceRecord -> Ward
        ward_rel = AttendanceRecord.__mapper__.relationships.get("ward")
        self.assertIsNotNone(ward_rel)
        self.assertEqual(ward_rel.back_populates, "attendance_records")

        # Ward -> AttendanceRecord
        ward_att_rel = Ward.__mapper__.relationships.get("attendance_records")
        self.assertIsNotNone(ward_att_rel)
        self.assertEqual(ward_att_rel.back_populates, "ward")

        # AttendanceRecord -> MusterPoint
        mp_rel = AttendanceRecord.__mapper__.relationships.get("muster_point")
        self.assertIsNotNone(mp_rel)
        self.assertEqual(mp_rel.back_populates, "attendance_records")

        # MusterPoint -> AttendanceRecord
        mp_att_rel = MusterPoint.__mapper__.relationships.get("attendance_records")
        self.assertIsNotNone(mp_att_rel)
        self.assertEqual(mp_att_rel.back_populates, "muster_point")

    def test_attendance_record_instantiation_defaults(self):
        """Verify in-memory model instantiation and defaults."""
        worker_id = uuid.uuid4()
        ward_id = uuid.uuid4()
        today = date(2026, 11, 1)  # Asia/Kolkata workday
        now = datetime.now(timezone.utc)

        record = AttendanceRecord(
            worker_id=worker_id,
            ward_id=ward_id,
            attendance_date=today,
            created_at=now,
            updated_at=now,
        )

        self.assertEqual(record.worker_id, worker_id)
        self.assertEqual(record.ward_id, ward_id)
        self.assertEqual(record.attendance_date, today)
        self.assertEqual(record.status, AttendanceStatus.PRESENT.value)

        # Nullable fields default to None
        self.assertIsNone(record.muster_point_id)
        self.assertIsNone(record.check_in_at)
        self.assertIsNone(record.check_out_at)
        self.assertIsNone(record.check_in_location)
        self.assertIsNone(record.check_out_location)
        self.assertIsNone(record.check_in_distance_meters)
        self.assertIsNone(record.check_out_distance_meters)
        self.assertIsNone(record.exception_reason)
        self.assertIsNone(record.reviewed_by)
        self.assertIsNone(record.reviewed_at)
        self.assertIsNone(record.review_notes)

        # Repr string
        repr_str = repr(record)
        self.assertIn("AttendanceRecord", repr_str)
        self.assertIn("2026-11-01", repr_str)
        self.assertIn("PRESENT", repr_str)


if __name__ == "__main__":
    unittest.main()
