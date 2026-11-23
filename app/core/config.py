import json
from typing import Optional, Literal, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application and infrastructure configuration loaded from environment variables."""

    # General App Config
    APP_NAME: str = "NammaClean"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # CORS Origins (configurable list of allowed client origins)
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, list[str]]) -> list[str]:
        if isinstance(v, str):
            v_trimmed = v.strip()
            if v_trimmed.startswith("[") and v_trimmed.endswith("]"):
                try:
                    parsed = json.loads(v_trimmed)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [origin.strip() for origin in v_trimmed.split(",") if origin.strip()]
        return v

    # Database Configuration (Host port 5433 by default for Docker PostGIS)
    DATABASE_URL: Optional[str] = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433
    POSTGRES_DB: str = "nammaclean_db"
    POSTGRES_USER: str = "nammaclean_admin"
    POSTGRES_PASSWORD: str = ""

    # Security & JWT Configuration (Secrets loaded from .env without insecure fallbacks)
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0, le=10080)

    # Controlled GPS Simulation Engine & Map Data Controls
    SIMULATION_ENABLED: bool = False
    VEHICLE_FRESHNESS_MINUTES: int = 15

    # Evidence Storage Configuration (Local filesystem storage for development)
    EVIDENCE_STORAGE_PATH: str = "data/uploads/evidence"
    MAX_EVIDENCE_FILE_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB limit

    # Pilot Operational Area & Bengaluru City-Wide Map Configuration
    PILOT_ACTIVE: bool = True
    PILOT_ZONE_NAME: str = "Yelahanka – Avalahalli (BMSIT&M)"
    PILOT_WARD_CODE: str = "BBMP-W004"
    PILOT_WARD_NAME: str = "Ward 4 - Yelahanka Satellite Town & Avalahalli Corridor"
    PILOT_CENTER_LAT: float = 13.1331
    PILOT_CENTER_LON: float = 77.5685
    PILOT_DEFAULT_GEOFENCE_METERS: int = 150
    BENGALURU_CENTER_LAT: float = 12.9716
    BENGALURU_CENTER_LON: float = 77.5946
    BENGALURU_DEFAULT_ZOOM: int = 12





    # Async Database URL (used by FastAPI asyncpg)
    @property
    def async_database_url(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Sync Database URL (used by Alembic migrations with psycopg2)
    @property
    def sync_database_url(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg2://", 1)
            elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
