"""
Unit tests for the Public Ward Selection Endpoint: GET /api/v1/wards.

Focused, database-independent tests verifying:
1. Successful public ward listing without authentication.
2. Response structure conformance (id, name, ward_number).
3. Strict omission of sensitive fields, internal timestamps, and geospatial boundaries.
4. Empty result handling.
5. Query parameter validation (pagination limits and offsets).
6. Authenticated user access (works transparently for citizens as well).
"""

import uuid
import unittest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_db
from app.models.ward import Ward
from app.core.security import create_access_token
from app.models.enums import UserRole


class TestPublicWardSelectionEndpoint(unittest.IsolatedAsyncioTestCase):
    """Database-independent tests for GET /api/v1/wards using dependency overrides."""

    def setUp(self):
        self.ward_1_id = uuid.uuid4()
        self.ward_2_id = uuid.uuid4()

        # Create dummy Ward ORM instances in memory
        self.ward_1 = Ward(
            id=self.ward_1_id,
            ward_code="WARD-150",
            display_name="Bellandur",
            boundary=None,
        )
        self.ward_2 = Ward(
            id=self.ward_2_id,
            ward_code="WARD-174",
            display_name="HSR Layout",
            boundary=None,
        )

        self.mock_session = AsyncMock()
        self.mock_result = MagicMock()
        self.mock_session.execute = AsyncMock(return_value=self.mock_result)

        async def _override_get_db():
            yield self.mock_session

        app.dependency_overrides[get_db] = _override_get_db

    def tearDown(self):
        app.dependency_overrides.clear()

    async def test_public_ward_listing_success(self):
        """Verify unauthenticated client receives HTTP 200 and mapped ward list."""
        self.mock_result.scalars.return_value.all.return_value = [self.ward_1, self.ward_2]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/v1/wards")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)

        first = data[0]
        self.assertEqual(first["id"], str(self.ward_1_id))
        self.assertEqual(first["name"], "Bellandur")
        self.assertEqual(first["ward_number"], "WARD-150")

        second = data[1]
        self.assertEqual(second["id"], str(self.ward_2_id))
        self.assertEqual(second["name"], "HSR Layout")
        self.assertEqual(second["ward_number"], "WARD-174")

    async def test_response_structure_and_sensitive_field_omission(self):
        """Verify response contains ONLY id, name, ward_number and no internal/admin attributes."""
        self.mock_result.scalars.return_value.all.return_value = [self.ward_1]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/v1/wards")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)

        item = data[0]
        # Exactly the three public selection keys must be present
        self.assertEqual(set(item.keys()), {"id", "name", "ward_number"})

        # Explicitly verify sensitive / internal keys are never exposed
        forbidden_keys = [
            "boundary",
            "created_at",
            "updated_at",
            "user_assignments",
            "collection_points",
            "routes",
            "password",
            "status",
        ]
        for key in forbidden_keys:
            self.assertNotIn(key, item, f"Sensitive or extraneous key '{key}' leaked in public wards response!")

    async def test_empty_results(self):
        """Verify HTTP 200 with empty list when no wards exist."""
        self.mock_result.scalars.return_value.all.return_value = []

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/v1/wards")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 0)

    async def test_pagination_parameters_validation(self):
        """Verify query parameters limit and offset validation."""
        self.mock_result.scalars.return_value.all.return_value = [self.ward_1]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Valid pagination
            res_valid = await client.get("/api/v1/wards?limit=10&offset=5")
            self.assertEqual(res_valid.status_code, 200)

            # Invalid limit: 0 (must be ge=1)
            res_invalid_limit_zero = await client.get("/api/v1/wards?limit=0")
            self.assertEqual(res_invalid_limit_zero.status_code, 422)

            # Invalid limit: 501 (must be le=500)
            res_invalid_limit_high = await client.get("/api/v1/wards?limit=501")
            self.assertEqual(res_invalid_limit_high.status_code, 422)

            # Invalid offset: -1 (must be ge=0)
            res_invalid_offset = await client.get("/api/v1/wards?offset=-1")
            self.assertEqual(res_invalid_offset.status_code, 422)

    async def test_authenticated_citizen_access(self):
        """Verify authenticated citizens can access the endpoint transparently."""
        self.mock_result.scalars.return_value.all.return_value = [self.ward_1]
        token = create_access_token(
            subject=str(uuid.uuid4()),
            extra_claims={"role": UserRole.CITIZEN.value},
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"Authorization": f"Bearer {token}"}
            res = await client.get("/api/v1/wards", headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Bellandur")


if __name__ == "__main__":
    unittest.main()
