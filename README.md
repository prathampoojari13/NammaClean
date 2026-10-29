# NammaClean (ನಮ್ಮಕ್ಲೀನ್)

A real-world oriented, evidence-based municipal solid waste management and fleet monitoring platform for Bengaluru.

Designed to connect citizens, sanitation workers (*Pourakarmikas*), ward supervisors, and BBMP municipal officials with live collection vehicle tracking, route monitoring, shift management, and spatial analytics.

---

## Architecture & Technology Stack

- **Runtime**: Python 3.12.10
- **Framework**: FastAPI (Asynchronous ASGI)
- **Database**: PostgreSQL 16 + PostGIS 3.4 (Geospatial extension) via Docker Compose
- **ORM / Migrations**: SQLAlchemy 2.x (Async) + Alembic (Sync)
- **Validation & Settings**: Pydantic v2 & Pydantic-Settings
- **Testing**: Pytest & pytest-asyncio with HTTPX

### Dedicated Port Allocation
To avoid collisions with other existing PostgreSQL instances (such as MigrationGuard on port 5432), NammaClean uses a dedicated host port:

| Service | Host Port | Container Port | Service / Database |
| :--- | :--- | :--- | :--- |
| **NammaClean PostGIS** | `5433` | `5432` | `nammaclean_db` |
| **NammaClean FastAPI** | `8000` | N/A (Host) | ASGI Application |

---

## Quickstart Guide

### 1. Prerequisites
- Python 3.12 (`py -3.12`)
- Docker Desktop running

### 2. Start the PostGIS Database
Start the isolated PostgreSQL + PostGIS container:
```powershell
docker compose up -d
```
Verify container status:
```powershell
docker ps
```
The container `nammaclean_postgis` should show as `Up` and `(healthy)` on port `5433->5432`.

### 3. Environment Setup
The project includes a pre-configured `.env.example`.
If setting up on a new machine:
```powershell
Copy-Item .env.example .env
```
Activate the virtual environment:
```powershell
.\.venv\Scripts\Activate.ps1
```

### 4. Running the Development Server
Launch FastAPI with hot-reloading:
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Then visit:
- **Root Welcome**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Interactive Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Health Check & DB Ping**: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

### 5. Running Automated Tests
Run tests using Python 3.12:
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

---

## Project Structure

```text
NammaClean/
├── .env.example             # Safe environment variable template (untracked: .env)
├── .gitignore               # Excludes .venv, .env, __pycache__, and caches
├── docker-compose.yml       # PostGIS 16-3.4 container configuration on port 5433
├── requirements.txt         # Pinned Python 3.12 dependencies
├── pytest.ini               # Pytest asyncio configuration
├── alembic.ini              # Alembic database migration config
├── alembic/                 # Database migration versions and environments
├── app/
│   ├── main.py              # FastAPI application entrypoint & lifespan
│   ├── core/
│   │   ├── config.py        # Pydantic BaseSettings loading from .env
│   │   └── database.py      # Async SQLAlchemy engine & PostGIS connection check
│   └── api/
│       └── v1/
│           ├── router.py    # V1 API router aggregator
│           └── health.py    # GET /api/v1/health with DB & PostGIS ping
└── tests/
    ├── conftest.py          # Pytest async client fixtures
    └── test_health.py       # API and database connectivity tests
```

---

## Verifiable Milestones

- [x] **Stage 1**: Foundation & Infrastructure (FastAPI, PostGIS container on port 5433, async engine, health endpoint, automated tests).
- [ ] **Stage 2**: Role-Based Access Control (RBAC) & Authentication (Citizens, Pourakarmikas, Ward Supervisors, BBMP Admins).
- [ ] **Stage 3**: Spatial Modeling of Bengaluru Wards & Collection Points (GeoJSON boundaries, PostGIS geometries).
- [ ] **Stage 4**: Vehicle Fleet & Daily Worker Shifts.
- [ ] **Stage 5**: Live Vehicle Telemetry Ingestion & Citizen Proximity Alerts.
- [ ] **Stage 6**: Evidence-Based Collection Auditing & Blackspot Reporting.
- [ ] **Stage 7**: Operational Dashboards, Delay Alerts & Research Evaluation Metrics.
