import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.core.security import hash_password
import sqlalchemy as sa
from app.core.config import settings

def ensure_passwords():
    engine = sa.create_engine(settings.sync_database_url)
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE users SET password_hash = :pwd, full_name = 'Pratham' WHERE email = 'pk@gmail.com'"), {'pwd': hash_password('CitizenPratham@2026!')})
        conn.execute(sa.text("UPDATE users SET password_hash = :pwd, full_name = 'Rahul' WHERE email = 'rahul@nammaclean.local'"), {'pwd': hash_password('CitizenRahul@2026!')})
        conn.execute(sa.text("UPDATE users SET password_hash = :pwd, full_name = NULL WHERE email = 'test_citizen@nammaclean.local'"), {'pwd': hash_password('TestCitizen@2026!')})

def run_tests():
    ensure_passwords()
    base = 'http://127.0.0.1:8000/api/v1'
    with httpx.Client(base_url=base) as client:
        # 1. Test Pratham
        r1 = client.post('/auth/login', json={'email': 'pk@gmail.com', 'password': 'CitizenPratham@2026!'})
        assert r1.status_code == 200, f'Pratham login failed: {r1.text}'
        token1 = r1.json()['access_token']
        me1 = client.get('/users/me', headers={'Authorization': f'Bearer {token1}'}).json()
        print('1. Pratham /users/me response:')
        print(f"   email: {me1.get('email')}, full_name: {me1.get('full_name')}")
        assert me1.get('full_name') == 'Pratham'

        # 2. Test Rahul
        r2 = client.post('/auth/login', json={'email': 'rahul@nammaclean.local', 'password': 'CitizenRahul@2026!'})
        assert r2.status_code == 200, f'Rahul login failed: {r2.text}'
        token2 = r2.json()['access_token']
        me2 = client.get('/users/me', headers={'Authorization': f'Bearer {token2}'}).json()
        print('2. Rahul /users/me response:')
        print(f"   email: {me2.get('email')}, full_name: {me2.get('full_name')}")
        assert me2.get('full_name') == 'Rahul'

        # 3. Test Missing Profile Name
        r3 = client.post('/auth/login', json={'email': 'test_citizen@nammaclean.local', 'password': 'TestCitizen@2026!'})
        assert r3.status_code == 200, f'Test citizen login failed: {r3.text}'
        token3 = r3.json()['access_token']
        me3 = client.get('/users/me', headers={'Authorization': f'Bearer {token3}'}).json()
        print('3. Missing Name /users/me response:')
        print(f"   email: {me3.get('email')}, full_name: {me3.get('full_name')}")
        assert me3.get('full_name') is None

    print('\nAll 3 user profile authentication flows verified successfully!')

if __name__ == '__main__':
    run_tests()
