import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class CertificateSigningRequest(Base, TimestampMixin):
    __tablename__ = "certificate_signing_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # new_key, existing_key
    subject_json: Mapped[str] = mapped_column(Text, nullable=False)
    san_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    key_algo: Mapped[str] = mapped_column(String(16), nullable=False)
    key_size: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(8), nullable=False, default="sha256")
    csr_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # encrypted, optional

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )  # pending, signed, deleted

    # Link to signed certificate (if signed by internal CA)
    signed_cert_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("certificates.id"), nullable=True
    )

    # Multi-tenancy
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default="00000000-0000-0000-0000-000000000001"
    )

    # Relationships
    signed_certificate: Mapped["Certificate | None"] = relationship("Certificate")
