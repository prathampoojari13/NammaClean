import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    message: str,
    notification_type: str = "SYSTEM",
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[uuid.UUID] = None,
    deduplicate_unread: bool = True,
) -> Notification:
    """
    Creates a new persistent notification for a specific user.
    If deduplicate_unread is True, avoids creating a duplicate unread notification
    for the exact same related entity and type.
    """
    if deduplicate_unread and related_entity_type and related_entity_id:
        stmt_check = select(Notification).where(
            Notification.user_id == user_id,
            Notification.related_entity_type == related_entity_type,
            Notification.related_entity_id == related_entity_id,
            Notification.is_read.is_(False),
        )
        res = await db.execute(stmt_check)
        existing = res.scalars().first()
        if existing:
            # Update timestamp and title/message rather than spamming duplicate notifications
            existing.title = title
            existing.message = message
            existing.notification_type = notification_type
            existing.created_at = datetime.now(timezone.utc)
            await db.flush()
            return existing

    notif = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(notif)
    await db.flush()
    return notif


async def get_user_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    status_filter: str = "ALL",
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Notification], int, int]:
    """
    Fetches notifications for a user with total count and unread count.
    Enforces user isolation.
    """
    # Count unread
    stmt_unread = select(func.count(Notification.id)).where(
        Notification.user_id == user_id,
        Notification.is_read.is_(False),
    )
    res_unread = await db.execute(stmt_unread)
    unread_count = res_unread.scalar() or 0

    # Base query for user
    stmt_base = select(Notification).where(Notification.user_id == user_id)
    if status_filter == "UNREAD":
        stmt_base = stmt_base.where(Notification.is_read.is_(False))
    elif status_filter == "READ":
        stmt_base = stmt_base.where(Notification.is_read.is_(True))

    # Total count matching filter
    stmt_count = select(func.count()).select_from(stmt_base.subquery())
    res_count = await db.execute(stmt_count)
    total_count = res_count.scalar() or 0

    # Fetch items ordered by created_at desc
    stmt_items = stmt_base.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    res_items = await db.execute(stmt_items)
    items = list(res_items.scalars().all())

    return items, total_count, unread_count


async def mark_notification_read(
    db: AsyncSession,
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[Notification]:
    """
    Marks a notification as read, enforcing that the requesting user owns it.
    """
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    )
    res = await db.execute(stmt)
    notif = res.scalars().first()
    if not notif:
        return None

    if not notif.is_read:
        notif.is_read = True
        notif.read_at = datetime.now(timezone.utc)
        await db.flush()
    return notif


async def mark_all_notifications_read(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    """
    Marks all notifications for the user as read.
    """
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )
    res = await db.execute(stmt)
    await db.flush()
    return res.rowcount or 0
