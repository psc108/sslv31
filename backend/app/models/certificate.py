import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, TZDateTime as DateTime

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class Certificate(Base, TimestampMixin):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    serial: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    profile: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # server, client, code_sign, email, custom
    subject_json: Mapped[str] = mapped_column(Text, nullable=False)
    san_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    key_algo: Mapped[str] = mapped_column(String(16), nullable=False)
    key_size: Mapped[int] = mapped_column(Integer, nullable=False)
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # Fernet-encrypted
    chain_pem: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Signing CA reference (nullable for externally-signed certificates)
    signing_ca_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("certificate_authorities.id"), nullable=True
    )

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="valid", index=True
    )  # valid, revoked, expired, held
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    held_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Renewal tracking
    renewed_from: Mapped[str | None] = mapped_column(String(64), nullable=True)  # serial of predecessor
    renewed_to: Mapped[str | None] = mapped_column(String(64), nullable=True)  # serial of successor
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)

    # Tags / labels for filtering
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Monitoring flags
    expiry_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    repeated_key_download: Mapped[bool] = mapped_column(Boolean, default=False)

    # Multi-tenancy
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default=DEFAULT_TENANT_ID
    )

    # Relationships
    signing_ca: Mapped["CertificateAuthority"] = relationship(
        "CertificateAuthority", back_populates="certificates"
    )

    __table_args__ = (
        Index("ix_certificates_status_expires", "status", "expires_at"),
    )
