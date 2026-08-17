"""Background retention sweep for the Docs/Bugs Trash (Improvements Plan
Stage 7) — the automatic half of "purged after N days or via an admin
empty-trash action." The manual half is the per-item DELETE /trash/{id}
endpoints in docs.py and bug_tracker.py. Follows the same daily-loop shape
as main.py's other scheduled tasks (e.g. the compliance scanner)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30


async def run_trash_purge_scheduler(session_factory) -> None:
    # Initial delay — let startup settle before the first sweep.
    await asyncio.sleep(180)

    while True:
        try:
            await _purge_expired(session_factory)
        except Exception as e:
            logger.error(f"Trash purge sweep failed: {e}")

        await asyncio.sleep(24 * 3600)


async def _purge_expired(session_factory) -> None:
    from pathlib import Path
    from app.models.docs import Doc
    from app.models.bug_tracker import Bug, BugAttachment

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    async with session_factory() as db:
        docs = (await db.execute(
            select(Doc).where(Doc.deleted_at.is_not(None), Doc.deleted_at < cutoff)
        )).scalars().all()
        for d in docs:
            await db.delete(d)

        bugs = (await db.execute(
            select(Bug).where(Bug.deleted_at.is_not(None), Bug.deleted_at < cutoff)
        )).scalars().all()
        if bugs:
            # Same reasoning as bug_tracker.py's purge_bug endpoint —
            # ondelete=CASCADE only removes the BugAttachment DB rows, not
            # the on-disk files, so delete those explicitly before the bugs
            # (and their attachment rows) are hard-deleted below.
            attachments = (await db.execute(
                select(BugAttachment).where(BugAttachment.bug_id.in_([b.id for b in bugs]))
            )).scalars().all()
            for a in attachments:
                Path(a.stored_path).unlink(missing_ok=True)
        for b in bugs:
            await db.delete(b)

        if docs or bugs:
            await db.commit()
            logger.info(
                f"Trash purge sweep: removed {len(docs)} doc version(s), {len(bugs)} bug(s) "
                f"older than {RETENTION_DAYS} days"
            )
