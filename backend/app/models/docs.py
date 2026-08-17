"""Docs feature database models — Library > Shelf > Doc, plus Annotations.

Stage 1 of the DocApp-in-LabTool plan. Library is a level DocApp's own
source doesn't actually have (its local-mode hierarchy is flat Shelf ->
Document, despite the IndexedDB database being named "docapp_library") —
added deliberately here since it's cheap now and expensive to retrofit
later. Doc keeps DocApp's own "new version row per save" model (an integer
version per name+shelf, full copies not diffs) rather than a separate
revision/diff table, matching what was actually observed in the source.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TZDateTime

# Same default-tenant convention as jar_analyser.py/certificate.py/etc. —
# no shared constant module for this in the codebase, redefined per module.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _uuid() -> str:
    return str(uuid.uuid4())


class DocLibrary(Base):
    __tablename__ = "doc_libraries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, default=DEFAULT_TENANT_ID, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # Improvements Plan Stage 14 — manually-dragged Map View node positions,
    # {doc_id: {"x": float, "y": float}}. Null means "no manual layout yet,
    # let d3-force auto-arrange everything." Lives on the library row rather
    # than a separate per-doc table since a whole layout is always read/
    # written together (one map, one save action), matching this codebase's
    # existing "Text column + # JSON comment" convention for blob data.
    map_layout_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    shelves: Mapped[list["DocShelf"]] = relationship("DocShelf", back_populates="library", cascade="all, delete-orphan")


class DocShelf(Base):
    __tablename__ = "doc_shelves"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    library_id: Mapped[str] = mapped_column(String(36), ForeignKey("doc_libraries.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, default=DEFAULT_TENANT_ID, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    library: Mapped["DocLibrary"] = relationship("DocLibrary", back_populates="shelves")
    docs: Mapped[list["Doc"]] = relationship("Doc", back_populates="shelf", cascade="all, delete-orphan")


class Doc(Base):
    __tablename__ = "docs"
    __table_args__ = (
        # Mirrors DocApp's own [shelfId, name] index — used to find the
        # current-highest-version row for a given document name on a shelf.
        UniqueConstraint("shelf_id", "name", "version", name="uq_doc_shelf_name_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    shelf_id: Mapped[str] = mapped_column(String(36), ForeignKey("doc_shelves.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # New row per save, not an in-place update — matches DocApp's own
    # library-store.js addDocument() behaviour (max(version)+1 per
    # shelf+name, never overwritten). Highest version for a given
    # shelf_id+name is "current".
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, default=DEFAULT_TENANT_ID, index=True
    )
    # Where the issue behind this doc was first observed — a single origin
    # point, not the Bug Tracker's BugOccurrence-style multi-report pattern
    # tracking. Metadata, not content: set/cleared in place via a dedicated
    # endpoint rather than forcing a new version, and carried forward onto
    # the next version whenever the doc is actually next saved. See
    # Documentation/planning/doc_first_seen_plan.md.
    first_seen_report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    first_seen_sub_report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sub_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # Soft-delete — Improvements Plan Stage 7. NULL means live; set means "in
    # Trash," excluded from normal listings/search but recoverable via
    # POST .../restore until the background sweep (app/services/trash_sweep.py)
    # purges it for good after the retention window.
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True, index=True)

    shelf: Mapped["DocShelf"] = relationship("DocShelf", back_populates="docs")
    annotations: Mapped[list["DocAnnotation"]] = relationship("DocAnnotation", back_populates="doc", cascade="all, delete-orphan")


class DocAnnotation(Base):
    __tablename__ = "doc_annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Real FK to a specific doc version — an improvement over DocApp's own
    # annotations-store.js, which links by a docPath *string* rather than a
    # row id (fragile: breaks if a document is renamed/moved).
    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey("docs.id", ondelete="CASCADE"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="yellow")  # yellow|green|blue|pink|orange
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Re-anchoring context so the highlight can be re-located in the
    # rendered document even if surrounding content shifts slightly —
    # matches DocApp's annotations.js findBestMatch() approach exactly.
    prefix: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suffix: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    doc: Mapped["Doc"] = relationship("Doc", back_populates="annotations")


class CategoryRule(Base):
    """Structured View's heading -> category badge mapping (Improvements
    Plan Stage 13). Deliberately global, not tenant-scoped like the rest of
    this file — this is a shared rendering taxonomy (which domain terms map
    to which badge), not tenant-private data, and every tenant benefits from
    the same sensible defaults with no per-tenant seeding step required.
    Replaces what was previously a fixed ~25-pattern regex map hardcoded in
    structuredParse.ts; that same list is this table's seed data (migration
    080), so out-of-the-box behaviour is unchanged until an admin edits it.

    Matched case-insensitively against a heading, first match wins, in
    sort_order ascending — same "first match wins" semantics the old
    hardcoded array had via array iteration order."""
    __tablename__ = "category_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)


class DecodeEvent(Base):
    """Append-only record of each stack trace decode — fingerprint, matched
    KB entries, and ML analysis blob. root_cause_label is null until a human
    (or future feedback endpoint) confirms the actual root cause, at which
    point it becomes a labelled training example for the ML scorer."""
    __tablename__ = "decode_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    stack_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    exception_classes_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list[str]
    matched_kb_ids_json: Mapped[str] = mapped_column(Text, nullable=False)     # JSON list[str]
    ml_analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob
    root_cause_label: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)


class KbMatchCount(Base):
    """Error KB usage tracking (Improvements Plan Stage 16) — how many times
    a KB entry's pattern has actually matched real pasted/scanned error
    text, across both places that run KB pattern matching against real
    text: the Docs "Search" tab's pattern mode and JAR Analyser's report-
    context-aware Diagnose. A simple running counter, not a full event log
    — the plan asks for "match counts" and a "most/least matched" view,
    both of which only need a count and a last-seen timestamp, not a growing
    history table. One row per KB entry (a Doc's id) once it's matched at
    least once; a KB entry that's never matched simply has no row here — the
    usage endpoint treats that as count 0 rather than requiring a row to
    exist upfront for every KB entry."""
    __tablename__ = "kb_match_counts"

    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey("docs.id", ondelete="CASCADE"), primary_key=True)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_matched_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
