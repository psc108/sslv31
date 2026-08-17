import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, TypeDecorator, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TZDateTime(TypeDecorator):
    """A DateTime type that normalises timezone-aware datetimes to naive UTC.

    asyncpg is strict: if the column is TIMESTAMP (without tz), it rejects
    tz-aware Python datetimes. This decorator strips tzinfo on bind and
    works transparently with both SQLite and PostgreSQL.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return value


class Base(DeclarativeBase):
    # Override the default DateTime mapping so all models use TZDateTime
    type_annotation_map = {
        datetime: TZDateTime,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
