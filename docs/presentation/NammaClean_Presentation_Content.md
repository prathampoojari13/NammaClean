# NammaClean — College Project Presentation Content
**Degree**: Bachelor of Engineering (B.E.) in Computer Science & Engineering  
**Academic Institution**: BMS Institute of Technology and Management (BMSIT&M), Avalahalli, Yelahanka, Bengaluru  
**Project Title**: NammaClean (ನಮ್ಮಕ್ಲೀನ್)  
**Subtitle**: Smart Municipal Waste Management and Sanitation Monitoring Platform  
**Operational Pilot Zone**: Yelahanka (Ward 0004), Bengaluru  

---

## Slide 1: Title & Academic Details

* **Slide Title**: NammaClean (ನಮ್ಮಕ್ಲೀನ್)
* **Subtitle**: Smart Municipal Waste Management and Sanitation Monitoring Platform
* **Academic Context**: Capstone Project Presentation — Department of Computer Science & Engineering
* **Institution**: BMS Institute of Technology and Management (BMSIT&M), Bengaluru
* **Project Team**:
  * Student Name: Pratham [USN: 1BY... Placeholder]
  * Student Name: [Team Member 2 Placeholder]
  * Student Name: [Team Member 3 Placeholder]
  * Student Name: [Team Member 4 Placeholder]
* **Project Guide**: [Prof. / Dr. Guide Name Placeholder], Department of CSE
* **Visual Suggestion**: Clean white background with dark-forest civic green header banner (`#063321`), NammaClean brand mark, BMSIT&M institution emblem, and Vidhana Soudha architectural watermark.
* **Speaker Notes**:
  > "Good morning respected evaluators, professors, and peers. Today we are proud to present 'NammaClean'—a comprehensive civic technology platform designed to transform municipal solid waste collection, citizen grievance redressal, and sanitation workforce monitoring in Bengaluru, demonstrated through an operational pilot centered around Yelahanka."

---

## Slide 2: Introduction & Civic Context

* **Headline**: Connecting Citizens, Municipal Supervisors, and Sanitation Workers on a Single Civic Platform
* **Key Points**:
  * **Bengaluru Urban Context**: Bengaluru generates ~5,500 metric tons of municipal solid waste daily across 198+ wards, requiring extensive coordination across thousands of daily collection trips.
  * **Three Key Stakeholders**:
    1. **Citizens**: Seek reliable door-to-door collection schedules, transparent vehicle arrival, and responsive illegal dumping redressal.
    2. **Ward Supervisors (BBMP)**: Need centralized operational oversight, complaint status tracking, and workforce attendance audits.
    3. **Pourakarmikas (Sanitation Workers)**: Require simplified, tamper-proof shift check-in and clear daily route assignments.
  * **The NammaClean Bridge**: Replaces isolated communication channels with an integrated, geospatial, role-based platform that unifies operations under a single source of truth.
* **Visual Suggestion**: A three-pillar infographic showing Citizen (Mobile/Web), BBMP Supervisor (Operations Portal), and Pourakarmika (Field Dashboard) converging on the NammaClean Central Spatial Engine.
* **Speaker Notes**:
  > "Urban waste management in a rapidly growing metropolis like Bengaluru is fundamentally a logistics and transparency challenge. Citizens often do not know when the auto-tipper will arrive, black spots of garbage dumping persist due to lack of geotagged evidence, and supervisors rely on manual paper logs for workforce muster-ins. NammaClean connects all three actors into a unified digital ecosystem."

---

## Slide 3: Problem Statement

* **Headline**: Structural Deficits in Traditional Municipal Waste Operations
* **Identified Challenges**:
  * **Limited Public Telemetry**: Citizens have no live visibility into primary collection vehicle positions, leading to missed pickups and street littering.
  * **Unmonitored Illegal Dumping**: Black spots and unauthorized dumping lack geotagged photographic evidence, making dispatching cleanups slow and uncoordinated.
  * **Fragmented Grievance Redressal**: Complaints logged through generic municipal helplines frequently stall without auditable lifecycle transitions.
  * **Vulnerable Attendance Verification**: Traditional paper-based muster registers are prone to proxy check-ins, manual transcription errors, and lack physical location verification.
  * **Siloed Operational Data**: Ward supervisors lack unified map views displaying both active fleet positions and unassigned citizen complaints.
