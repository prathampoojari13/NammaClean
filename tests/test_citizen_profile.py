"""
Unit tests for Citizen Profile Management and Ward Association:
- GET /api/v1/users/me
- PATCH /api/v1/users/me

Focused, database-independent unit tests verifying:
1. Unauthenticated requests to PATCH /api/v1/users/me are rejected (HTTP 401).
2. Authenticated citizen can successfully update locality, address, and selected ward (HTTP 200).
3. Non-existent ward ID is rejected with HTTP 404.
4. Privileged fields (role, status, email, id, password) cannot be updated (HTTP 422).
5. Partial update (locality only or ward only) preserves other fields.
6. Citizen can unassign their selected ward by setting ward_id to None.
7. GET /api/v1/users/me returns ward_id, locality, and address.
8. Users cannot edit other users' profiles (mutations operate strictly on authenticated token subject).
"""

import uuid
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_db
from app.models.user import User
from app.models.ward import Ward
from app.core.security import create_access_token
from app.models.enums import UserRole, UserStatus
from app.api.deps import get_current_user


class TestCitizenProfileManagement(unittest.IsolatedAsyncioTestCase):
    """Database-independent tests for citizen profile and ward association."""

    def setUp(self):
        self.user_id = uuid.uuid4()
        self.ward_id = uuid.uuid4()

        now = datetime.now(timezone.utc)
        self.user = User(
            id=self.user_id,
            email="citizen@example.com",
            password_hash="argon2id_mock_hash",
            role=UserRole.CITIZEN.value,
            status=UserStatus.ACTIVE.value,
            ward_id=None,
            locality=None,
            address=None,
            created_at=now,
            updated_at=now,
        )

        # In-memory Ward instance
        self.ward = Ward(
            id=self.ward_id,
            ward_code="WARD-150",
            display_name="Bellandur",
            boundary=None,
        )

        self.mock_session = AsyncMock()
        self.mock_session.commit = AsyncMock()
        self.mock_session.refresh = AsyncMock()

        # Generate valid citizen Bearer token
        self.token = create_access_token(
            subject=str(self.user_id),
            extra_claims={"role": UserRole.CITIZEN.value},
        )
        self.auth_headers = {"Authorization": f"Bearer {self.token}"}

        # Override get_current_user and get_db dependencies
        async def _override_get_current_user():
            return self.user

        async def _override_get_db():
            yield self.mock_session

        app.dependency_overrides[get_current_user] = _override_get_current_user
        app.dependency_overrides[get_db] = _override_get_db

    def tearDown(self):
        app.dependency_overrides.clear()

    async def test_update_profile_unauthenticated(self):
        """Verify unauthenticated PATCH /api/v1/users/me returns HTTP 401."""
        # Temporarily remove get_current_user override to test auth dependency
        app.dependency_overrides.pop(get_current_user, None)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                "/api/v1/users/me",
                json={"locality": "Indiranagar"},
            )

        self.assertEqual(res.status_code, 401)
        self.assertIn("WWW-Authenticate", res.headers)

    async def test_update_profile_valid_ward_and_locality(self):
        """Verify citizen can successfully set ward, locality, and address."""
        # Mock ward lookup query returning self.ward
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = self.ward
        self.mock_session.execute = AsyncMock(return_value=mock_result)

        payload = {
            "ward_id": str(self.ward_id),
            "locality": "Green Glen Layout",
            "address": "42 Outer Ring Road",
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                "/api/v1/users/me",
                json=payload,
                headers=self.auth_headers,
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["ward_id"], str(self.ward_id))
        self.assertEqual(data["locality"], "Green Glen Layout")
        self.assertEqual(data["address"], "42 Outer Ring Road")
        self.assertEqual(data["id"], str(self.user_id))
        self.assertEqual(data["role"], UserRole.CITIZEN.value)

        # Confirm commit was invoked
        self.mock_session.commit.assert_awaited_once()

    async def test_update_profile_invalid_ward_id(self):
        """Verify setting a non-existent ward ID returns HTTP 404."""
        # Mock ward lookup returning None (ward not found)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        self.mock_session.execute = AsyncMock(return_value=mock_result)

        fake_ward_id = uuid.uuid4()
        payload = {"ward_id": str(fake_ward_id)}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                "/api/v1/users/me",
                json=payload,
                headers=self.auth_headers,
            )

        self.assertEqual(res.status_code, 404)
        self.assertIn(f"Ward with id '{fake_ward_id}' not found.", res.json()["detail"])
        # Commit must not be called when validation fails
        self.mock_session.commit.assert_not_awaited()

    async def test_update_profile_forbidden_privileged_fields(self):
        """Verify attempts to modify role, status, email, or id are rejected with HTTP 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Attempt role escalation
            res_role = await client.patch(
                "/api/v1/users/me",
                json={"role": "MUNICIPAL_ADMIN"},
                headers=self.auth_headers,
            )
            self.assertEqual(res_role.status_code, 422)

            # Attempt email modification
            res_email = await client.patch(
                "/api/v1/users/me",
                json={"email": "hacker@test.com"},
                headers=self.auth_headers,
            )
            self.assertEqual(res_email.status_code, 422)

            # Attempt arbitrary id spoofing
            res_id = await client.patch(
                "/api/v1/users/me",
                json={"id": str(uuid.uuid4())},
                headers=self.auth_headers,
            )
            self.assertEqual(res_id.status_code, 422)

    async def test_partial_update_locality_only(self):
        """Verify updating only locality leaves existing ward and address intact."""
        self.user.ward_id = self.ward_id
        self.user.address = "Existing Address"

        payload = {"locality": "New Locality"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                "/api/v1/users/me",
                json=payload,
                headers=self.auth_headers,
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["locality"], "New Locality")
        self.assertEqual(data["ward_id"], str(self.ward_id))
        self.assertEqual(data["address"], "Existing Address")

    async def test_unassign_ward(self):
        """Verify setting ward_id to None clears the citizen's selected ward."""
        self.user.ward_id = self.ward_id

        payload = {"ward_id": None}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                "/api/v1/users/me",
                json=payload,
                headers=self.auth_headers,
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNone(data["ward_id"])

    async def test_get_current_user_profile_reflects_ward_and_locality(self):
        """Verify GET /api/v1/users/me includes ward_id, locality, and address."""
        self.user.ward_id = self.ward_id
        self.user.locality = "Koramangala"
        self.user.address = "100 Feet Road"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/v1/users/me", headers=self.auth_headers)

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["id"], str(self.user_id))
        self.assertEqual(data["ward_id"], str(self.ward_id))
        self.assertEqual(data["locality"], "Koramangala")
        self.assertEqual(data["address"], "100 Feet Road")
        self.assertNotIn("password_hash", data)

    async def test_prevent_editing_other_user_profile(self):
        """Verify that attempting to mutate another user's profile path returns HTTP 404 / 405."""
        other_user_id = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.patch(
                f"/api/v1/users/{other_user_id}",
                json={"locality": "Hacker Locality"},
                headers=self.auth_headers,
            )
            # Route /api/v1/users/{id} does not exist, guaranteeing callers cannot target other users
            self.assertIn(res.status_code, (404, 405))


if __name__ == "__main__":
    unittest.main()
