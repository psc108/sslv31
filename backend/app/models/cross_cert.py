"""Cross-certificate model for trust bridge tracking."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, TZDateTime as DateTime

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class CrossCertificate(Base, TimestampMixin):
    __tablename__ = "cross_certificates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # The local CA that issued the cross-certificate
    issuing_ca_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("certificate_authorities.id"), nullable=False
    )
    # Description of the external CA being cross-signed
    external_ca_cn: Mapped[str] = mapped_column(String(255), nullable=False)
    external_ca_subject_json: Mapped[str] = mapped_column(Text, nullable=False)
    external_ca_cert_pem: Mapped[str] = mapped_column(Text, nullable=False)

    # The cross-certificate itself (issued by local CA for external CA's key)
    cross_cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    serial: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Constraints applied
    path_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name_constraints_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active, revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Direction: "outbound" = we trust them, "inbound" = they trust us
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="outbound")

    # Multi-tenancy
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default=DEFAULT_TENANT_ID
    )
