"""
Unit tests for Muster Point Management APIs:
- POST   /api/v1/wards/{ward_id}/muster-points
- GET    /api/v1/wards/{ward_id}/muster-points
- GET    /api/v1/muster-points/{muster_point_id}
- PATCH  /api/v1/muster-points/{muster_point_id}
- DELETE /api/v1/muster-points/{muster_point_id}

Database-independent tests verifying:
1. Authorized creation and listing by MUNICIPAL_ADMIN and assigned WARD_SUPERVISOR.
2. Coordinate validation (lat [-90, 90], lon [-180, 180]).
3. Geofence radius validation (positive, max sensible 2000m).
4. Blank name validation.
5. Missing ward (404) and missing muster point (404).
6. Unauthorized roles (CITIZEN, SANITATION_WORKER) rejected with HTTP 403.
7. Unauthenticated callers rejected with HTTP 401.
8. Ward supervisor cross-ward access rejection (HTTP 403).
9. Partial updates to name, coordinates, geofence radius, and active status.
10. Prohibiting client mutation of ID or Ward ID (HTTP 422).
11. Soft deactivation preserving the record and attendance references.
12. `active_only` query filtering.
13. Correct coordinate conversion (PostGIS POINT -> numeric lat and lon).
"""

import uuid
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from geoalchemy2.elements import WKTElement

from app.main import app
from app.core.database import get_db
from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.models.enums import UserRole, UserStatus
from app.models.user import User
from app.models.ward import Ward, UserWardAssignment
from app.models.attendance import MusterPoint