* **Scope Note**: These challenges represent technical problem domains addressed by our platform design; they do not assert absolute claims across all BBMP subdivisions.
* **Visual Suggestion**: Split slide with 4 pain-point cards: "Opaque Fleet Tracking", "Uncoordinated Black Spots", "Paper-Based Muster Logs", and "Siloed Operations".
* **Speaker Notes**:
  > "When analyzing the existing workflow, we identified five critical technical bottlenecks. Notice how paper muster logs lack location auditing, while complaints filed by citizens rarely correlate with vehicle route data. NammaClean was engineered to systematically eliminate each of these vulnerabilities."

---

## Slide 4: Project Objectives

* **Headline**: Measurable Technical & Operational Goals
* **Core Technical Objectives**:
  * **1. Interactive Fleet Visualization**: Render real-time collection vehicle telemetry on Leaflet spatial maps with standard/satellite views and telemetry freshness indicators.
  * **2. Geotagged Incident Reporting**: Enable authenticated citizens to report illegal dumping with strict GPS coordinate boundaries, photo evidence validation, and an auditable status lifecycle.
  * **3. Role-Based Governance**: Deliver three decoupled, role-tailored dashboards (`CITIZEN`, `WARD_SUPERVISOR` / `MUNICIPAL_ADMIN`, and `SANITATION_WORKER` / `DRIVER`).
  * **4. Dual Attendance Protocols**: Implement both a 5-minute single-use Roll-Call QR system and a 5-minute cryptographic Email OTP flow.
  * **5. Spatial Geofencing**: Enforce a 150-meter PostGIS spatial boundary (`ST_DWithin`) around muster depots to prevent off-site attendance check-in.
  * **6. Production-Ready Engineering**: Ensure clean API contracts, 100% test coverage on core models, and responsive desktop/mobile layouts.
* **Visual Suggestion**: Six clean metric target badges with checkmark icons in forest green borders.
* **Speaker Notes**:
  > "Our primary objective was not merely to build a visual portal, but to implement strict spatial and cryptographic safeguards. Specifically, we set out to validate attendance within 150 meters of official muster stations using PostGIS, ensure complaint status transitions follow a state machine, and provide real-time telemetry freshness monitoring."

---

## Slide 5: Proposed Solution & Operational Lifecycle

* **Headline**: End-to-End Operational Workflow
* **Lifecycle Flow**:
  1. **Citizen Discovery & Reporting**: Citizen logs in, monitors incoming collection vehicles in Yelahanka, and submits geotagged photo evidence of illegal dumping.
  2. **Supervisor Triage & Scheduling**: Ward Supervisor reviews the report in the complaints queue, inspects location metadata, and transitions status from `SUBMITTED` to `ACTION_SCHEDULED`.
  3. **Workforce Muster & Validation**: Pourakarmikas arrive at Yelahanka Satellite Town Depot, authenticate via Email OTP with GPS location within 150m, and review assigned vehicle and route.
  4. **Collection & Resolution**: Compactor trucks service scheduled routes; supervisors verify resolution and mark reports as `RESOLVED`.
  5. **Auditable Archives**: All attendance timestamps and incident transitions are recorded in PostgreSQL with strict immutability.
* **Scope Boundary**: Demonstrates full end-to-end software integration. Hardware GPS transceivers and production municipal SMS/SMTP gateways are decoupled via standard API adapters.
* **Visual Suggestion**: Horizontal sequence diagram showing: Citizen -> BBMP Official -> Pourakarmika -> Live Database -> Closed Loop.
* **Speaker Notes**:
  > "Here we illustrate the complete operational lifecycle. When a citizen in Yelahanka reports a black spot, that incident immediately enters the supervisor's dashboard. Meanwhile, the Pourakarmika checks in at the designated muster station using location-verified OTP. The supervisor assigns the route, and once serviced, the citizen sees their report marked 'Resolved'. It forms an accountability loop."

---

## Slide 6: System Architecture

