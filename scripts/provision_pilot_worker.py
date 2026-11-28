"""
Idempotent Administrative Provisioning Script for NammaClean Pilot Worker.

Provisions the minimal required pilot data needed for worker login and attendance OTP:
1. Ward 4 (BBMP-W004) - Yelahanka Satellite Town administrative boundary.
2. Muster Point - Active physical roll-call depot with 150m geofence radius.
3. Sanitation Worker - Account for pratikgokavi2007@gmail.com with official ID BBMP-WRK-042.
4. Ward Assignment - Active association linking worker to Ward 4.
5. Worker Schedule - Active weekly schedule ensuring check-in window is open for testing.

Safety Features:
- Fully idempotent: Reuses existing records; never creates duplicates on repeated runs.
- Conflict-safe: Refuses to overwrite conflicting roles or official IDs.
- Fail-closed transactions: Atomic transaction rolled back on any error.
- Strict password policy: Enforces 12-128 character minimum and Argon2id hashing.
- Never prints passwords, hashes, JWTs, credentials, or connection strings.
- Requires explicit confirmation flag (--confirm-production) when connecting to non-local databases.
- Supports --dry-run for pre-execution verification.
"""

import os
import sys
import uuid
import getpass
import argparse
import logging
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, select, text, or_
from sqlalchemy.orm import Session
from geoalchemy2.elements import WKTElement

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User, normalize_email, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint
from app.models.schedule import WorkerSchedule

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("provision_pilot_worker")

# Well-known pilot identifiers
PILOT_WARD_CODE = "BBMP-W004"
PILOT_WARD_NAME = "Ward 4 - Yelahanka Satellite Town & Avalahalli Corridor"
PILOT_MUSTER_NAME = "Yelahanka Satellite Town Muster Depot"
PILOT_MUSTER_LOCATION = "POINT(77.5895 13.0985)"
PILOT_GEOFENCE_RADIUS = 150
PILOT_WORKER_EMAIL = "pratikgokavi2007@gmail.com"
PILOT_WORKER_FULL_NAME = "Pratik Gokavi"
PILOT_WORKER_OFFICIAL_ID = "BBMP-WRK-042"
PILOT_WORKER_PHONE = "+91 98450 12345"
PILOT_BOUNDARY_WKT = (
    "MULTIPOLYGON(((77.5580 13.0850, 77.6150 13.0850, 77.6150 13.1420, "
    "77.5580 13.1420, 77.5580 13.0850)))"
)


class ProvisioningError(Exception):
    """Raised when provisioning cannot safely proceed due to conflicting state."""
    pass


def validate_password_policy(password: str) -> None:
    """Enforces application password policy (12 to 128 characters)."""
    if not password or len(password) < 12:
        raise ValueError("Password must be at least 12 characters long.")
    if len(password) > 128:
        raise ValueError("Password must not exceed 128 characters.")


def is_production_database_url(db_url: str) -> bool:
    """Heuristic check to determine if database URL targets a cloud/production host."""
    if getattr(settings, "APP_ENV", "").lower() in ("production", "staging", "prod"):
        return True
    url_lower = db_url.lower()
    local_identifiers = ("localhost", "127.0.0.1", "::1", "nammaclean_test_db")
    from urllib.parse import urlparse
    parsed = urlparse(url_lower)
    hostname = parsed.hostname or ""
    if hostname in local_identifiers and "render" not in url_lower and "onrender" not in url_lower:
        return False
    return True


