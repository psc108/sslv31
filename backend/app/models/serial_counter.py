"""Serial counter model for database-backed serial number allocation."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SerialCounter(Base):
    """Per-CA monotonic serial counter for provably unique serial numbers."""

    __tablename__ = "serial_counters"

    ca_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    format: Mapped[str] = mapped_column(
        String(32), nullable=False, default="random"
    )  # random, sequential, timestamp
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="")