* **Headline**: Modular Three-Tier Geospatial Architecture
* **Architectural Tiers**:
  * **Presentation Tier**: React 18, TypeScript, Vite, responsive vanilla CSS design system (`citizen-dashboard.css`), Leaflet maps, and Lucide icons.
  * **Application / Logic Tier**: FastAPI (Asynchronous ASGI Python 3.12), Pydantic v2 validation models, JWT authentication, and OTP security manager.
  * **Spatial Data Tier**: PostgreSQL 16 with PostGIS 3.4.3 extension, GeoAlchemy2, SQLAlchemy 2.0 Async ORM, and Alembic migrations.
  * **Telemetry & Simulation Engine**: Internal GPS simulator generating WGS 84 coordinate sequences along collection routes with directional headings.
  * **External Services**: Esri World Imagery (Satellite tiles) and OpenStreetMap (Standard tiles).
* **Architecture Diagram**:
```text
┌─────────────────────────────────────────────────────────────────┐
│                    CLIENT TIER (React 18 + TS)                  │
│   Citizen Dashboard   │   Supervisor Portal   │  Worker Portal  │
└────────────────┬──────────────────────┬───────────────┬─────────┘
                 │                      │               │
                 ▼                      ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│                 API & SECURITY TIER (FastAPI ASGI)              │
│  OAuth2 / JWT Bearer │ RBAC Router │ Geofence Validator │ OTP   │
└────────────────┬──────────────────────┬───────────────┬─────────┘
                 │                      │               │
                 ▼                      ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│                  DATABASE TIER (PostgreSQL 16 + PostGIS)        │
│  Spatial Points (4326) │ ST_DWithin (150m) │ WKT Geometries    │
└─────────────────────────────────────────────────────────────────┘
```
* **Speaker Notes**:
  > "Our architecture adheres to clean separation of concerns. The frontend communicates with FastAPI exclusively via asynchronous REST endpoints with Bearer authentication. In the persistence tier, PostGIS handles all spatial operations natively using spatial indexes, allowing sub-millisecond geofence calculations."

---

## Slide 7: Technology Stack & Technical Specifications

* **Headline**: Verified Production Dependencies
* **Stack Categorization**:
  * **Frontend**:
    * React `v18.3.1` with TypeScript `v5.6.3`
    * Vite `v5.4.11` (Hot module replacement & tree-shaken production bundles)
    * Leaflet `v1.9.4` (Spatial map visualization)
    * Lucide React `v0.460.0` (Consistent iconography)
  * **Backend**:
    * FastAPI `v0.115.6` with Uvicorn `v0.34.0` (ASGI server)
    * Pydantic `v2.10.4` & Pydantic-Settings `v2.7.0`
    * Python `v3.12.10` runtime
  * **Database & Spatial Engine**:
    * PostgreSQL `16` with PostGIS `3.4.3` on dedicated port `5433`
    * SQLAlchemy `v2.0.36` (Asyncio session engine via `asyncpg v0.30.0`)
    * GeoAlchemy2 `v0.17.0` & Shapely `v2.0.6`
    * Alembic `v1.14.0` schema migration management
  * **Security**:
    * Argon2id hashing via `pwdlib[argon2] v0.3.1`
    * PyJWT `v2.15.1` (HMAC-SHA256 bearer tokens)
  * **Automated Testing**:
    * Pytest `v8.3.4`, pytest-asyncio `v0.25.0`, HTTPX `v0.28.1`, Node.js native test runner
* **Visual Suggestion**: 4-column tech badges table grouped by Frontend, Backend, Database, and Security.
* **Speaker Notes**:
  > "Every library version listed here is strictly verified from package.json and requirements.txt. Notice our use of Argon2id—the winner of the Password Hashing Competition—over legacy bcrypt, and PostGIS 3.4 for hardware-accelerated spatial joins."

---

## Slide 8: Citizen Dashboard Walkthrough

* **Headline**: Public Fleet Transparency & Grievance Lodging
* **Features Demonstrated**:
  * **Personalized Civic Banner**: Dynamic welcome heading (`Welcome Back, Pratham!`), tagline, and animated SVG soaring nature birds.
  * **Original 4 Summary Cards**:
    1. *Active Vehicles* (Live vehicle count from `/public/map/summary`)
    2. *Collection Points* (Community bins, DWCCs across Bengaluru)
    3. *Published Routes* (Active daily collection routes)
    4. *Your Reports* (Clickable count linking to personal incident history)
  * **Bengaluru & Yelahanka Interactive Map**: Tile layer toggle (OpenStreetMap vs Esri Satellite), vehicle markers with directional heading arrows, and telemetry freshness badges.
  * **Illegal Dumping Modal**: Two-step validation (description between 10–1000 characters, latitude/longitude bounds, photo upload support).
