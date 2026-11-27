import uuid
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Notification(Base):
    """
    Persistent notification entity for NammaClean users.
    Stores role-specific notices, alerts, complaint updates, and vehicle arrival notices.
    Enforces user isolation at database and application levels.
    """
    __tablename__ = "notifications"

    id = sa.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = sa.Column(UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = sa.Column(sa.String(255), nullable=False)
    message = sa.Column(sa.Text, nullable=False)
    notification_type = sa.Column(sa.String(50), nullable=False, default="SYSTEM", index=True)
    is_read = sa.Column(sa.Boolean, nullable=False, default=False, index=True)
    read_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    related_entity_type = sa.Column(sa.String(50), nullable=True)
    related_entity_id = sa.Column(UUID(as_uuid=True), nullable=True)
    created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    user = relationship("User", backref="notifications")
