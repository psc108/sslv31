"""Improvements Plan Stage 12 — automated cross-report bug pattern scan.

Hooked into the JAR Analyser pipeline right after a report finishes
persisting (see job.py's AnalysisJob.run()): scans the corpus of existing
open bugs for anything that looks related to what THIS analysis just found,
using the same scoring path as the Bug Tracker's own duplicate-suggestion
assist (app.services.bug_similarity) — so a user opening a freshly-analysed
report can immediately see "this looks like it might be affecting known
bugs X, Y, Z" without first having to go file a bug to discover that.

Deliberately best-effort: any failure here is logged and swallowed, never
allowed to fail the analysis run itself — this is a nice-to-have signal on
top of a successful analysis, not a required step.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.bug_tracker import Bug
from app.models.jar_analyser import AnalysisReport, SubReport
from app.services.bug_similarity import find_similar_bugs, find_similar_bugs_fts

logger = logging.getLogger(__name__)

# Matches the "My Open Bugs" dashboard card's own definition of "open"
# (Improvements Plan Stage 4/5) — still-actionable bugs, not resolved/closed/
# wont-fix ones. A closed bug isn't "this might be affecting your upload
# too," it's history.
_OPEN_STATUSES = ("open", "investigating")

# Findings JSON can get large on a big multi-jar upload — bounded so the
# FTS5 MATCH/word-overlap pass stays cheap and dominated by signal, not by
# an enormous tail of low-value tokens.
_MAX_SCAN_TEXT_LEN = 4000


def _report_scan_text(report: AnalysisReport, sub_reports: list[SubReport]) -> str:
    """Text to score bugs against, built from what an analysis actually
    *found* — consistency findings, actuator exposure risks, errors/
    warnings — plus each sub-report's purpose narrative. Deliberately not
    the raw manifest/dependency/class dumps also stored on these rows,
    which would just be noise for this kind of matching."""
    parts: list[str] = []
    for field_name in ("consistency_findings_json", "actuator_exposure_json", "errors_json", "warnings_json"):
        raw = getattr(report, field_name, None)
        if raw:
            parts.append(raw)
    for sr in sub_reports:
        if sr.purpose_narrative_json:
            parts.append(sr.purpose_narrative_json)
    return " ".join(parts)[:_MAX_SCAN_TEXT_LEN]


async def scan_for_related_bugs(db: AsyncSession, report: AnalysisReport) -> list[str]:
    """Returns matching open bug ids, best-first, scoped to the report's own
    tenant. Never raises — a scan failure is logged and treated as "found
    nothing" so it can never break the analysis pipeline it's hooked into."""
    try:
        sub_reports = (await db.execute(
            select(SubReport).where(SubReport.parent_report_id == report.id)
        )).scalars().all()
        scan_text = _report_scan_text(report, list(sub_reports))
        if not scan_text.strip():
            return []

        query = select(Bug).where(
            Bug.deleted_at.is_(None), Bug.status.in_(_OPEN_STATUSES), Bug.tenant_id == report.tenant_id,
        )

        if settings.is_sqlite:
            candidate_ids = await find_similar_bugs_fts(db, "", scan_text, limit=5)
            if not candidate_ids:
                return []
            query = query.where(Bug.id.in_(candidate_ids))
            bugs = (await db.execute(query)).scalars().all()
            rank_index = {bid: i for i, bid in enumerate(candidate_ids)}
            ranked = sorted(bugs, key=lambda b: rank_index.get(b.id, len(candidate_ids)))[:5]
        else:
            bugs = (await db.execute(query)).scalars().all()
            ranked = find_similar_bugs("", scan_text, list(bugs), limit=5)

        return [b.id for b in ranked]
    except Exception:
        logger.exception("Cross-report bug pattern scan failed for report %s", report.id)
        return []
