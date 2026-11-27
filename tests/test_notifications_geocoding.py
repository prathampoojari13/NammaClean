"""
Tests for NammaClean Geocoding and Persistent Notification APIs.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_geocoding_search_landmarks(async_client: AsyncClient):
    """Verify place search returns curated Bengaluru locations."""
    response = await async_client.get("/api/v1/geocoding/search?q=yelahanka")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any("Yelahanka" in item["display_name"] for item in data)
    assert "latitude" in data[0]
    assert "longitude" in data[0]


@pytest.mark.asyncio
async def test_geocoding_reverse_lookup(async_client: AsyncClient):
    """Verify coordinate reverse-geocoding returns localized place name."""
    response = await async_client.get("/api/v1/geocoding/reverse?latitude=13.0985&longitude=77.5895")
    assert response.status_code == 200
    data = response.json()
    assert "display_name" in data
    assert "latitude" in data
    assert "longitude" in data


@pytest.mark.asyncio
async def test_notifications_crud_and_isolation(
    async_client: AsyncClient,
    async_db_session: AsyncSession,
):
    """Verify notifications retrieval, creation, unread count, and user isolation."""
    # User 1
    user1 = User(
        email=f"notif_user1_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    # User 2
    user2 = User(
        email=f"notif_user2_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("ValidPassword123!"),
        role=UserRole.CITIZEN.value,
        status=UserStatus.ACTIVE.value,
    )
    async_db_session.add_all([user1, user2])
    await async_db_session.commit()

    token1 = create_access_token(subject=user1.id)
    token2 = create_access_token(subject=user2.id)

    # 1. Unauthenticated request rejected
    unauth_res = await async_client.get("/api/v1/notifications")
    assert unauth_res.status_code == 401

    # 2. Trigger notification for User 1
    trig_res = await async_client.post(
        "/api/v1/notifications/test-trigger",
        headers={"Authorization": f"Bearer {token1}"},
        json={
            "title": "Welcome Alert",
            "message": "Your complaint has been submitted.",
            "notification_type": "REPORT_UPDATE",
        },
    )
    assert trig_res.status_code == 200
    created_notif = trig_res.json()
    notif_id = created_notif["id"]

    # 3. User 1 unread count is 1
    count_res1 = await async_client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert count_res1.status_code == 200
    assert count_res1.json()["unread_count"] >= 1

    # 4. User 2 cannot see User 1's notifications
    list_res2 = await async_client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert list_res2.status_code == 200
    assert all(item["id"] != notif_id for item in list_res2.json()["items"])

    # 5. User 2 cannot mark User 1's notification as read (HTTP 404)
    read_res2 = await async_client.patch(
        f"/api/v1/notifications/{notif_id}/read",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert read_res2.status_code == 404

    # 6. User 1 marks as read
    read_res1 = await async_client.patch(
        f"/api/v1/notifications/{notif_id}/read",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert read_res1.status_code == 200
    assert read_res1.json()["is_read"] is True

    # 7. Mark all read
    mark_all_res = await async_client.post(
        "/api/v1/notifications/mark-all-read",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert mark_all_res.status_code == 200
