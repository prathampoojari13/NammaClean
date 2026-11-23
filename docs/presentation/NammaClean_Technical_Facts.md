# NammaClean — Technical Facts & System Specification
**Project Reference Manual for Evaluation Committee & Technical Inquiries**  
**Repository**: `D:\DOCUMENT !!\FULL STACK DEVELOPMENT\NammaClean`  
**Pilot Domain**: Yelahanka (Ward 0004), Bengaluru, Karnataka  
**Academic Institution**: BMS Institute of Technology and Management (BMSIT&M), Bengaluru  

---

## 1. Verified Technology Stack & Library Versions

All libraries and versions have been directly verified from `frontend/package.json` and `requirements.txt`:

### A. Frontend Tier
| Technology / Package | Verified Version | Purpose in NammaClean |
| :--- | :---: | :--- |
| **React** | `18.3.1` | Declarative component hierarchy and state management |
| **TypeScript** | `5.6.3` | Strict static typing, contract interfaces, and zero-defect builds |
| **Vite** | `5.4.11` | Optimized ES module bundler, tree-shaking, and HMR server |
| **Leaflet** | `1.9.4` | Interactive geospatial mapping, tile rendering, and vehicle markers |
| **Lucide React** | `0.460.0` | Accessible, tree-shakeable SVG civic iconography |
| **React Router DOM** | `6.28.0` | Client-side routing, route guards, and role-based redirecting |
| **Vanilla CSS System** | Custom CSS3 | Civic design system (`citizen-dashboard.css`) with zero third-party UI overhead |

### B. Backend API Tier
| Technology / Package | Verified Version | Purpose in NammaClean |
| :--- | :---: | :--- |
| **Python** | `3.12.10` | Core language runtime |
| **FastAPI** | `0.115.6` | High-performance asynchronous ASGI web framework |
| **Uvicorn** | `0.34.0` | Asynchronous ASGI HTTP server |
| **Pydantic** | `2.10.4` | Data validation, request/response schema parsing, and boundary enforcement |
| **Pydantic-Settings** | `2.7.0` | Environment configuration management with strict typing |
| **pwdlib[argon2]** | `0.3.1` | Secure password hashing using Argon2id algorithm |
| **PyJWT** | `2.15.1` | Cryptographic JSON Web Token encoding, decoding, and expiry checks |

### C. Database & Spatial Persistence Tier
| Technology / Package | Verified Version | Purpose in NammaClean |
| :--- | :---: | :--- |
| **PostgreSQL** | `16` | ACID-compliant relational persistence |
| **PostGIS Extension** | `3.4.3` | Native spatial data types, spatial indexing (R-Tree), and spatial SQL functions |
| **SQLAlchemy** | `2.0.36` | Asynchronous ORM and SQL query construction |
| **asyncpg** | `0.30.0` | High-throughput asynchronous PostgreSQL driver |
| **psycopg2-binary** | `2.9.10` | Synchronous PostgreSQL driver utilized for Alembic migrations |
| **GeoAlchemy2** | `0.17.0` | SQLAlchemy spatial extension for PostGIS geometry types (`WKTElement`) |
| **Shapely** | `2.0.6` | Computational geometry operations on spatial coordinates |
| **Alembic** | `1.14.0` | Schema migration tracking and revision rollouts |

### D. Automated Testing Frameworks
| Technology / Package | Verified Version | Purpose in NammaClean |
| :--- | :---: | :--- |
| **Pytest** | `8.3.4` | Backend test runner |
| **pytest-asyncio** | `0.25.0` | Asynchronous test execution for FastAPI endpoints |
| **HTTPX** | `0.28.1` | Async HTTP client for integration and contract tests |
| **Node.js Test Runner** | `v20+` Native | Zero-dependency contract test runner for frontend interfaces |

---

## 2. System Architecture & Component Mapping

