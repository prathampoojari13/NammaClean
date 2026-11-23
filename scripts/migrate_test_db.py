"""Safely migrate the existing NammaClean regression test database."""

import argparse
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.core.config import settings

TEST_DB_HOST = "localhost"
TEST_DB_PORT = 5433
TEST_DB_NAME = "nammaclean_test_db"
START_REVISION = "e5a19cb28df4"
TARGET_REVISION = "b7e4d2c9f1a8"
CONFIRMATION_PHRASE = (
    f"MIGRATE {TEST_DB_NAME} FROM {START_REVISION} TO {TARGET_REVISION}"
)

REQUIRED_COLUMNS = {
    "users": {"ward_id", "locality", "address"},
    "muster_points": {"id", "ward_id", "name", "location"},
    "attendance_records": {
        "id",
        "worker_id",
        "ward_id",
        "attendance_date",
        "status",
    },
    "attendance_qr_tokens": {
        "id",
        "token_hash",
        "muster_point_id",
        "ward_id",
        "expires_at",
    },
}


def _test_database_url() -> URL:
    url = URL.create(
        "postgresql+psycopg2",
        username=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
    )
    if (url.host, url.port, url.database) != (
        TEST_DB_HOST,
        TEST_DB_PORT,
        TEST_DB_NAME,
    ):
        raise RuntimeError("Refusing migration: target URL is not the dedicated test database.")
    return url


def _verify_identity_and_revision(
    connection: Connection,
    expected_revision: str,
) -> None:
    url = connection.engine.url
    if (url.host, url.port, url.database) != (
        TEST_DB_HOST,
        TEST_DB_PORT,
        TEST_DB_NAME,
    ):
        raise RuntimeError(
            "Refusing migration: connected URL is not localhost:5433/nammaclean_test_db."
        )

    database_name = connection.execute(
        text("SELECT current_database()")
    ).scalar_one()
    if database_name != TEST_DB_NAME:
        raise RuntimeError(
            f"Refusing migration: connected database is {database_name!r}, not {TEST_DB_NAME!r}."
        )

    revisions = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalars().all()
    if revisions != [expected_revision]:
        raise RuntimeError(
            f"Refusing migration: expected revision {expected_revision!r}, found {revisions!r}."
        )

    postgis_available = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
    ).scalar_one()
    if not postgis_available:
        raise RuntimeError(
            "Refusing migration: PostGIS is not installed in the target database."
        )


def _verify_required_schema(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN (
                  'users',
                  'muster_points',
                  'attendance_records',
                  'attendance_qr_tokens'
              )
            """
        )
    )
    actual_columns: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        actual_columns.setdefault(table_name, set()).add(column_name)

    missing = {
        table: sorted(columns - actual_columns.get(table, set()))
        for table, columns in REQUIRED_COLUMNS.items()
        if columns - actual_columns.get(table, set())
    }
    if missing:
        raise RuntimeError(
            f"Post-migration schema verification failed; missing columns: {missing!r}."
        )


def _migrate() -> None:
    engine = create_engine(_test_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            _verify_identity_and_revision(connection, START_REVISION)
            connection.rollback()

            print(f"Preflight passed for {TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}.")
            print(f"Starting revision: {START_REVISION}; target revision: {TARGET_REVISION}.")
            phrase = input("Type the exact migration confirmation phrase: ").strip()
            if phrase != CONFIRMATION_PHRASE:
                raise RuntimeError("Confirmation phrase did not match; no migration was run.")

            with connection.begin():
                connection.execute(
                    text("LOCK TABLE alembic_version IN ACCESS EXCLUSIVE MODE")
                )
                _verify_identity_and_revision(connection, START_REVISION)

                alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
                alembic_config.attributes["connection"] = connection
                alembic_config.attributes["require_external_connection"] = True
                command.upgrade(alembic_config, TARGET_REVISION)

                _verify_identity_and_revision(connection, TARGET_REVISION)
                _verify_required_schema(connection)
    finally:
        engine.dispose()

    print(
        f"Migration verified: {TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME} "
        f"is at {TARGET_REVISION} with the required schema."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Require a second exact-phrase confirmation after database preflight.",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("migration is disabled unless --confirm is supplied")

    _migrate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
