"""Notification preference model — per-user event subscriptions."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime as DateTime

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    # Event types: expiry_warning, cert_issued, approval_required, approval_decision,
    #              ca_ceremony, security_event, auto_renewal, digest
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optional filter: specific CA ID or tag
    filter_ca_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filter_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Digest mode: batch into daily summary instead of immediate
    digest_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    # Mandatory (admin-set, user cannot disable)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default=DEFAULT_TENANT_ID
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class NotificationQueue(Base):
    """Queued notifications for digest mode."""
    __tablename__ = "notification_queue"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default=DEFAULT_TENANT_ID
    )
