"""Bug Tracker feature database models — Stage 1 of the bug tracker plan
(see Documentation/planning/bug_tracker_plan.md).

Deliberately not "full KB-style" (unlike the JAR Analyser KB migration,
which encoded severity/pattern as parseable markdown lines and read them
back on request): a bug has real relational columns for anything the app
needs to query, filter, join, or transition (status, severity, report/
sub-report links, assignee) — markdown text only for the actual prose
(description, resolution). BugOccurrence is the mechanism that answers
"which other reports (or jobs) has this bug shown up on" — a bug has one
primary origin (report_id/sub_report_id, or — since Improvements Plan
Stage 19 — bm_job_id, on Bug itself, where it was first filed) plus
explicit additional links via BugOccurrence, not automatic fuzzy matching.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TZDateTime

# Same default-tenant convention as jar_analyser.py/docs.py/etc.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _uuid() -> str:
    return str(uuid.uuid4())


class Bug(Base):
    __tablename__ = "bugs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, default=DEFAULT_TENANT_ID, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open|investigating|resolved|closed|wont-fix
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")  # critical|high|medium|low
    frequency: Mapped[str | None] = mapped_column(String(16), nullable=True)  # always|intermittent|one-off
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Primary report — where the bug was first filed. Additional reports the
    # same bug has since been spotted on go through BugOccurrence, not here.
    report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sub_report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sub_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A second, independent origin (Improvements Plan Stage 19) — a bug is
    # filed against *either* a JAR Analyser report or a Build Manager job,
    # never both, enforced at the API layer (_validate_bm_job_link in
    # bug_tracker.py) rather than a DB constraint, matching every other
    # cross-field invariant in this codebase. Additive, not a replacement:
    # a bug can still have no origin at all (freestanding), same as today.
    bm_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("bm_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reporter: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Improvements Plan Stage 22 — set when this bug was filed by the
    # opt-in Ansible-failure auto-filer (bug_pattern_scan.py), not a human.
    # A real indexed column rather than a tags_json entry: lets "hide
    # auto-filed" become a real query instead of a tag scan, and can't be
    # accidentally cleared by editing tags the way a tag could be.
    auto_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A real account, not a free-text name — same "actor is an actual user
    # row, not just a logged string" precedent as notification.py's
    # user_id columns (Improvements Plan Stage 4). Lets "My Bugs" filter by
    # a real id instead of fuzzy-matching a name string.
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Self-referential — set when this bug has been explicitly marked as a
    # duplicate of another (see bug_tracker.py's mark_duplicate endpoint).
    # Deliberately distinct from BugOccurrence: an occurrence links one bug
    # to an additional *report/job* it was also seen on; this links two
    # already-independently-filed Bug rows to each other, for the case
    # where two people each filed their own bug for the same underlying
    # issue. Nullable FK rather than a boolean + separate mapping table —
    # a bug can be a duplicate of at most one other bug, so this is enough.
    duplicate_of_bug_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("bugs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # Soft-delete — Improvements Plan Stage 7, same shape as Doc.deleted_at:
    # NULL means live, set means "in Trash" until restored or purged (by
    # hand or by the background retention sweep).
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True, index=True)

    comments: Mapped[list["BugComment"]] = relationship("BugComment", back_populates="bug", cascade="all, delete-orphan")
    history: Mapped[list["BugHistoryEntry"]] = relationship("BugHistoryEntry", back_populates="bug", cascade="all, delete-orphan")
    occurrences: Mapped[list["BugOccurrence"]] = relationship("BugOccurrence", back_populates="bug", cascade="all, delete-orphan")
    attachments: Mapped[list["BugAttachment"]] = relationship("BugAttachment", back_populates="bug", cascade="all, delete-orphan")


class BugComment(Base):
    __tablename__ = "bug_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bug_id: Mapped[str] = mapped_column(String(36), ForeignKey("bugs.id", ondelete="CASCADE"), nullable=False, index=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    bug: Mapped["Bug"] = relationship("Bug", back_populates="comments")


class BugHistoryEntry(Base):
    __tablename__ = "bug_history_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bug_id: Mapped[str] = mapped_column(String(36), ForeignKey("bugs.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # created|status_change|resolved|comment|occurrence_linked|attachment_added
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    bug: Mapped["Bug"] = relationship("Bug", back_populates="history")


class BugOccurrence(Base):
    """A confirmed sighting of an existing Bug on a report (or, since
    Improvements Plan Stage 19, a Build Manager job) other than its primary
    origin — the "find patterns across reports" mechanism. Deliberately
    explicit/human-confirmed, not auto-merged. Every occurrence points at
    exactly one of report_id or bm_job_id (enforced at the API layer,
    _validate report helpers in bug_tracker.py) — report_id became nullable
    in Stage 19 specifically to allow that, not because an occurrence can
    now point nowhere."""
    __tablename__ = "bug_occurrences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bug_id: Mapped[str] = mapped_column(String(36), ForeignKey("bugs.id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sub_report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=True
    )
    bm_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("bm_jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    noted_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    bug: Mapped["Bug"] = relationship("Bug", back_populates="occurrences")


class BugAttachment(Base):
    """A screenshot, log file, or other artefact attached directly to a bug
    (Improvements Plan Stage 18) — the DB row is metadata only, content
    lives on disk at `stored_path`, same "DB row + on-disk file, not a BLOB
    column" split JAR Analyser's upload feature already established. Kept
    deliberately simple relative to that precedent: no content-addressed
    dedup, no SHA256 — attachments here are expected to be small and
    per-bug, not large shared binaries. Deleting a single attachment (its
    own DELETE endpoint) removes the on-disk file immediately; a soft-
    deleted (Trashed) bug leaves its attachments' files alone until the bug
    is actually purged — see purge_bug/_purge_expired, which explicitly
    unlink() each attachment's file at that point, since ondelete=CASCADE
    only cleans up the DB row, never the filesystem."""
    __tablename__ = "bug_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bug_id: Mapped[str] = mapped_column(String(36), ForeignKey("bugs.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    bug: Mapped["Bug"] = relationship("Bug", back_populates="attachments")


class BugActivityCheckpoint(Base):
    """One row per user — "the last time this user checked their bugs."
    Backs the in-app "N bugs need your attention" badge (Improvements Plan
    Stage 5): activity (status changes, occurrences, comments) on a bug
    the user is assigned to or reported, created after this timestamp and
    not by the user themselves, counts as unseen. Kept local to this
    module rather than added to the shared User model/migration, same
    reasoning as everything else built as a bug-tracker-owned concern."""
    __tablename__ = "bug_activity_checkpoints"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
