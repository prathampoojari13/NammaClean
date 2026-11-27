import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uuid
import sqlalchemy as sa
from app.core.config import settings
from app.core.security import hash_password

def setup():
    engine = sa.create_engine(settings.sync_database_url)
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE users SET full_name = 'Pratham' WHERE email = 'pk@gmail.com'"))
        r = conn.execute(sa.text("SELECT id FROM users WHERE email = 'rahul@nammaclean.local'")).first()
        if not r:
            conn.execute(sa.text("""
                INSERT INTO users (id, email, password_hash, role, status, full_name, created_at, updated_at)
                VALUES (:id, 'rahul@nammaclean.local', :pwd, 'CITIZEN', 'ACTIVE', 'Rahul', NOW(), NOW())
            """), {'id': uuid.uuid4(), 'pwd': hash_password('CitizenRahul@2026!')})
            print('Created Rahul test user!')
        else:
            conn.execute(sa.text("UPDATE users SET full_name = 'Rahul' WHERE email = 'rahul@nammaclean.local'"))
            print('Updated Rahul test user!')

        # Seed/Update Admin
        r_admin = conn.execute(sa.text("SELECT id FROM users WHERE email = 'admin.central@nammaclean.local'")).first()
        if not r_admin:
            conn.execute(sa.text("""
                INSERT INTO users (id, email, password_hash, role, status, full_name, official_id, phone_number, created_at, updated_at)
                VALUES (:id, 'admin.central@nammaclean.local', :pwd, 'MUNICIPAL_ADMIN', 'ACTIVE', 'BBMP Central Administrator', 'BBMP-ADM-001', '+919876543200', NOW(), NOW())
            """), {'id': uuid.uuid4(), 'pwd': hash_password('AdminCentral@2026!')})
            print('Created admin.central test user!')
        else:
            conn.execute(sa.text("""
                UPDATE users SET official_id = 'BBMP-ADM-001', phone_number = '+919876543200' WHERE email = 'admin.central@nammaclean.local'
            """))

        # Assign Official IDs to operational users
        conn.execute(sa.text("UPDATE users SET official_id = 'BBMP-WRK-004', phone_number = '+919876543210', full_name = 'Manjunatha Swamy' WHERE email = 'worker.yelahanka@nammaclean.local'"))
        conn.execute(sa.text("UPDATE users SET official_id = 'BBMP-SUP-004', phone_number = '+919876543211', full_name = 'Ramesh Kumar (Ward Supervisor)' WHERE email = 'supervisor.yelahanka@nammaclean.local'"))
        conn.execute(sa.text("UPDATE users SET official_id = 'BBMP-DRV-004', phone_number = '+919876543212', full_name = 'Suresh Pilot Driver' WHERE email = 'pilot.driver.yelahanka@nammaclean.local'"))
        conn.execute(sa.text("UPDATE users SET official_id = 'BBMP-DRV-001', phone_number = '+919876543213' WHERE email = 'pratham@gmail.com'"))

        print("Verification:")
        for row in conn.execute(sa.text("SELECT email, full_name, role, official_id, phone_number FROM users WHERE email IN ('admin.central@nammaclean.local', 'supervisor.yelahanka@nammaclean.local', 'worker.yelahanka@nammaclean.local', 'pilot.driver.yelahanka@nammaclean.local', 'pratham@gmail.com', 'rahul@nammaclean.local')")).mappings().all():
            print(dict(row))

if __name__ == "__main__":
    setup()