```text
                                 [ BROWSER CLIENTS ]
             ┌───────────────────────────┼───────────────────────────┐
             │                           │                           │
             ▼                           ▼                           ▼
    [ Citizen Dashboard ]       [ Supervisor Portal ]       [ Worker Portal ]
    - 4 Summary Cards           - Operations Roster         - OTP Verification
    - Live Telemetry Map        - Complaint Triage          - 150m Geofence
    - Dumping Reports Modal     - 5-Min Roll-Call QR        - Digital Worker ID
             │                           │                           │
             └───────────────────────────┼───────────────────────────┘
                                         │  HTTPS / REST / JSON
                                         ▼
                             [ FastAPI ASGI ENGINE ]
                  (app.main:app on 127.0.0.1:8000 via Uvicorn)
      ┌──────────────────────────────────┴──────────────────────────────────┐
      │                                                                     │
      ▼                                                                     ▼
[ Security & Middleware ]                                          [ Modular API Routers ]
- OAuth2 Password Bearer                                           - /auth & /users
- JWT Token Validator                                              - /public/map (Vehicles, Summary)
- Argon2id Password Hasher                                         - /reports (Incident Tracking)
- Role Dependency Guards                                           - /attendance (OTP, QR, Roster)
      │                                                                     │
      └──────────────────────────────────┬──────────────────────────────────┘
                                         │  SQLAlchemy 2.0 Async (asyncpg)
                                         ▼
                       [ POSTGRESQL 16 + POSTGIS 3.4.3 ]
                         (nammaclean_db on port 5433)
      ┌──────────────────────────────────┴──────────────────────────────────┐
      │                                                                     │
      ▼                                                                     ▼
[ Relational Tables ]                                              [ Spatial Geometry Columns ]
- users (Roles, Status, Wards)                                     - vehicles.current_location (Point)
- dumping_reports (Status, History)                                - collection_routes.route_path (LineString)
- attendance_records (Timestamps)                                  - muster_points.location (Point)
- attendance_qr_tokens (Tokens)                                    - wards.boundary (Polygon)
```

---

## 3. Database Schema & Spatial Entity Specifications

All geometries are defined in standard **WGS 84 coordinate reference system (SRID 4326)**:

| Table Name | Primary Key | Key Columns & Spatial Attributes | Constraints & Indexes |
| :--- | :--- | :--- | :--- |
| `wards` | `id` (UUID) | `ward_code` (VARCHAR 50), `display_name`, `boundary: Geometry(Polygon, 4326)` | Unique index on `ward_code`; GIST index on `boundary` |
| `users` | `id` (UUID) | `email` (VARCHAR 255), `password_hash`, `role` (VARCHAR 30), `ward_id` (UUID FK), `locality` | Unique index on `email`; Check constraint on `role` and `status` |
| `user_ward_assignments` | `id` (UUID) | `user_id` (UUID FK), `ward_id` (UUID FK), `assigned_at`, `revoked_at` | Composite index on `user_id, ward_id` |
| `vehicles` | `id` (UUID) | `registration_number` (VARCHAR 50), `vehicle_type`, `status`, `assigned_ward_id` (FK), `current_location: Geometry(Point, 4326)`, `is_simulated` (BOOL), `last_seen_at` | Unique index on `registration_number`; GIST index on `current_location` |
| `collection_points` | `id` (UUID) | `ward_id` (FK), `name`, `point_type`, `location: Geometry(Point, 4326)`, `is_active` | GIST index on `location` |
| `collection_routes` | `id` (UUID) | `ward_id` (FK), `name`, `route_code`, `route_path: Geometry(LineString, 4326)`, `is_published` | Unique index on `route_code`; GIST index on `route_path` |
| `route_stops` | `id` (UUID) | `route_id` (FK), `collection_point_id` (FK), `stop_sequence` (INT) | Composite unique constraint on `(route_id, stop_sequence)` |
| `dumping_reports` | `id` (UUID) | `reporter_id` (FK), `ward_id` (FK), `location: Geometry(Point, 4326)`, `description` (TEXT), `status`, `official_notes` | GIST index on `location`; Check constraint on `status` |
| `muster_points` | `id` (UUID) | `ward_id` (FK), `name`, `location: Geometry(Point, 4326)`, `geofence_radius_meters` (FLOAT = 150.0), `is_active` | GIST index on `location` |
| `attendance_records` | `id` (UUID) | `worker_id` (FK), `muster_point_id` (FK), `ward_id` (FK), `attendance_date` (DATE), `check_in_at`, `check_out_at`, `status`, `is_geofence_verified` | Unique constraint on `(worker_id, attendance_date)` |
| `attendance_qr_tokens` | `id` (UUID) | `muster_point_id` (FK), `token_hash` (VARCHAR 64), `created_at`, `expires_at`, `is_redeemed`, `redeemed_by_id` | Index on `token_hash` |

---

## 4. API Endpoints Catalog

### Public & Citizen Endpoints
* `GET /api/v1/health` — Database and PostGIS extension ping.
* `POST /api/v1/auth/register` — Citizen registration (`role = CITIZEN`).
* `POST /api/v1/auth/login` — OAuth2 token issuance (returns JWT Bearer token).
* `GET /api/v1/users/me` — Authenticated user profile and assigned ward/locality.
* `GET /api/v1/public/map/summary` — Operational metrics (active vehicles, collection points, routes).
* `GET /api/v1/public/map/vehicles` — Vehicle telemetry with simulation status and coordinates.
* `GET /api/v1/public/map/routes` — Published waste collection corridors (GeoJSON LineStrings).
* `POST /api/v1/reports` — Citizen illegal dumping incident submission.
* `GET /api/v1/reports/my` — Personal complaint history for the authenticated citizen.

