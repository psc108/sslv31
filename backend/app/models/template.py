import uuid

from sqlalchemy import Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CertificateTemplate(Base, TimestampMixin):
    __tablename__ = "certificate_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Constraints (JSON-encoded lists/values)
    allowed_key_algos: Mapped[str] = mapped_column(Text, nullable=False, default='["RSA","ECDSA","Ed25519"]')
    min_key_size: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    max_validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=398)
    allowed_san_types: Mapped[str] = mapped_column(Text, nullable=False, default='["dns","ip","email","uri"]')
    require_san: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Key usage / EKU (JSON lists)
    key_usage: Mapped[str] = mapped_column(Text, nullable=False, default='[]')
    extended_key_usage: Mapped[str] = mapped_column(Text, nullable=False, default='[]')

    # Subject constraints
    allowed_cn_pattern: Mapped[str] = mapped_column(String(255), nullable=False, default="")  # regex, empty = any
    require_org: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Built-in flag (cannot be deleted)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Approval workflow
    require_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Key escrow (only for encryption profiles)
    escrow_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
