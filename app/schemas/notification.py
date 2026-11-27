import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    message: str
    notification_type: str
    is_read: bool
    read_at: Optional[datetime] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[uuid.UUID] = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    total_count: int
    unread_count: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class NotificationCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    message: str = Field(..., min_length=2)
    notification_type: str = Field(default="SYSTEM", max_length=50)
    related_entity_type: Optional[str] = Field(default=None, max_length=50)
    related_entity_id: Optional[uuid.UUID] = None
