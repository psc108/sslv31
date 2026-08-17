"""Certificate Transparency log models — append-only Merkle tree."""

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, Index, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, TZDateTime as DateTime

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class CTLogEntry(Base, TimestampMixin):
    """Single entry in the internal CT log (append-only Merkle tree leaf)."""
    __tablename__ = "ct_log_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Position in the log (monotonically increasing)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)

    # Certificate data
    cert_serial: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cert_der_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 of DER
    issuer_ca_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    subject_cn: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    san_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Merkle tree
    leaf_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # H(0x00 || entry)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # SCT (Signed Certificate Timestamp)
    sct_json: Mapped[str] = mapped_column(Text, nullable=False)  # {version, log_id, timestamp, signature}

    # Tenant
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default=DEFAULT_TENANT_ID)

    __table_args__ = (
        Index("ix_ct_log_subject_cn", "subject_cn"),
        Index("ix_ct_log_timestamp", "timestamp"),
        Index("ix_ct_log_tenant", "tenant_id"),
    )


class CTTreeHead(Base):
    """Signed Tree Head — snapshot of Merkle tree state."""
    __tablename__ = "ct_tree_heads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tree_size: Mapped[int] = mapped_column(Integer, nullable=False)
    root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)  # HMAC of root_hash