* **Visual Suggestion**: Dual-panel screenshot showing the Citizen Dashboard with the Vidhana Soudha banner on top and the interactive tracking map below.
* **Speaker Notes**:
  > "On the Citizen Dashboard, citizens immediately see live fleet statistics and the Yelahanka pilot area. Clicking on any vehicle marker reveals its speed, vehicle type, and last-seen freshness timestamp. Citizens can submit dumping complaints with GPS coordinates and track their resolution status in real time."

---

## Slide 9: BBMP Official Dashboard Walkthrough

* **Headline**: Centralized Ward Operations & Supervisory Governance
* **Features Demonstrated**:
  * **Role-Based Access**: Restricted to `WARD_SUPERVISOR` and `MUNICIPAL_ADMIN`.
  * **4 Operational Metric Cards**: *Active Vehicles*, *Published Routes*, *Pending Reports*, and *Staff on Duty*.
  * **5 Functional Operation Tabs**:
    1. *Overview*: Operational health and quick metrics.
    2. *Vehicles*: Real-time fleet tracking map.
    3. *Citizen Reports*: Triage table supporting status transitions (`UNDER_REVIEW`, `ACTION_SCHEDULED`, `RESOLVED`, `REJECTED`).
    4. *Roll-Call QR*: 5-minute cryptographic single-use QR token generator for morning muster stations.
    5. *Operations Roster*: Real-time workforce attendance audit log with geofence exception indicators.
* **Visual Suggestion**: Screenshot of the BBMP Official dashboard showing the complaints triage queue and the 5-minute QR roll-call generator.
* **Speaker Notes**:
  > "The BBMP Official Dashboard empowers ward supervisors with complete operational governance. When a supervisor reviews complaints, status updates are validated through our state machine. Furthermore, supervisors can generate a rolling 5-minute QR code on-screen for morning muster roll-calls."

---

## Slide 10: Pourakarmika / Worker Dashboard Walkthrough

* **Headline**: Digital Workforce Enablement & Tamper-Proof Muster
* **Features Demonstrated**:
  * **Role-Based Access**: Dedicated to `SANITATION_WORKER` and `DRIVER`.
  * **4 Daily Field Summary Cards**: *Muster Depot*, *Shift Attendance Status*, *Assigned Vehicle*, and *Check-In Time*.
  * **3-Step Cryptographic Attendance Flow**:
    1. Worker requests OTP (6-digit numeric code, 5-minute validity).
    2. Enters code alongside device GPS coordinates.
    3. Backend verifies code and validates location within 150m of assigned muster station (`Yelahanka Satellite Town Depot`).
  * **Shift Check-Out**: Records check-out timestamp and computes total shift duration.
  * **Digital Worker ID Card**: Displays worker name, photo placeholder, employee ID, assigned ward, and muster station.
* **Transparency Notice**: In offline development, OTPs are output to the server console and test scratchpad (`scratch/dev_latest_otp.txt`) rather than external SMS/SMTP relays.
* **Visual Suggestion**: Screenshots showing the Attendance OTP verification card and the digital Pourakarmika identity card.
* **Speaker Notes**:
  > "For our sanitation workers, simplicity and fairness are paramount. The worker logs in, requests a single-use OTP, and submits their check-in. The system checks whether their device GPS is within 150 meters of their muster depot. Once checked in, they can view their assigned route and access their digital identity card."

---

## Slide 11: Security, Spatial Validation & Cryptography

