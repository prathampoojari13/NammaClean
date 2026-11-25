"""
Pre-deployment execution script for NammaClean on Render / Cloud.
Safely ensures PostGIS extension is installed and runs Alembic migrations
during the pre-deploy stage rather than during image build.
"""
import sys
import logging
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from alembic.config import Config
from alembic import command
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pre_deploy")


def run_pre_deploy() -> None:
    db_url = settings.sync_database_url
    logger.info("Initializing pre-deploy database checks...")

    # 1. Connect to sync database URL and ensure PostGIS extension is enabled
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            logger.info("Verifying/Enabling PostGIS extension...")
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            result = conn.execute(
                text("SELECT extname, extversion FROM pg_extension WHERE extname = 'postgis';")
            ).fetchone()
            if result:
                logger.info(f"PostGIS extension verified: {result[0]} (version {result[1]})")
            else:
                logger.warning("PostGIS extension query did not return a row.")
    except Exception as exc:
        logger.error(f"Failed while configuring PostGIS extension: {exc}")
        raise
    finally:
        engine.dispose()

    # 2. Run Alembic migrations to head
    logger.info("Running database migrations (alembic upgrade head)...")
    try:
        alembic_ini_path = str(PROJECT_ROOT / "alembic.ini")
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully.")
    except Exception as exc:
        logger.error(f"Failed during Alembic migration upgrade: {exc}")
        raise


if __name__ == "__main__":
    run_pre_deploy()
