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

        print("Verification:")
        for row in conn.execute(sa.text("SELECT email, full_name, role FROM users WHERE email IN ('pk@gmail.com', 'rahul@nammaclean.local', 'test_citizen@nammaclean.local')")).mappings().all():
            print(dict(row))

if __name__ == "__main__":
    setup()