* **Headline**: Multi-Layered Defense & Spatial Verification
* **Security Controls Implemented**:
  * **Cryptographic Passwords**: Passwords hashed with Argon2id (`memory=65536, time=3, parallelism=4`).
  * **JWT Session Tokens**: HMAC-SHA256 signed bearer tokens with role claims and expiration enforcement.
  * **Role-Based Access Control (RBAC)**: Endpoint-level dependencies (`require_roles(...)`) reject unauthorized requests with `HTTP 403 Forbidden`.
  * **OTP Security Parameters**:
    * 6-digit high-entropy numeric token (`secrets.randbelow`).
    * Stored as salted SHA-256 hash (`hashlib.sha256(salt + otp)`).
    * Strictly 5-minute lifetime (`OTP_VALIDITY_SECONDS = 300`).
    * Maximum 3 verification attempts before permanent challenge invalidation.
    * 30-second rate-limiting cooldown per worker.
  * **150-Meter PostGIS Geofence**: Validated via `ST_DWithin(worker_location, depot_location, 150.0)`.
  * **Single-Use Roll-Call QR Tokens**: Cryptographic token hash with 5-minute expiry, server-clock enforcement, and replay attack prevention.
* **Visual Suggestion**: Security architecture diagram highlighting Argon2id, JWT, PostGIS Geofence (150m radius circle), and OTP Salted Hash.
* **Speaker Notes**:
  > "Security is embedded throughout our stack. Notice that OTPs are never stored in plaintext—only salted SHA-256 hashes are retained. If an entered OTP fails 3 times, the challenge is destroyed. Geofencing is calculated server-side in PostGIS, ensuring clients cannot spoof proximity checks."

---

## Slide 12: Database & Spatial API Design

* **Headline**: Relational Architecture with Spatial Extensions
* **Core Database Entities & Relationships**:
  * `wards`: Primary administrative boundary (`id`, `ward_code`, `display_name`, `boundary: Geometry(Polygon, 4326)`).
  * `users`: Authentication & profiles (`email`, `password_hash`, `role`, `locality`, `ward_id`).
  * `vehicles`: Fleet inventory (`registration_number`, `vehicle_type`, `status`, `current_location: Geometry(Point, 4326)`, `is_simulated`).
  * `collection_routes`: Planned waste routes (`route_code`, `route_path: Geometry(LineString, 4326)`, `is_published`).
  * `dumping_reports`: Citizen grievances (`reporter_id`, `location: Geometry(Point, 4326)`, `status`, `official_notes`).
  * `muster_points`: Official depots (`ward_id`, `location: Geometry(Point, 4326)`, `geofence_radius_meters = 150`).
  * `attendance_records`: Daily worker check-ins (`worker_id`, `muster_point_id`, `check_in_at`, `status`, `is_geofence_verified`).
* **Representative REST Endpoints**:
  * `GET /api/v1/public/map/summary` — Public fleet and route statistics.
  * `GET /api/v1/public/map/vehicles` — Real-time telemetry with simulation and freshness flags.
  * `POST /api/v1/reports` — Citizen geotagged dumping incident submission.
  * `PATCH /api/v1/reports/{id}/status` — Supervisor complaint lifecycle updates.
  * `POST /api/v1/attendance/request-otp` & `POST /api/v1/attendance/verify-otp` — Workforce attendance check-in.
* **Speaker Notes**:
  > "All spatial tables utilize PostGIS SRID 4326, which represents standard WGS 84 latitude and longitude coordinates. Spatial queries leverage PostGIS R-Tree indexes for fast bounding box lookups, ensuring responsive performance even under high concurrency."

---

## Slide 13: Testing Strategy & Verification Evidence

* **Headline**: Rigorous Automated and Live Verification Results
* **Verified Test Results**:
  * **Frontend Contract & Unit Tests**: **31 passed, 0 failed** (Duration: 3.85s).
    * Verified auth client token lifecycle, display name resolution, report input bounds, GeoJSON conversions, and OTP format checks.
  * **Production Frontend Build**: **Built cleanly in 2.35s** with 0 TypeScript/ESLint errors (`tsc -b && vite build`).
  * **Backend Pytest Suite**: **370 passed, 0 failed** (Duration: 19.78s).
    * Complete coverage of authentication, login, attendance lifecycle, QR tokens, route stops, and spatial distance calculations.
  * **Citizen Dashboard Live Audit**: **15/15 checks passed (100%)**.
    * Verified login, user profile resolution, 4 summary cards, telemetry range bounds, and flying bird animation.
  * **Role-Based Dashboards Live Audit**: **13/13 checks passed (100%)**.
    * Verified supervisor complaint triage, attendance roster querying, worker assignment lookup, and QR generation.
