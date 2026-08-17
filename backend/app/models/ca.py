import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text

from app.models.base import TZDateTime as DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin



class CertificateAuthority(Base, TimestampMixin):
    __tablename__ = "certificate_authorities"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    cn: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_json: Mapped[str] = mapped_column(Text, nullable=False)
    key_algo: Mapped[str] = mapped_column(String(16), nullable=False)  # RSA, ECDSA, Ed25519
    key_size: Mapped[int] = mapped_column(Integer, nullable=False)
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # Fernet-encrypted (NULL = offline root)
    path_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_root: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(32), default="user")  # user, bootstrap

    # Self-referential FK for intermediate CAs
    parent_ca_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("certificate_authorities.id"), nullable=True
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Name constraints (JSON: {"permitted": ["*.example.com"], "excluded": ["*.bad.com"]})
    name_constraints_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Certificate policy
    policy_oid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cps_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # OCSP signing delegation (RFC 6960 §4.2.2.2)
    ocsp_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocsp_key_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # Fernet-encrypted
    ocsp_cert_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Serial number format (NULL = random, "sequential", "timestamp")
    serial_format: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Multi-tenancy
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default="00000000-0000-0000-0000-000000000001"
    )

    # Relationships
    parent: Mapped["CertificateAuthority | None"] = relationship(
        "CertificateAuthority", remote_side="CertificateAuthority.id", back_populates="children"
    )
    children: Mapped[list["CertificateAuthority"]] = relationship(
        "CertificateAuthority", back_populates="parent"
    )
    certificates: Mapped[list["Certificate"]] = relationship(
        "Certificate", back_populates="signing_ca"
    )
