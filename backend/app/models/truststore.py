import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TrustStore(Base, TimestampMixin):
    __tablename__ = "truststores"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    store_type: Mapped[str] = mapped_column(String(8), nullable=False)  # JKS, PKCS12
    ca_ids_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of CA UUIDs
    blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # Multi-tenancy
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False,
        default="00000000-0000-0000-0000-000000000001"
    )
