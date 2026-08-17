"""Improvements Plan Stage 21 — automated cross-job bug pattern scan.

The Build Manager equivalent of JAR Analyser's own cross-report scan
(jar_analyser/bug_pattern_scan.py, Stage 12) — same shared scorer
(app.services.bug_similarity), same shape, same best-effort guarantee.
Hooked into ansible_runner.py's _execute_job() only once a job's outcome
is final (not about to be auto-retried) and actually "failed" — a
succeeded job has nothing to scan for.

Deliberately best-effort: any failure here is logged and swallowed, never
allowed to fail the job pipeline it's hooked into.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.bug_tracker import Bug, BugHistoryEntry, BugOccurrence
from app.models.build_manager import BMJob, BMJobLog, BMSettings
from app.services.bug_similarity import find_similar_bugs, find_similar_bugs_fts, fts_index_bug

logger = logging.getLogger(__name__)

# Distinct from any real username, so an auto-filed bug is obviously not
# human-filed at a glance in the reporter/noted_by column.
_AUTO_REPORTER = "Automated (Ansible failure scan)"

# Same definition of "open" as the JAR Analyser scan and the "My Open Bugs"
# dashboard card (Improvements Plan Stage 4/5).
_OPEN_STATUSES = ("open", "investigating")

# Same bound as the JAR Analyser scan — keeps the FTS5 MATCH/word-overlap
# pass cheap and dominated by signal, not an enormous raw-log tail.
_MAX_SCAN_TEXT_LEN = 4000

# Ansible's own failure markers in its default output format — "fatal:
# [host]: FAILED! => {...}" for a task failure, "fatal: [host]: UNREACHABLE!
# => {...}" for a connection failure. Matching on these substrings rather
# than a stricter regex since verbosity flags/callback plugins can vary the
# surrounding format, but both markers are stable across those.
_FAILURE_MARKERS = ("fatal:", "FAILED!")

# ansible-playbook's own exit codes, for a "what does this number mean"
# hint in an auto-filed bug's description. Codes 2/3/4 are flagged "varies
# by version" deliberately, not guessed as one fixed meaning:
# ansible-playbook's own man page documents 4 as "Parser error", but a
# real, version-spanning report (ansible/ansible#19720, seen on 2.15,
# 2.16, 2.18) shows a plain unreachable host producing exit code 4 too -
# exactly the case this hint exists to help with, so the hedge is real,
# not decorative.
_EXIT_CODE_HINTS = {
    1: "fatal error or exception during the run",
    2: "one or more hosts failed a task, or the run was aborted - meaning varies by Ansible version",
    3: "one or more hosts were unreachable (older Ansible) - meaning varies by Ansible version",
    4: "in current Ansible, most often hosts unreachable (SSH/login issue), though older docs call it a parser error - meaning varies by Ansible version",
    5: "bad or incomplete command-line options passed to ansible-playbook",
    6: "command-line arguments were not UTF-8 encoded",
    8: "an internal task-queue break-play condition",
    99: "the run was interrupted (Ctrl+C)",
    143: "the process was killed (SIGKILL)",
    250: "an unexpected exception - often a module bug or a Jinja templating error",
    255: "an unknown/internal error",
}


def _job_scan_text(job: BMJob, log_lines: list[str]) -> str:
    """Text to score bugs against, built from what the job run actually
    reported failing — the fatal:/FAILED! lines from its own output, plus
    the hostnames Ansible itself flagged and the playbook that was
    running. Deliberately not the full raw log (mostly successful task
    output, pure noise for this kind of matching)."""
    fail_lines = [ln for ln in log_lines if any(m in ln for m in _FAILURE_MARKERS)]
    parts = [job.playbook or ""]
    if job.failed_hosts:
        parts.append(job.failed_hosts)
    parts.extend(fail_lines)
    return " ".join(p for p in parts if p)[:_MAX_SCAN_TEXT_LEN]


async def scan_for_related_bugs(db: AsyncSession, job: BMJob) -> list[str]:
    """Returns matching open bug ids, best-first, scoped to the job's own
    tenant. Never raises — a scan failure is logged and treated as "found
    nothing" so it can never break the job pipeline it's hooked into."""
    try:
        log_rows = (await db.execute(
            select(BMJobLog.line).where(BMJobLog.job_id == job.id).order_by(BMJobLog.timestamp)
        )).scalars().all()
        scan_text = _job_scan_text(job, list(log_rows))
        if not scan_text.strip():
            return []

        query = select(Bug).where(
            Bug.deleted_at.is_(None), Bug.status.in_(_OPEN_STATUSES), Bug.tenant_id == job.tenant_id,
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
        logger.exception("Cross-job bug pattern scan failed for job %s", job.id)
        return []


async def diagnose_job_failure(db: AsyncSession, job: BMJob, log_lines: list[str]) -> list[dict]:
    """Match this job's own failure text against the Error KB - the same
    pattern-matching engine JAR Analyser's own Diagnose action and the
    Docs Search tab's pattern mode already use (app.services.docs_error_kb
    / app.services.jar_analyser.error_kb) - so a known Ansible failure
    surfaces real, curated troubleshooting guidance (causes/fix steps),
    not just a generic "exit code N sometimes means" hint. Returns matched
    KB entries (flat dicts: id/title/severity/causes/fix_steps/...),
    best-first, capped at 5. Never raises - best-effort, same guarantee as
    scan_for_related_bugs above; an empty/no-match result just means no
    KB entry exists yet for this failure, not that nothing went wrong."""
    try:
        scan_text = _job_scan_text(job, log_lines)
        if not scan_text.strip():
            return []
        from app.services.docs_error_kb import build_kb_entries, fetch_all_current_docs_with_paths
        from app.services.jar_analyser.error_kb import search_kb
        docs = await fetch_all_current_docs_with_paths(db, job.tenant_id, is_global_admin=False)
        kb_entries = build_kb_entries(docs)
        return search_kb(scan_text, db_entries=kb_entries, limit=5)
    except Exception:
        logger.exception("Error KB diagnosis failed for job %s", job.id)
        return []


async def get_or_create_bm_settings(db: AsyncSession) -> BMSettings:
    """Fetch the single global settings row, creating it (default off) on
    first use — see BMSettings' own docstring for why this isn't seeded by
    a migration instead."""
    row = (await db.execute(select(BMSettings).where(BMSettings.id == "global"))).scalar_one_or_none()
    if row is None:
        row = BMSettings(id="global")
        db.add(row)
        await db.flush()
    return row


async def maybe_auto_file_bug(db: AsyncSession, job: BMJob, related_bug_ids: list[str]) -> None:
    """Improvements Plan Stage 22 — opt-in. Called right after
    scan_for_related_bugs, with that scan's own result, so it never
    duplicates the work: a match found there is treated as "this is a
    recurrence," bumping a BugOccurrence on the top match instead of
    filing a new bug, so one recurring flaky failure doesn't spawn a fresh
    bug every run. Only reached from ansible_runner.py once a job's
    outcome is final and it isn't dry_run (a --check run didn't actually
    fail anything real).

    Best-effort by design, same guarantee as scan_for_related_bugs: any
    failure here is logged and swallowed, never allowed to break the job
    pipeline it's hooked into."""
    try:
        bm_settings = await get_or_create_bm_settings(db)
        if not bm_settings.auto_file_bugs_on_failure:
            return

        if related_bug_ids:
            top_bug_id = related_bug_ids[0]
            existing = (await db.execute(
                select(BugOccurrence).where(
                    BugOccurrence.bug_id == top_bug_id, BugOccurrence.bm_job_id == job.id,
                )
            )).scalar_one_or_none()
            if existing is None:
                db.add(BugOccurrence(
                    bug_id=top_bug_id, bm_job_id=job.id,
                    note="Automatically linked - this job's failure matched an existing open bug.",
                    noted_by=_AUTO_REPORTER,
                ))
                logger.info("Auto-linked job %s to existing bug %s as a recurrence", job.id, top_bug_id)
            return

        title = f"Job failure: {job.playbook or job.name}"
        if job.failed_hosts:
            title += f" ({job.failed_hosts})"
        exit_hint = _EXIT_CODE_HINTS.get(job.exit_code) if job.exit_code is not None else None
        description = (
            "Automatically filed because this Build Manager job finished failed and no existing "
            "open bug matched closely enough. See the job's own output for full detail - this "
            "description is generated from the failure signal alone, not a root-cause analysis.\n\n"
            f"Playbook: {job.playbook or '(none)'}\n"
            f"Failed hosts: {job.failed_hosts or '(none reported)'}\n"
            f"Exit code: {job.exit_code if job.exit_code is not None else '(none)'}"
            + (f" (commonly: {exit_hint})" if exit_hint else "")
        )

        # Error KB guidance (not just the coarse exit-code hint above) —
        # best-effort, and deliberately does NOT call record_kb_matches:
        # that usage counter is reserved for a real human looking at the
        # match (Improvements Plan Stage 16's own scoping decision), and
        # this auto-filer is exactly the kind of unattended background
        # scanner that decision excluded.
        kb_log_rows = (await db.execute(
            select(BMJobLog.line).where(BMJobLog.job_id == job.id).order_by(BMJobLog.timestamp)
        )).scalars().all()
        kb_matches = await diagnose_job_failure(db, job, list(kb_log_rows))
        if kb_matches:
            kb_lines = ["", "Error KB matches (not yet reviewed by a human):"]
            for m in kb_matches[:3]:
                fix = m["fix_steps"][0] if m["fix_steps"] else None
                kb_lines.append(f"- {m['title']}" + (f" - first fix step: {fix}" if fix else ""))
            description += "\n" + "\n".join(kb_lines)

        bug = Bug(
            tenant_id=job.tenant_id, title=title[:512], description=description,
            severity="medium", bm_job_id=job.id, reporter=_AUTO_REPORTER, auto_created=True,
        )
        db.add(bug)
        await db.flush()
        # Without this, the bug is invisible to future scans' FTS lookup
        # (find_similar_bugs_fts reads bugs_fts, not the bugs table
        # directly) — a recurring failure would keep spawning new bugs
        # instead of ever finding the one already filed for it.
        await fts_index_bug(db, bug)
        db.add(BugHistoryEntry(
            bug_id=bug.id, action="created", to_status="open",
            note="Automatically filed from a failed Build Manager job.", actor=_AUTO_REPORTER,
        ))
        logger.info("Auto-filed bug %s for job %s", bug.id, job.id)
    except Exception:
        logger.exception("Auto bug creation failed for job %s", job.id)
