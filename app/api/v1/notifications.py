"""
Notification endpoints for authenticated users across all roles.
Supports retrieval, filtering (ALL, UNREAD, READ), marking as read, and unread counts.
Enforces strict user isolation: users can only view and update their own notifications.
"""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    UnreadCountResponse,
    NotificationCreateRequest,
)
from app.services.notification_service import (
    get_user_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    create_notification,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    status: str = Query(default="ALL", pattern="^(ALL|UNREAD|READ)$", description="Filter by status"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    """
    Retrieves notifications for the authenticated user.
    """
    items, total_count, unread_count = await get_user_notifications(
        db=db,
        user_id=current_user.id,
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(item) for item in items],
        total_count=total_count,
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountResponse:
    """
    Returns the count of unread notifications for the header badge.
    """
    _, _, unread_count = await get_user_notifications(
        db=db,
        user_id=current_user.id,
        status_filter="ALL",
        limit=1,
        offset=0,
    )
    return UnreadCountResponse(unread_count=unread_count)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_single_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    """
    Marks a specific notification as read.
    Enforces user isolation: returns 404 if not found or belongs to another user.
    """
    notif = await mark_notification_read(db=db, notification_id=notification_id, user_id=current_user.id)
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    await db.commit()
    await db.refresh(notif)
    return NotificationResponse.model_validate(notif)


@router.post("/mark-all-read")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Marks all unread notifications for the user as read.
    """
    updated_count = await mark_all_notifications_read(db=db, user_id=current_user.id)
    await db.commit()
    return {"message": f"Marked {updated_count} notifications as read.", "updated_count": updated_count}


@router.post("/test-trigger", response_model=NotificationResponse)
async def trigger_user_notification(
    payload: NotificationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    """
    Allows user to trigger an in-app notification for themselves (e.g., test vehicle arrival alerts).
    """
    notif = await create_notification(
        db=db,
        user_id=current_user.id,
        title=payload.title,
        message=payload.message,
        notification_type=payload.notification_type,
        related_entity_type=payload.related_entity_type,
        related_entity_id=payload.related_entity_id,
    )
    await db.commit()
    await db.refresh(notif)
    return NotificationResponse.model_validate(notif)