def provision_pilot_worker(
    session: Session,
    worker_password: Optional[str] = None,
    update_password: bool = False,
    schedule_mode: str = "pilot-24x7",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Executes idempotent provisioning of pilot data within the provided SQLAlchemy session.
    
    Returns a dictionary of provisioned/reused record summaries.
    Does not commit; caller owns transaction boundary.
    """
    summary: Dict[str, Any] = {}

    # 1. Resolve or Create Ward 4
    stmt_ward = select(Ward).where(Ward.ward_code == PILOT_WARD_CODE)
    existing_ward = session.execute(stmt_ward).scalars().first()

    if existing_ward:
        ward = existing_ward
        summary["ward"] = {"id": str(ward.id), "code": ward.ward_code, "action": "REUSED"}
        logger.info("Found existing pilot ward: %s (id: %s)", ward.ward_code, ward.id)
    else:
        ward = Ward(
            id=uuid.uuid4(),
            ward_code=PILOT_WARD_CODE,
            display_name=PILOT_WARD_NAME,
            boundary=WKTElement(PILOT_BOUNDARY_WKT, srid=4326),
        )
        session.add(ward)
        session.flush()
        summary["ward"] = {"id": str(ward.id), "code": ward.ward_code, "action": "CREATED"}
        logger.info("Created pilot ward: %s (id: %s)", ward.ward_code, ward.id)

    # 2. Resolve or Create Muster Point
    stmt_mp = select(MusterPoint).where(
        MusterPoint.ward_id == ward.id,
        MusterPoint.name == PILOT_MUSTER_NAME,
    )
    existing_mp = session.execute(stmt_mp).scalars().first()

    if existing_mp:
        muster_point = existing_mp
        if not muster_point.is_active:
            # Reactivate without altering existing location or geofence
            muster_point.is_active = True
            session.flush()
            summary["muster_point"] = {"id": str(muster_point.id), "action": "REACTIVATED"}
        else:
            summary["muster_point"] = {"id": str(muster_point.id), "action": "REUSED"}
        logger.info("Found existing muster point: %s (id: %s)", muster_point.name, muster_point.id)
    else:
        muster_point = MusterPoint(
            id=uuid.uuid4(),
            ward_id=ward.id,
            name=PILOT_MUSTER_NAME,
            location=WKTElement(PILOT_MUSTER_LOCATION, srid=4326),
            geofence_radius_meters=PILOT_GEOFENCE_RADIUS,
            is_active=True,
        )
        session.add(muster_point)
        session.flush()
        summary["muster_point"] = {"id": str(muster_point.id), "action": "CREATED"}
        logger.info("Created muster point: %s (id: %s)", muster_point.name, muster_point.id)

    # 3. Resolve or Create Sanitation Worker
    normalized_worker_email = normalize_email(PILOT_WORKER_EMAIL)
    stmt_user = select(User).where(User.email == normalized_worker_email)
    existing_user = session.execute(stmt_user).scalars().first()

    if existing_user:
        # Refuse to overwrite if existing account has conflicting non-worker role
        if existing_user.role != UserRole.SANITATION_WORKER.value:
            raise ProvisioningError(
                f"Conflict: Account '{normalized_worker_email}' already exists with role '{existing_user.role}', "
                f"not '{UserRole.SANITATION_WORKER.value}'. Refusing to overwrite existing user identity."
            )
        # Check official_id conflict
        if existing_user.official_id and existing_user.official_id != PILOT_WORKER_OFFICIAL_ID:
            raise ProvisioningError(
                f"Conflict: Account '{normalized_worker_email}' has conflicting official ID "
                f"'{existing_user.official_id}' (expected '{PILOT_WORKER_OFFICIAL_ID}'). Refusing to overwrite."
            )

        worker = existing_user
        # Ensure status is active and ward_id is mapped
        worker_updated = False
        if worker.status != UserStatus.ACTIVE.value:
            worker.status = UserStatus.ACTIVE.value
            worker_updated = True
        if not worker.ward_id:
            worker.ward_id = ward.id
            worker_updated = True
        if not worker.official_id:
            worker.official_id = PILOT_WORKER_OFFICIAL_ID
            worker_updated = True

        # Existing worker password is ONLY updated if explicitly requested via update_password flag
        if worker_password and update_password:
            validate_password_policy(worker_password)
            worker.password_hash = hash_password(worker_password)
            worker_updated = True
            logger.info("Explicitly updated password credentials for existing worker (--update-password).")
        elif worker_password and not update_password:
            logger.info("Worker account exists: preserved existing password (pass --update-password to override).")

        if worker_updated:
            worker.updated_at = utc_now()
            session.flush()
            summary["worker"] = {"id": str(worker.id), "email": worker.email, "action": "UPDATED"}
        else:
            summary["worker"] = {"id": str(worker.id), "email": worker.email, "action": "REUSED"}
        logger.info("Found existing worker account: %s (id: %s)", worker.email, worker.id)
    else:
        # Verify official_id is not already taken by another user
        stmt_off = select(User).where(User.official_id == PILOT_WORKER_OFFICIAL_ID)
        conflicting_off = session.execute(stmt_off).scalars().first()
        if conflicting_off:
            raise ProvisioningError(
                f"Conflict: Official employee ID '{PILOT_WORKER_OFFICIAL_ID}' is already registered to "
                f"another account ({conflicting_off.email})."
            )

        if not worker_password:
            raise ValueError(
                "Initial password is required to create new worker account. "
                "Provide password via secure prompt or WORKER_INITIAL_PASSWORD environment variable."
            )
        validate_password_policy(worker_password)

        worker = User(
            id=uuid.uuid4(),
            email=normalized_worker_email,
            password_hash=hash_password(worker_password),
            role=UserRole.SANITATION_WORKER.value,
            status=UserStatus.ACTIVE.value,
            full_name=PILOT_WORKER_FULL_NAME,
            official_id=PILOT_WORKER_OFFICIAL_ID,
            phone_number=PILOT_WORKER_PHONE,
            ward_id=ward.id,
            locality="Yelahanka Satellite Town",
            address="Sector 4, Yelahanka New Town, Bengaluru",
        )
        session.add(worker)
        session.flush()
        summary["worker"] = {"id": str(worker.id), "email": worker.email, "action": "CREATED"}
        logger.info("Created sanitation worker account: %s (id: %s)", worker.email, worker.id)

    # 4. Resolve or Create Active Ward Assignment
    stmt_assign = select(UserWardAssignment).where(
        UserWardAssignment.user_id == worker.id,
        UserWardAssignment.ward_id == ward.id,
        UserWardAssignment.revoked_at.is_(None),
    )
    existing_assign = session.execute(stmt_assign).scalars().first()

    if existing_assign:
        summary["ward_assignment"] = {"id": str(existing_assign.id), "action": "REUSED"}
        logger.info("Found active ward assignment: id=%s", existing_assign.id)
    else:
        assign = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=worker.id,
            ward_id=ward.id,
            assigned_at=utc_now(),
        )
        session.add(assign)
        session.flush()
        summary["ward_assignment"] = {"id": str(assign.id), "action": "CREATED"}
        logger.info("Created active ward assignment: id=%s", assign.id)

    # 5. Resolve or Create Active Worker Schedule
    stmt_sched = select(WorkerSchedule).where(
        WorkerSchedule.worker_id == worker.id,
        WorkerSchedule.ward_id == ward.id,
        WorkerSchedule.is_active == True,
    )
    existing_sched = session.execute(stmt_sched).scalars().first()

    if existing_sched:
        summary["schedule"] = {"id": str(existing_sched.id), "action": "REUSED"}
        logger.info("Found active worker schedule: id=%s (preserved untouched)", existing_sched.id)
    else:
        if schedule_mode == "canonical-morning":
            # Canonical municipal morning shift: 07:00-14:00, check-in 06:45-07:30, Mon-Sat
            days = [1, 2, 3, 4, 5, 6]
            shift_start = "07:00"
            shift_end = "14:00"
            check_in_start = "06:45"
            check_in_end = "07:30"
            check_out_start = "14:00"
            check_out_end = "15:00"
            grace = 10
        else:
            # Pilot 24x7 testing schedule: covers all 7 days with all-day check-in window
            days = [1, 2, 3, 4, 5, 6, 7]
            shift_start = "06:00"
            shift_end = "22:00"
            check_in_start = "00:00"
            check_in_end = "23:59"
            check_out_start = "14:00"
            check_out_end = "23:59"
            grace = 15

        sched = WorkerSchedule(
            id=uuid.uuid4(),
            worker_id=worker.id,
            ward_id=ward.id,
            route_id=None,
            days_of_week=days,
            shift_start_time=shift_start,
            shift_end_time=shift_end,
            check_in_start_time=check_in_start,
            check_in_end_time=check_in_end,
            check_out_start_time=check_out_start,
            check_out_end_time=check_out_end,
            grace_period_minutes=grace,
            timezone="Asia/Kolkata",
            effective_from=date(2026, 1, 1),
            is_active=True,
        )
        session.add(sched)
        session.flush()
        summary["schedule"] = {"id": str(sched.id), "action": "CREATED"}
        logger.info("Created active schedule (%s): id=%s", schedule_mode, sched.id)

    if dry_run:
        logger.info("[DRY RUN] All checks passed. Rolling back session changes.")
        session.rollback()

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Idempotent administrative provisioning tool for NammaClean pilot worker."
    )
    parser.add_argument(
        "--db-url",
        dest="db_url",
        default=None,
        help="Target database sync connection URL (overrides .env / settings.sync_database_url).",
    )
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        default=False,
        help="Explicit confirmation required when targeting a non-local/production database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Perform all lookups, conflict validations, and planning without committing changes.",
    )
    parser.add_argument(
        "--update-password",
        action="store_true",
        default=False,
        help="Allow updating an existing worker's password. If omitted, existing worker password is preserved.",
    )
    parser.add_argument(
        "--schedule-mode",
        choices=["pilot-24x7", "canonical-morning"],
        default="pilot-24x7",
        help="Schedule configuration to apply if creating schedule (default: pilot-24x7 for all-hour testing).",
    )
    parser.add_argument(
        "--password-from-env",
        action="store_true",
        default=False,
        help="Read worker password from WORKER_INITIAL_PASSWORD environment variable rather than prompting.",
    )

    args = parser.parse_args()

    # Determine database URL securely
    target_db_url = args.db_url or settings.sync_database_url
    if not target_db_url:
        print("Error: No database URL configured. Provide --db-url or configure environment settings.")
        sys.exit(1)

    # Normalize driver prefix for sync SQLAlchemy
    if target_db_url.startswith("postgres://"):
        target_db_url = target_db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif target_db_url.startswith("postgresql://") and not target_db_url.startswith("postgresql+psycopg2://"):
        target_db_url = target_db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    # Safety check: enforce --confirm-production if non-local
    is_prod = is_production_database_url(target_db_url)
    if is_prod and not args.confirm_production and not args.dry_run:
        print("\n" + "=" * 70)
        print("SECURITY ABORT:")
        print("Target database appears to be non-local or production.")
        print("To prevent accidental writes, you MUST pass --confirm-production.")
        print("Or use --dry-run to inspect the plan safely.")
        print("=" * 70 + "\n")
        sys.exit(2)

    # Check if worker already exists to avoid unnecessary password prompts when not updating
    worker_already_exists = False
    try:
        engine_check = create_engine(target_db_url, pool_pre_ping=True)
        with Session(engine_check) as chk_sess:
            norm_email = normalize_email(PILOT_WORKER_EMAIL)
            stmt = select(User).where(User.email == norm_email)
            worker_already_exists = chk_sess.execute(stmt).scalars().first() is not None
        engine_check.dispose()
    except Exception as exc:
        logger.warning("Could not pre-check worker existence: %s", exc)

    # Resolve worker password securely (prompt only if creating new worker or explicitly updating password)
    password: Optional[str] = None
    needs_password = (not worker_already_exists) or args.update_password

    if needs_password and not args.dry_run:
        if args.password_from_env:
            password = os.environ.get("WORKER_INITIAL_PASSWORD")
            if not password:
                print("Error: --password-from-env was specified, but WORKER_INITIAL_PASSWORD is not set.")
                sys.exit(1)
        else:
            try:
                prompt_label = (
                    "Enter NEW password for existing worker (min 12 chars): "
                    if worker_already_exists
                    else "Enter password for initial sanitation worker (min 12 chars): "
                )
                password = getpass.getpass(prompt_label)
                confirm = getpass.getpass("Confirm password: ")
                if password != confirm:
                    print("Error: Passwords do not match.")
                    sys.exit(1)
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                sys.exit(1)
    elif worker_already_exists and not args.update_password:
        logger.info("Worker account exists. Preserving current password (pass --update-password to override).")

    if password:
        try:
            validate_password_policy(password)
        except ValueError as err:
            print(f"Error: {err}")
            sys.exit(1)

    # Execute inside transaction
    engine = create_engine(target_db_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            try:
                summary = provision_pilot_worker(
                    session,
                    worker_password=password,
                    update_password=args.update_password,
                    schedule_mode=args.schedule_mode,
                    dry_run=args.dry_run,
                )
                if not args.dry_run:
                    session.commit()
                    print("\n[SUCCESS] Pilot worker provisioned/verified successfully:")
                else:
                    print("\n[DRY RUN COMPLETE] Simulated provisioning plan:")

                for entity, details in summary.items():
                    print(f"  - {entity.upper()}: {details.get('action')} (ID: {details.get('id')})")
            except Exception as exc:
                session.rollback()
                print(f"\n[ERROR] Provisioning failed and was rolled back cleanly: {exc}")
                sys.exit(3)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
