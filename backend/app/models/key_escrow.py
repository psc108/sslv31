import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, TZDateTime as DateTime

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class KeyEscrow(Base, TimestampMixin):
    """Escrowed private key — encrypted with recovery key, not master key."""
    __tablename__ = "key_escrow"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    certificate_serial: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    certificate_cn: Mapped[str] = mapped_column(String(255), nullable=False)
    profile: Mapped[str] = mapped_column(String(32), nullable=False)
    key_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # Fernet-encrypted with RECOVERY key
    escrowed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    escrowed_by: Mapped[str] = mapped_column(String(255), nullable=False)

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default=DEFAULT_TENANT_ID
    )


class KeyRecoveryRequest(Base, TimestampMixin):
    """M-of-N approval workflow for key recovery."""
    __tablename__ = "key_recovery_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    escrow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("key_escrow.id"), nullable=False
    )
    certificate_serial: Mapped[str] = mapped_column(String(64), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Approval tracking (JSON list of {"user": ..., "at": ...})
    approvals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    approvals_required: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    # Status: pending, approved, completed, denied, expired
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)

    # Time-limited download (1 hour after approval)
    download_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    download_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default=DEFAULT_TENANT_ID
    )
