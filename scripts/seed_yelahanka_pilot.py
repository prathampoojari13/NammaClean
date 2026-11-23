"""
Idempotent Seeder for NammaClean Yelahanka Operational Pilot.
Creates authentic Yelahanka Satellite Town ward (BBMP-W004) with boundary geometry,
muster depot, pilot sanitation worker, pilot supervisor, and clearly labeled simulated vehicle & route.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from sqlalchemy import select, text
from geoalchemy2.elements import WKTElement

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.enums import UserRole, UserStatus, VehicleType, VehicleStatus, CollectionPointType
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint
from app.models.vehicle import Vehicle
from app.models.route import CollectionRoute
from app.models.collection_point import CollectionPoint
from app.models.user import User

YELAHANKA_WARD_ID = uuid.UUID("44444444-4444-4444-4444-444444440004")
MUSTER_POINT_ID = uuid.UUID("44444444-4444-4444-4444-444444440001")
PILOT_VEHICLE_ID = uuid.UUID("44444444-4444-4444-4444-444444440010")
PILOT_ROUTE_ID = uuid.UUID("44444444-4444-4444-4444-444444440020")

async def seed_pilot():
    async with AsyncSessionLocal() as session:
        print("[Pilot Seeder] Checking Yelahanka Pilot Ward...")
        
        # 1. Ward: BBMP-W004 Yelahanka Satellite Town
        stmt = select(Ward).where(Ward.ward_code == "BBMP-W004")
        res = await session.execute(stmt)
        ward = res.scalars().first()

        boundary_wkt = (
            "MULTIPOLYGON(((77.5580 13.0850, 77.6150 13.0850, 77.6150 13.1420, "
            "77.5580 13.1420, 77.5580 13.0850)))"
        )
        
        if not ward:
            ward = Ward(
                id=YELAHANKA_WARD_ID,
                ward_code="BBMP-W004",
                display_name="Ward 4 - Yelahanka Satellite Town & Avalahalli Corridor",
                boundary=WKTElement(boundary_wkt, srid=4326),
            )
            session.add(ward)
            await session.flush()
            print(f"  -> Created Ward: {ward.display_name} ({ward.id})")
        else:
            ward.display_name = "Ward 4 - Yelahanka Satellite Town & Avalahalli Corridor"
            ward.boundary = WKTElement(boundary_wkt, srid=4326)
            await session.flush()
            print(f"  -> Ward updated with BMSIT&M / Avalahalli corridor boundary: {ward.display_name} ({ward.id})")

        # 2. Muster Points: Yelahanka Satellite Town Depot & BMSIT&M Avalahalli Depot
        stmt_mp = select(MusterPoint).where(MusterPoint.name == "Yelahanka Satellite Town Muster Depot")
        res_mp = await session.execute(stmt_mp)
        mp = res_mp.scalars().first()

        if not mp:
            mp = MusterPoint(
                id=MUSTER_POINT_ID,
                ward_id=ward.id,
                name="Yelahanka Satellite Town Muster Depot",
                location=WKTElement("POINT(77.5895 13.0985)", srid=4326),
                geofence_radius_meters=150,
                is_active=True,
            )
            session.add(mp)
            await session.flush()
            print(f"  -> Created Muster Point: {mp.name} (150m geofence)")
        else:
            print(f"  -> Muster Point already exists: {mp.name}")

        # 2b. BMSIT&M Avalahalli Muster Depot
        bmsit_mp_id = uuid.UUID("44444444-4444-4444-4444-444444440002")
        stmt_bmp = select(MusterPoint).where(MusterPoint.name == "BMSIT&M - Avalahalli Muster Depot")
        res_bmp = await session.execute(stmt_bmp)
        bmp = res_bmp.scalars().first()

        if not bmp:
            bmp = MusterPoint(
                id=bmsit_mp_id,
                ward_id=ward.id,
                name="BMSIT&M - Avalahalli Muster Depot",
                location=WKTElement("POINT(77.5685 13.1331)", srid=4326),
                geofence_radius_meters=150,
                is_active=True,
            )
            session.add(bmp)
            await session.flush()
            print(f"  -> Created Muster Point: {bmp.name} (150m geofence at BMSIT&M)")
        else:
            print(f"  -> Muster Point already exists: {bmp.name}")

        # 3. Pilot Accounts
        # 3a. Pilot Sanitation Worker
        stmt_w = select(User).where(User.email == "worker.yelahanka@nammaclean.local")
        res_w = await session.execute(stmt_w)
        worker = res_w.scalars().first()

        if not worker:
            worker = User(
                email="worker.yelahanka@nammaclean.local",
                password_hash=hash_password("PilotWorker@2026!"),
                role=UserRole.SANITATION_WORKER.value,
                status=UserStatus.ACTIVE.value,
                ward_id=ward.id,
                locality="Yelahanka Satellite Town",
                address="Sector 4, Yelahanka New Town, Bengaluru",
            )
            session.add(worker)
            await session.flush()
            print(f"  -> Created Worker: {worker.email}")
        else:
            worker.ward_id = ward.id
            await session.flush()
            print(f"  -> Worker already exists: {worker.email}")

        # Ensure Worker Ward Assignment
        stmt_uwa = select(UserWardAssignment).where(
            UserWardAssignment.user_id == worker.id,
            UserWardAssignment.ward_id == ward.id,
            UserWardAssignment.revoked_at.is_(None),
        )
        res_uwa = await session.execute(stmt_uwa)
        if not res_uwa.scalars().first():
            assign = UserWardAssignment(user_id=worker.id, ward_id=ward.id)
            session.add(assign)
            await session.flush()
            print("  -> Worker assigned to Yelahanka Ward in user_ward_assignments")

        # 3b. Pilot Ward Supervisor
        stmt_s = select(User).where(User.email == "supervisor.yelahanka@nammaclean.local")
        res_s = await session.execute(stmt_s)
        supervisor = res_s.scalars().first()

        if not supervisor:
            supervisor = User(
                email="supervisor.yelahanka@nammaclean.local",
                password_hash=hash_password("PilotSupervisor@2026!"),
                role=UserRole.WARD_SUPERVISOR.value,
                status=UserStatus.ACTIVE.value,
                ward_id=ward.id,
                locality="Yelahanka Satellite Town",
                address="BBMP Sub-Division Office, Yelahanka New Town, Bengaluru",
            )
            session.add(supervisor)
            await session.flush()
            print(f"  -> Created Supervisor: {supervisor.email}")
        else:
            supervisor.ward_id = ward.id
            await session.flush()
            print(f"  -> Supervisor already exists: {supervisor.email}")

        # Ensure Supervisor Ward Assignment
        stmt_suwa = select(UserWardAssignment).where(
            UserWardAssignment.user_id == supervisor.id,
            UserWardAssignment.ward_id == ward.id,
            UserWardAssignment.revoked_at.is_(None),
        )
        res_suwa = await session.execute(stmt_suwa)
        if not res_suwa.scalars().first():
            assign = UserWardAssignment(user_id=supervisor.id, ward_id=ward.id)
            session.add(assign)
            await session.flush()
            print("  -> Supervisor assigned to Yelahanka Ward in user_ward_assignments")

        # 4. Pilot Demo Vehicle in Yelahanka – Avalahalli (BMSIT&M) Corridor
        stmt_v = select(Vehicle).where(Vehicle.registration_number == "KA-50-P-0401")
        res_v = await session.execute(stmt_v)
        veh = res_v.scalars().first()

        now = datetime.now(timezone.utc)
        if not veh:
            veh = Vehicle(
                id=PILOT_VEHICLE_ID,
                registration_number="KA-50-P-0401",
                vehicle_type=VehicleType.COMPACTOR_TRUCK.value,
                status=VehicleStatus.ON_DUTY.value,
                assigned_ward_id=ward.id,
                current_location=WKTElement("POINT(77.5690 13.1320)", srid=4326),
                last_seen_at=now,
                is_simulated=True,
                is_published=True,
            )
            session.add(veh)
            await session.flush()
            print(f"  -> Created Pilot Vehicle: {veh.registration_number} (Simulated Demo, Published)")
        else:
            veh.assigned_ward_id = ward.id
            veh.current_location = WKTElement("POINT(77.5690 13.1320)", srid=4326)
            veh.last_seen_at = now
            veh.is_published = True
            veh.is_simulated = True
            await session.flush()
            print(f"  -> Refreshed Pilot Vehicle: {veh.registration_number} at BMSIT&M corridor")

        # 5. Pilot Demo Route in Yelahanka – BMSIT&M Corridor
        stmt_rt = select(CollectionRoute).where(CollectionRoute.route_code == "YEL-F-04")
        res_rt = await session.execute(stmt_rt)
        route = res_rt.scalars().first()

        route_wkt = (
            "LINESTRING(77.5895 13.0985, 77.5830 13.1080, 77.5750 13.1190, "
            "77.5700 13.1270, 77.5685 13.1331)"
        )

        if not route:
            route = CollectionRoute(
                id=PILOT_ROUTE_ID,
                ward_id=ward.id,
                name="Yelahanka – BMSIT&M Avalahalli Corridor Route",
                route_code="YEL-F-04",
                route_path=WKTElement(route_wkt, srid=4326),
                is_active=True,
                is_published=True,
                is_simulated=True,
            )
            session.add(route)
            await session.flush()
            print(f"  -> Created Pilot Route: {route.name} ({route.route_code})")
        else:
            route.name = "Yelahanka – BMSIT&M Avalahalli Corridor Route"
            route.route_path = WKTElement(route_wkt, srid=4326)
            route.is_active = True
            route.is_published = True
            await session.flush()
            print(f"  -> Route updated for BMSIT&M corridor: {route.name}")

        await session.commit()
        print("\n[Pilot Seeder] Yelahanka Operational Pilot data seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed_pilot())
