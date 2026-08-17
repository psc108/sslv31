import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, TZDateTime as DateTime

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class ComplianceScan(Base, TimestampMixin):
    """Stores results of automated compliance scans."""
    __tablename__ = "compliance_scans"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scan_type: Mapped[str] = mapped_column(String(32), nullable=False)  # br, cis, full
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")  # completed, failed
    total_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_violations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_warnings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    results_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    scanned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default=DEFAULT_TENANT_ID)
