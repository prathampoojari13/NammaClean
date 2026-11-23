# NammaClean (ನಮ್ಮಕ್ಲೀನ್)

A real-world oriented, evidence-based municipal solid waste management and fleet monitoring platform for Bengaluru.

Designed to connect citizens, sanitation workers (*Pourakarmikas*), ward supervisors, and BBMP municipal officials with live collection vehicle tracking, route monitoring, shift management, and spatial analytics.

---

## 🏛️ Architecture & Technology Stack

### Frontend
- **Framework**: React 18 with TypeScript and Vite
- **Routing**: React Router DOM v6 with SPA client-side routing & deep-link fallbacks
- **Maps**: Leaflet & OpenStreetMap / CartoDB / Esri Satellite imagery
- **Styling & UI**: Tailwind-inspired responsive CSS with Lucide React iconography
- **State & Storage**: Resilient localStorage token recovery and live role-based route protection

### Backend
- **Runtime**: Python 3.12 (ASGI)
- **Framework**: FastAPI with asynchronous endpoints
- **Database**: PostgreSQL 16 with PostGIS 3.4 (Geospatial extension)
- **ORM & Migrations**: SQLAlchemy 2.x (Asyncpg) + Alembic (Psycopg2)
- **Security**: Argon2 password hashing (pwdlib), JWT authentication, strict role-based authorization
- **Testing**: Pytest & Python standard unittest suites (380+ tests)

---

## 🚀 Quickstart Guide (Local Development)

### 1. Prerequisites
- Python 3.12+
- Node.js 20+ and npm
- Docker Desktop (for local PostgreSQL + PostGIS)

### 2. Start Database
```powershell
docker compose up -d
```
Container `nammaclean_postgis` binds to port `5433` (mapped to container port `5432`) to avoid port collisions.

### 3. Setup Backend
```powershell
# Copy environment configuration
Copy-Item .env.example .env

# Install backend dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run migrations
.\.venv\Scripts\python.exe -m alembic upgrade head

# Run development server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 4. Setup Frontend
```powershell
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## 🌐 Production Deployment

### Recommended Architecture
1. **Frontend**: [Vercel](https://vercel.com) or [Netlify](https://netlify.com)
2. **Backend**: [Render](https://render.com) or [Railway](https://railway.app)
3. **Database**: Managed PostgreSQL with PostGIS (e.g. Render PostGIS, Supabase, Neon, or Railway)

### 1. Deploying the Backend on Render
The repository includes a ready-to-use `render.yaml` blueprint:
1. Log in to [Render](https://dashboard.render.com).
2. Click **New +** > **Blueprint**.
3. Connect your GitHub repository (`prathampoojari13/NammaClean`).
4. Render automatically configures:
   - Python Web Service running `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Pre-deploy command: `pip install -r requirements.txt && alembic upgrade head`
   - Health check: `/api/v1/health/live`
   - PostGIS-enabled PostgreSQL database instance
5. Add your production frontend URL to `BACKEND_CORS_ORIGINS`.

### 2. Deploying the Frontend on Vercel
1. Log in to [Vercel](https://vercel.com).
2. Click **Add New Project** and select your GitHub repository.
3. Configure the build settings:
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
4. Set Environment Variables:
   - `VITE_API_BASE_URL`: `https://<your-backend-domain>/api/v1`
5. Click **Deploy**. SPA routing and deep links work automatically via `frontend/vercel.json` and `frontend/public/_redirects`.

---

## ⚙️ Environment Variables Reference

### Backend (`.env`)
| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `APP_NAME` | Name of the platform | `NammaClean` |
| `APP_ENV` | Environment (`development`, `production`, `testing`) | `development` |
| `APP_DEBUG` | Enable debug logs | `true` in dev, `false` in prod |
| `API_V1_STR` | API prefix | `/api/v1` |
| `BACKEND_CORS_ORIGINS` | Allowed frontend origins (comma-separated or JSON list) | `["http://localhost:5173","https://nammaclean.vercel.app"]` |
| `DATABASE_URL` | Cloud database URL (overrides discrete POSTGRES_* settings) | `postgresql://user:pass@host:5432/nammaclean_db` |
| `POSTGRES_HOST` | Database host (local Docker) | `localhost` |
| `POSTGRES_PORT` | Database port (local Docker) | `5433` |
| `POSTGRES_DB` | Database name | `nammaclean_db` |
| `POSTGRES_USER` | Database username | `nammaclean_admin` |
| `POSTGRES_PASSWORD` | Database password | Secure secret |
| `JWT_SECRET_KEY` | Secret key for signing JWT tokens | 32+ byte random string |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token validity duration | `30` |
| `SIMULATION_ENABLED` | Simulated vehicle movement | `false` |
| `EVIDENCE_STORAGE_PATH` | Local file uploads directory | `data/uploads/evidence` |

### Frontend (`frontend/.env`)
| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `VITE_API_BASE_URL` | Base URL of the FastAPI backend | `http://localhost:8000/api/v1` (dev), `https://api.yourdomain.com/api/v1` (prod) |

---

## 🧪 Automated Testing & CI/CD

Continuous Integration is configured via GitHub Actions (`.github/workflows/ci.yml`). On every push to `main` and pull request:
- **Backend Tests**: Executes Python test suite.
- **Frontend Tests**: Executes Leaflet, authentication, and contract tests (`npm test`).
- **Production Build Check**: Compiles TypeScript and builds Vite bundle (`npm run build`).

To run tests locally:
```powershell
# Frontend contract tests (40 contracts)
npm --prefix frontend test

# Frontend production build
npm --prefix frontend run build

# Backend tests
.\.venv\Scripts\python.exe -m unittest tests/test_attendance_otp_dev.py tests/test_attendance_models.py -v
```

---

## ⚠️ Operational & Pilot Scope Disclaimers

1. **BMSIT&M / Yelahanka Pilot Scope**:
   Live spatial modeling and automated muster points are calibrated for the Yelahanka – Avalahalli corridor (Ward 4, BMSIT&M campus perimeter). City-wide expansion utilizes OpenStreetMap bounding extents for Bengaluru.
2. **Simulated Telemetry**:
   BBMP collection vehicle telemetry and route sweeps reflect simulated GPS feeds designed to match BBMP operational specifications.
3. **Development OTP Delivery**:
   Sanitation worker roll-call OTP verification is configured in development mode with local verification cards. Production deployments can connect directly to an external SMS/SMTP gateway.

---

## 📷 Media & Asset Attributions

The Vidhana Soudha (Bengaluru) photograph used for the citizen dashboard banner and authentication backdrop is by iMahesh and is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- Source: [Vidhana Soudha (Bengaluru) - Panoramic view](https://commons.wikimedia.org/wiki/File:Vidhana_Soudha_(Bengaluru)_-_Panoramic_view.jpg)
- Assets: `frontend/public/assets/vidhana-soudha-bengaluru.jpg` and `frontend/public/assets/vidhana-soudha-login.jpg`