### BBMP Official / Supervisory Endpoints
* `GET /api/v1/reports` — Ward-filtered complaint list (Role: `WARD_SUPERVISOR`, `MUNICIPAL_ADMIN`).
* `PATCH /api/v1/reports/{id}/status` — Status transition (`UNDER_REVIEW`, `ACTION_SCHEDULED`, `RESOLVED`, `REJECTED`).
* `POST /api/v1/wards/{ward_id}/muster-points/{muster_point_id}/qr-code` — Generate 5-minute single-use roll-call QR.
* `GET /api/v1/attendance/daily` — Ward attendance roster with geofence exception tracking.

### Pourakarmika / Worker Endpoints
* `GET /api/v1/attendance/worker-assignment` — Worker assigned ward, muster station, and route details.
* `GET /api/v1/attendance/my-today` — Today's attendance status and timestamps.
* `POST /api/v1/attendance/request-otp` — Issue single-use 6-digit verification code (5-minute TTL).
* `POST /api/v1/attendance/verify-otp` — Submit OTP with device GPS coordinates; verifies 150m geofence.
* `POST /api/v1/attendance/check-out` — Record shift completion and calculate total shift hours.

---

## 5. Security & Verification Parameters (Verified in Code)

| Security Domain | Exact Implementation Parameter | Source File |
| :--- | :--- | :--- |
| **Password Hashing** | Argon2id (`memory_cost=65536, time_cost=3, parallelism=4`) | `app/core/security.py` |
| **JWT Algorithm** | HMAC-SHA256 (`HS256`), configurable token lifetime | `app/core/security.py` |
| **OTP Length** | Exactly 6 numeric digits (`secrets.randbelow`) | `app/services/otp_service.py:18` |
| **OTP Lifetime** | Exactly **300 seconds (5 minutes)** | `app/services/otp_service.py:19` |
| **OTP Storage** | Salted SHA-256 hash (`hashlib.sha256(salt + otp).hexdigest()`) | `app/services/otp_service.py:32` |
| **OTP Attempts** | Maximum **3 verification attempts** before challenge invalidation | `app/services/otp_service.py:20` |
| **OTP Rate Limiting** | **30 seconds cooldown** between issuance requests per worker | `app/services/otp_service.py:21` |
| **Geofence Radius** | Exactly **150.0 meters** around muster point | `app/models/attendance.py:34` |
| **Geofence Query** | PostGIS `ST_DWithin(worker_location, muster_location, 150.0)` | `app/services/attendance_service.py` |
| **QR Code Lifetime** | Exactly **300 seconds (5 minutes)** single-use token | `app/services/attendance_service.py` |
| **RBAC Enforcement** | FastAPI dependency `require_roles(...)` returning `HTTP 403` | `app/api/deps.py` |

---

## 6. Testing & Build Verification Evidence

```text
================================ TEST EXECUTION SUMMARY ================================
1. Frontend Contract Tests:       31 passed, 0 failed in 3.85s (Node.js test runner)
2. Frontend Production Build:     Built in 2.35s (tsc -b && vite build) - 0 errors
3. Backend Pytest Suite:          370 passed, 0 failed in 19.78s (Pytest 8.3.4)
4. Live Citizen Dashboard Audit:  15/15 passed (100% success)
5. Live Role Dashboard Audit:     13/13 passed (100% success)
========================================================================================
```

---

## 7. Disclosed Limitations & Academic Scope

1. **Telemetry Simulation**: Vehicle coordinates are streamed by an internal simulation engine (`is_simulated = True`) along verified route paths. The platform does not currently connect to physical hardware GPS units installed on BBMP collection trucks.
2. **Local OTP Transport**: In this offline test environment, OTP codes are logged to the backend console and test scratchpad (`scratch/dev_latest_otp.txt`) rather than routed through commercial external SMS/SMTP relays.
3. **Pilot Geometry**: The Yelahanka operational boundary represents an approximate spatial corridor around Yelahanka and Avalahalli; it is not an official survey-grade BBMP cadastre.
4. **Tile Provider Dependency**: Standard and satellite map layers load from external CDNs (OpenStreetMap and Esri World Imagery) and require active internet connectivity when un-cached.
5. **Municipal Governance**: The application is an independent academic capstone project developed at BMSIT&M and is not an officially endorsed BBMP product.
