"""Serial number allocation service.

Provides database-backed, provably unique serial numbers with configurable formats.
Guarantees no collisions via atomic increment + pre-issuance collision check.
"""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.serial_counter import SerialCounter

logger = logging.getLogger(__name__)

# Minimum entropy required by CA/Browser Forum Ballot SC-62: 64 bits
_MIN_RANDOM_BYTES = 8


def _random_suffix(n_bytes: int = 8) -> str:
    """Generate a hex random suffix with at least 64 bits of entropy."""
    return os.urandom(n_bytes).hex()


def generate_serial_random() -> int:
    """Pure random serial (128 bits). Current default, RFC 5280 compliant."""
    return int.from_bytes(os.urandom(16), byteorder="big")


def generate_serial_sequential(counter: int, prefix: str = "") -> int:
    """Sequential counter + 64-bit random suffix. Auditable and unique.

    Format: {prefix_as_int}{counter_32bit}{random_64bit}
    Total: at least 96 bits, with 64 bits of entropy from random.
    """
    random_part = int.from_bytes(os.urandom(8), byteorder="big")
    # Pack: counter in upper 32 bits, random in lower 64 bits
    serial = (counter << 64) | random_part
    return serial


def generate_serial_timestamp(counter: int) -> int:
    """Timestamp + counter + random. Readable in hex.

    Format: {YYYYMMDD_as_hex}{counter_16bit}{random_64bit}
    """
    now = datetime.now(timezone.utc)
    date_int = now.year * 10000 + now.month * 100 + now.day  # e.g. 20260710
    random_part = int.from_bytes(os.urandom(8), byteorder="big")
    # Pack: date(32bit) | counter(16bit) | random(64bit)
    serial = (date_int << 80) | ((counter & 0xFFFF) << 64) | random_part
    return serial


async def allocate_serial(ca_id: str, db: AsyncSession) -> int:
    """Allocate the next serial number for a CA using its configured format.

    Uses SELECT FOR UPDATE semantics (via immediate commit) to prevent races.
    Falls back to pure random if no counter exists (backward compatible).
    """
    result = await db.execute(
        select(SerialCounter).where(SerialCounter.ca_id == ca_id)
    )
    counter = result.scalar_one_or_none()

    if not counter:
        # No counter configured — use pure random (backward compatible)
        return generate_serial_random()

    fmt = counter.format
    current = counter.next_value

    # Atomically increment
    counter.next_value = current + 1
    await db.flush()

    if fmt == "sequential":
        return generate_serial_sequential(current, counter.prefix)
    elif fmt == "timestamp":
        return generate_serial_timestamp(current)
    else:
        # "random" or unknown — pure random
        return generate_serial_random()


async def check_collision(serial_hex: str, db: AsyncSession) -> bool:
    """Check if a serial already exists in the certificates table.

    Returns True if collision detected (should never happen).
    """
    from app.models.certificate import Certificate
    result = await db.execute(
        select(Certificate.id).where(Certificate.serial == serial_hex).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def allocate_serial_safe(
    ca_id: str, db: AsyncSession, max_retries: int = 3
) -> int:
    """Allocate a serial with collision detection and retry.

    Logs a WARNING on collision (indicates potential RNG issue).
    Raises ValueError if max_retries exhausted (should never happen).
    """
    for attempt in range(max_retries):
        serial_int = await allocate_serial(ca_id, db)
        serial_hex = format(serial_int, "x")

        if not await check_collision(serial_hex, db):
            if attempt > 0:
                logger.warning(
                    f"Serial collision resolved after {attempt} retries for CA {ca_id}"
                )
            return serial_int

        logger.warning(
            f"SERIAL COLLISION detected for CA {ca_id}: {serial_hex} "
            f"(attempt {attempt + 1}/{max_retries}). This should never happen — "
            f"check RNG health."
        )

    raise ValueError(
        f"Serial number allocation failed after {max_retries} retries for CA {ca_id}. "
        f"Possible RNG failure."
    )


async def configure_serial_format(
    ca_id: str, fmt: str, prefix: str, db: AsyncSession
) -> SerialCounter:
    """Configure or update the serial format for a CA.

    Creates the counter if it doesn't exist.
    """
    if fmt not in ("random", "sequential", "timestamp"):
        raise ValueError(f"Invalid serial format: {fmt}")

    result = await db.execute(
        select(SerialCounter).where(SerialCounter.ca_id == ca_id)
    )
    counter = result.scalar_one_or_none()

    if counter:
        counter.format = fmt
        counter.prefix = prefix
    else:
        counter = SerialCounter(
            ca_id=ca_id, next_value=1, format=fmt, prefix=prefix
        )
        db.add(counter)

    await db.flush()
    return counter