class TestMusterPointsAPI(unittest.IsolatedAsyncioTestCase):
    """Database-independent unit tests for MusterPoint endpoints."""

    def setUp(self):
        self.ward_id = uuid.uuid4()
        self.other_ward_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()
        self.supervisor_id = uuid.uuid4()
        self.citizen_id = uuid.uuid4()

        now = datetime.now(timezone.utc)

        # Users
        self.admin_user = User(
            id=self.admin_id,
            email="admin@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.MUNICIPAL_ADMIN.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        self.supervisor_user = User(
            id=self.supervisor_id,
            email="supervisor@bbmp.gov.in",
            password_hash="mock_hash",
            role=UserRole.WARD_SUPERVISOR.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        self.citizen_user = User(
            id=self.citizen_id,
            email="citizen@example.com",
            password_hash="mock_hash",
            role=UserRole.CITIZEN.value,
            status=UserStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
        )

        # Wards
        self.ward = Ward(
            id=self.ward_id,
            ward_code="WARD-150",
            display_name="Bellandur",
            boundary=None,
        )

        # Sample Muster Point
        self.mp_id = uuid.uuid4()
        self.sample_point = MusterPoint(
            id=self.mp_id,
            ward_id=self.ward_id,
            name="Bellandur Gate Roll Call",
            location=WKTElement("POINT(77.6740 12.9260)", srid=4326),
            geofence_radius_meters=150,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        # Inactive sample point
        self.inactive_mp_id = uuid.uuid4()
        self.inactive_point = MusterPoint(
            id=self.inactive_mp_id,
            ward_id=self.ward_id,
            name="Decommissioned Station",
            location=WKTElement("POINT(77.6800 12.9300)", srid=4326),
            geofence_radius_meters=100,
            is_active=False,
            created_at=now,
            updated_at=now,
        )

        # Mock DB session
        self.mock_session = AsyncMock()
        self.mock_session.commit = AsyncMock()
        self.mock_session.rollback = AsyncMock()
        self.mock_session.refresh = AsyncMock()
        self.mock_session.add = MagicMock()
        self.mock_session.delete = MagicMock()

        # Tokens
        self.admin_token = create_access_token(
            subject=str(self.admin_id),
            extra_claims={"role": UserRole.MUNICIPAL_ADMIN.value},
        )
        self.supervisor_token = create_access_token(
            subject=str(self.supervisor_id),
            extra_claims={"role": UserRole.WARD_SUPERVISOR.value},
        )
        self.citizen_token = create_access_token(
            subject=str(self.citizen_id),
            extra_claims={"role": UserRole.CITIZEN.value},
        )

        # Dependency Overrides
        self.current_mock_user = self.admin_user

        async def _override_get_current_user():
            return self.current_mock_user

        async def _override_get_db():
            yield self.mock_session

        app.dependency_overrides[get_current_user] = _override_get_current_user
        app.dependency_overrides[get_db] = _override_get_db

    def tearDown(self):
        app.dependency_overrides.clear()

    # --- 1. Creation Tests ---

    async def test_create_muster_point_authorized_admin(self):
        """MUNICIPAL_ADMIN can create a muster point with valid coordinates."""
        self.current_mock_user = self.admin_user

        # Mock ward lookup: Ward exists
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = self.ward
        self.mock_session.execute.return_value = mock_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={
                    "name": "Bellandur Gate Roll Call",
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                    "geofence_radius_meters": 150,
                },
            )

        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["name"], "Bellandur Gate Roll Call")
        self.assertEqual(data["ward_id"], str(self.ward_id))
        self.assertAlmostEqual(data["latitude"], 12.9260, places=4)
        self.assertAlmostEqual(data["longitude"], 77.6740, places=4)
        self.assertEqual(data["geofence_radius_meters"], 150)
        self.assertTrue(data["is_active"])
        self.assertIn("id", data)
        self.assertIn("created_at", data)
        self.mock_session.commit.assert_awaited_once()

    async def test_create_muster_point_authorized_supervisor(self):
        """WARD_SUPERVISOR can create a muster point in their assigned ward."""
        self.current_mock_user = self.supervisor_user

        # Mock ward lookup, then assignment lookup for verify_ward_access
        ward_result = MagicMock()
        ward_result.scalars().first.return_value = self.ward

        assignment = UserWardAssignment(
            id=uuid.uuid4(),
            user_id=self.supervisor_id,
            ward_id=self.ward_id,
            revoked_at=None,
        )
        assignment_result = MagicMock()
        assignment_result.scalars().first.return_value = assignment

        self.mock_session.execute.side_effect = [ward_result, assignment_result]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.supervisor_token}"},
                json={
                    "name": "Kaikondrahalli Muster Point",
                    "latitude": 12.9150,
                    "longitude": 77.6720,
                    "geofence_radius_meters": 120,
                },
            )

        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["name"], "Kaikondrahalli Muster Point")
        self.assertAlmostEqual(data["latitude"], 12.9150, places=4)
        self.assertAlmostEqual(data["longitude"], 77.6720, places=4)

    async def test_create_muster_point_supervisor_cross_ward_denial(self):
        """WARD_SUPERVISOR is denied (403) when attempting access to an unassigned ward."""
        self.current_mock_user = self.supervisor_user

        # Ward exists, but supervisor has no assignment for that ward
        ward_result = MagicMock()
        ward_result.scalars().first.return_value = self.ward

        no_assignment_result = MagicMock()
        no_assignment_result.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [ward_result, no_assignment_result]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.supervisor_token}"},
                json={
                    "name": "Cross Ward Point",
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 403)
        self.assertIn("not actively assigned to this ward", res.json()["detail"])

    async def test_create_muster_point_unauthorized_role(self):
        """Unauthorized roles like CITIZEN are rejected with HTTP 403."""
        self.current_mock_user = self.citizen_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.citizen_token}"},
                json={
                    "name": "Citizen Point",
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 403)
        self.assertIn("Insufficient permissions", res.json()["detail"])

    async def test_create_muster_point_unauthenticated(self):
        """Unauthenticated requests are rejected with HTTP 401."""
        app.dependency_overrides.pop(get_current_user, None)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                json={
                    "name": "Unauth Point",
                    "latitude": 12.9260,
                    "longitude": 77.6740,
                },
            )

        self.assertEqual(res.status_code, 401)
        self.assertIn("WWW-Authenticate", res.headers)

    async def test_create_muster_point_invalid_coordinates(self):
        """Latitude outside [-90, 90] and longitude outside [-180, 180] trigger HTTP 422."""
        self.current_mock_user = self.admin_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Lat > 90
            res1 = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "Test", "latitude": 91.0, "longitude": 77.0},
            )
            self.assertEqual(res1.status_code, 422)

            # Lat < -90
            res2 = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "Test", "latitude": -95.0, "longitude": 77.0},
            )
            self.assertEqual(res2.status_code, 422)

            # Lon > 180
            res3 = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "Test", "latitude": 12.0, "longitude": 181.0},
            )
            self.assertEqual(res3.status_code, 422)

            # Lon < -180
            res4 = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "Test", "latitude": 12.0, "longitude": -185.0},
            )
            self.assertEqual(res4.status_code, 422)

    async def test_create_muster_point_invalid_geofence_radius(self):
        """Radius <= 0 or exceeding max configured limit triggers HTTP 422."""
        self.current_mock_user = self.admin_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Radius 0
            res1 = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "Test", "latitude": 12.0, "longitude": 77.0, "geofence_radius_meters": 0},
            )
            self.assertEqual(res1.status_code, 422)

            # Radius > 2000
            res2 = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "Test", "latitude": 12.0, "longitude": 77.0, "geofence_radius_meters": 2500},
            )
            self.assertEqual(res2.status_code, 422)

    async def test_create_muster_point_blank_name(self):
        """Blank or whitespace-only name triggers HTTP 422."""
        self.current_mock_user = self.admin_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "   ", "latitude": 12.0, "longitude": 77.0},
            )
        self.assertEqual(res.status_code, 422)

    async def test_create_muster_point_missing_ward(self):
        """Attempting to create a muster point for a non-existent ward returns HTTP 404."""
        self.current_mock_user = self.admin_user

        mock_result = MagicMock()
        mock_result.scalars().first.return_value = None
        self.mock_session.execute.return_value = mock_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/wards/{uuid.uuid4()}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"name": "Valid Point", "latitude": 12.0, "longitude": 77.0},
            )

        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"])

    # --- 2. Listing Tests ---

    async def test_list_muster_points_active_only_by_default(self):
        """GET /wards/{ward_id}/muster-points filters active points by default."""
        self.current_mock_user = self.admin_user

        # Ward lookup
        ward_result = MagicMock()
        ward_result.scalars().first.return_value = self.ward

        # Muster point list query result (only active point)
        mp_result = MagicMock()
        mp_result.scalars().all.return_value = [self.sample_point]

        self.mock_session.execute.side_effect = [ward_result, mp_result]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/wards/{self.ward_id}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], str(self.mp_id))
        self.assertTrue(data[0]["is_active"])
        self.assertAlmostEqual(data[0]["latitude"], 12.9260, places=4)
        self.assertAlmostEqual(data[0]["longitude"], 77.6740, places=4)

    async def test_list_muster_points_including_inactive(self):
        """GET /wards/{ward_id}/muster-points?active_only=false returns inactive points too."""
        self.current_mock_user = self.admin_user

        ward_result = MagicMock()
        ward_result.scalars().first.return_value = self.ward

        mp_result = MagicMock()
        mp_result.scalars().all.return_value = [self.sample_point, self.inactive_point]

        self.mock_session.execute.side_effect = [ward_result, mp_result]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/wards/{self.ward_id}/muster-points?active_only=false",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 2)
        active_statuses = [item["is_active"] for item in data]
        self.assertIn(True, active_statuses)
        self.assertIn(False, active_statuses)

    async def test_list_muster_points_missing_ward(self):
        """Listing points for non-existent ward returns HTTP 404."""
        self.current_mock_user = self.admin_user

        ward_result = MagicMock()
        ward_result.scalars().first.return_value = None
        self.mock_session.execute.return_value = ward_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/wards/{uuid.uuid4()}/muster-points",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )

        self.assertEqual(res.status_code, 404)

    # --- 3. Get Single Muster Point Tests ---

    async def test_get_muster_point_success(self):
        """GET /muster-points/{id} returns full muster point details."""
        self.current_mock_user = self.admin_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = self.sample_point
        self.mock_session.execute.return_value = mp_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/muster-points/{self.mp_id}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["id"], str(self.mp_id))
        self.assertEqual(data["name"], "Bellandur Gate Roll Call")
        self.assertAlmostEqual(data["latitude"], 12.9260, places=4)
        self.assertAlmostEqual(data["longitude"], 77.6740, places=4)
        self.assertEqual(data["geofence_radius_meters"], 150)

    async def test_get_muster_point_missing(self):
        """GET /muster-points/{id} returns HTTP 404 if not found."""
        self.current_mock_user = self.admin_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = None
        self.mock_session.execute.return_value = mp_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/muster-points/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )

        self.assertEqual(res.status_code, 404)

    async def test_get_muster_point_cross_ward_supervisor_denied(self):
        """Supervisor trying to read a point in an unassigned ward receives HTTP 403."""
        self.current_mock_user = self.supervisor_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = self.sample_point

        no_assignment_result = MagicMock()
        no_assignment_result.scalars().first.return_value = None

        self.mock_session.execute.side_effect = [mp_result, no_assignment_result]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get(
                f"/api/v1/muster-points/{self.mp_id}",
                headers={"Authorization": f"Bearer {self.supervisor_token}"},
            )

        self.assertEqual(res.status_code, 403)

    # --- 4. Partial Update Tests ---

    async def test_patch_muster_point_partial_update(self):
        """PATCH updates name and geofence radius while keeping coordinates unchanged."""
        self.current_mock_user = self.admin_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = self.sample_point
        self.mock_session.execute.return_value = mp_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                f"/api/v1/muster-points/{self.mp_id}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={
                    "name": "Updated Station Name",
                    "geofence_radius_meters": 200,
                },
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["name"], "Updated Station Name")
        self.assertEqual(data["geofence_radius_meters"], 200)
        self.assertAlmostEqual(data["latitude"], 12.9260, places=4)
        self.assertAlmostEqual(data["longitude"], 77.6740, places=4)
        self.mock_session.commit.assert_awaited_once()

    async def test_patch_muster_point_coordinates(self):
        """PATCH updates latitude and longitude correctly."""
        self.current_mock_user = self.admin_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = self.sample_point
        self.mock_session.execute.return_value = mp_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                f"/api/v1/muster-points/{self.mp_id}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={
                    "latitude": 12.9350,
                    "longitude": 77.6850,
                },
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertAlmostEqual(data["latitude"], 12.9350, places=4)
        self.assertAlmostEqual(data["longitude"], 77.6850, places=4)

    async def test_patch_muster_point_prohibits_ward_id_or_id(self):
        """Clients attempting to change id or ward_id in PATCH receive HTTP 422."""
        self.current_mock_user = self.admin_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                f"/api/v1/muster-points/{self.mp_id}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"ward_id": str(uuid.uuid4())},
            )

        self.assertEqual(res.status_code, 422)

    async def test_patch_muster_point_empty_payload(self):
        """Empty payload in PATCH returns HTTP 400."""
        self.current_mock_user = self.admin_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = self.sample_point
        self.mock_session.execute.return_value = mp_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                f"/api/v1/muster-points/{self.mp_id}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={},
            )

        self.assertEqual(res.status_code, 400)
        self.assertIn("No fields provided for update", res.json()["detail"])

    # --- 5. Soft Deactivation Tests ---

    async def test_delete_muster_point_soft_deactivation(self):
        """DELETE sets is_active = False without physically deleting the database row."""
        self.current_mock_user = self.admin_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = self.sample_point
        self.mock_session.execute.return_value = mp_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.delete(
                f"/api/v1/muster-points/{self.mp_id}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_active"])
        self.assertEqual(self.sample_point.is_active, False)

        # Critical: Assert database row was NOT deleted
        self.mock_session.delete.assert_not_called()
        self.mock_session.commit.assert_awaited_once()

    async def test_delete_muster_point_missing(self):
        """DELETE returns HTTP 404 for non-existent muster point."""
        self.current_mock_user = self.admin_user

        mp_result = MagicMock()
        mp_result.scalars().first.return_value = None
        self.mock_session.execute.return_value = mp_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.delete(
                f"/api/v1/muster-points/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )

        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