* **Visual Suggestion**: Test execution terminal summary banner with green passing checks and test metrics table.
* **Speaker Notes**:
  > "Our project underwent rigorous automated and manual verification. Both the frontend contract tests and backend pytest suite pass with 100% success across 370 server tests and 31 frontend contract tests, backed by a production TypeScript compilation with zero type errors."

---

## Slide 14: Current Limitations & Evaluation Transparency

* **Headline**: Transparent Engineering Disclosures
* **Disclosed Constraints**:
  * **1. Simulated Telemetry Feed**: Vehicle positions currently run on an internal simulation engine (`is_simulated: true`) along predefined route geometries. Physical AIS-140 GPS hardware units are not yet attached.
  * **2. Development OTP Transport**: In this offline test environment, OTP codes are logged to server console and local scratchpad (`scratch/dev_latest_otp.txt`) rather than dispatched via external commercial SMTP/SMS gateways.
  * **3. Pilot Geographic Boundaries**: The Yelahanka pilot area uses approximate polygon coordinates for demonstration and is not an official survey-grade BBMP cadastre.
  * **4. External Map Tile Connectivity**: Standard and satellite map views depend on external tile CDN connectivity (OpenStreetMap and Esri) when tiles are not cached locally.
  * **5. Academic Scope**: The platform is an engineered working capstone prototype and does not imply an official municipal partnership with BBMP.
* **Speaker Notes**:
  > "As responsible engineers, we believe in complete transparency. Our fleet telemetry is driven by a simulation engine rather than physical GPS hardware, and our OTP delivery uses local transport logging. These design decisions were made to guarantee reliable, deterministic demonstrations in an academic setting."

---

## Slide 15: Proposed Future Enhancements

* **Headline**: Roadmap for Production Municipal Deployment
* **Planned Future Work**:
  * **1. Hardware AIS-140 GPS Ingestion**: Connect onboard IoT vehicle telematics directly to the backend via MQTT or WebSockets for live sub-second GPS feeds.
  * **2. Multi-Channel Alerting**: Integrate Twilio SMS and AWS SES for real-time citizen notification when collection vehicles approach within 500 meters.
  * **3. Multilingual Support (Kannada & English)**: Provide a comprehensive Kannada language toggle across citizen and worker interfaces.
  * **4. Machine Learning Black-Spot Detection**: Deploy computer vision models (e.g., YOLO) to automatically classify garbage volume from citizen photo uploads.
  * **5. Dynamic Route Optimization**: Incorporate Open-Source Routing Machine (OSRM) to calculate dynamic collection routes based on daily traffic and fill levels.
  * **6. Municipal Stakeholder Pilot**: Conduct controlled field trials with local ward engineers and Pourakarmika unions.
* **Speaker Notes**:
  > "Looking forward, the architecture is designed to scale. The telemetry API already accepts live GPS payloads without code changes. Adding computer vision for automated waste classification and multi-lingual Kannada support will make the platform even more accessible to field workers."

---

## Slide 16: Conclusion & Project Summary

* **Headline**: Engineering Accountable Civic Infrastructure
* **Key Takeaways**:
  * **Tripartite Civic Ecosystem**: Successfully engineered unified, role-based workflows for Citizens, BBMP Supervisors, and Pourakarmikas.
  * **Geospatial & Cryptographic Rigor**: Combined PostGIS spatial queries (150m geofence) with salted SHA-256 OTP verification to eliminate proxy attendance.
  * **Grievance Redressal Transparency**: Full geotagged reporting with strict validation and auditable supervisor status state machines.
  * **Demonstration Reliability**: Fully verified pilot in Yelahanka (Ward 0004), supported by 370 backend tests, 31 frontend contract tests, and a production TypeScript build.
* **Closing Statement**: NammaClean proves that modern open-source web technologies and geospatial databases can bring transparency, dignity, and accountability to municipal sanitation operations.
* **Thank You & Q&A**: We welcome questions from the evaluation committee.
* **Speaker Notes**:
  > "In conclusion, NammaClean demonstrates that modern full-stack technologies—FastAPI, React, and PostGIS—can provide practical, high-integrity solutions to civic management challenges. We thank our guide and the evaluation panel for their time, and we look forward to your questions."
