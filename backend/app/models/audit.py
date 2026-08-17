from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime as DateTime


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    operator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    api_key_hint: Mapped[str | None] = mapped_column(String(72), nullable=True)  # holds 'jwt:<username>' too
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Multi-tenancy
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default="00000000-0000-0000-0000-000000000001"
    )

    __table_args__ = (
        Index("ix_audit_events_type_timestamp", "event_type", "timestamp"),
    )
