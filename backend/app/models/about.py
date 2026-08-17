import uuid
from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime


def _uuid() -> str:
    return str(uuid.uuid4())


class AboutPage(Base):
    """Single global content row for the "About" page (open-source
    attributions + product info) — same "one fixed row, lazily created"
    shape as BMSettings/CategoryRule, since this is one shared page for the
    whole install, not per-tenant data. Editable by admins only; readable
    by anyone signed in. Seeded with real content by migration 089 rather
    than left to get_or_create's fallback empty string, since a blank About
    page on a fresh install would be a worse first impression than a
    slightly-stale one."""
    __tablename__ = "about_page"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=lambda: "global")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # Flat {package_key: version} JSON snapshot from the most recent
    # Regenerate — the baseline the *next* Regenerate diffs freshly-detected
    # versions against to compute AboutVersionChange rows below. Not touched
    # by a manual Edit (PUT /about), only by regenerate_about() — a hand
    # edit isn't a version-detection event.
    last_versions_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class AboutPageVersion(Base):
    """A full-content snapshot of AboutPage, archived immediately before
    every overwrite (both a manual PUT and a Regenerate) — the "backup so
    nothing is lost" safety net. Same "copy the whole row before it
    changes" spirit as Docs' own versioning (docs.py's Doc model), but a
    separate archive table rather than Doc's "every save is a new row in
    the same table" shape, since AboutPage is a fixed single row keyed by
    id="global" elsewhere in the codebase (BMSettings/CategoryRule
    convention) and every caller of GET /about expects one object back,
    not a list — restructuring that to Doc's multi-row shape would be a
    much bigger change for no real benefit here."""
    __tablename__ = "about_page_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # When this snapshot was *current* (i.e. the row's own updated_at at the
    # moment it got superseded) — distinct from archived_at below, which is
    # when it was written to this table (always ~now, on the next change).
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    archived_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # "manual_edit" | "regenerate" | "restore" — which action superseded
    # this snapshot, shown in the History list so an admin can tell a
    # deliberate edit from an automated regenerate at a glance.
    source: Mapped[str] = mapped_column(String(16), nullable=False)


class AboutVersionChange(Base):
    """One row per detected package version change, populated only by
    regenerate_about() (about.py) diffing freshly-detected versions
    against AboutPage.last_versions_json — the structured "package X:
    1.2.3 -> 1.3.0" changelog, same from/to shape as JAR Analyser's own
    JarDiffReport dependency diffs (jar_analyser.py's DiffEngine), but
    computed automatically on every regenerate rather than needing two
    reports picked by hand. old_version is null the first time a package
    is ever detected (nothing to diff against yet)."""
    __tablename__ = "about_version_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    package_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_version: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False, index=True)
