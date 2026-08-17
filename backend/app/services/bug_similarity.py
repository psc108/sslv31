"""Bug similarity scoring — shared by the Bug Tracker's own duplicate-
suggestion assist (bug_tracker.py's GET /bugs/similar) and JAR Analyser's
automated cross-report bug pattern scan (jar_analyser/bug_pattern_scan.py,
Improvements Plan Stage 12), so both features rank candidates against the
same corpus identically instead of drifting into two scoring behaviours
over time. Originally lived directly in bug_tracker.py (an api/v1 module);
extracted here so a services-layer caller (the JAR Analyser pipeline)
doesn't have to import from an API route file to reuse it.
"""
import json
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.bug_tracker import Bug

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenise(s: str) -> list[str]:
    return [w for w in _WORD_RE.findall(s.lower()) if len(w) > 2]


def _bug_corpus(b: Bug) -> str:
    tags = " ".join(json.loads(b.tags_json))
    return " ".join(filter(None, [b.title, b.description, b.resolution, tags]))


def find_similar_bugs(title: str, text: str, bugs: list[Bug], limit: int = 5) -> list[Bug]:
    """Word-overlap scoring, matching DocApp's own bug-store.js
    findSimilar() (no AI/embeddings, per the plan). Non-SQLite fallback —
    find_similar_bugs_fts() below is what SQLite deployments actually use."""
    words = _tokenise(f"{title} {text}")
    if not words:
        return []
    scored: list[tuple[Bug, float]] = []
    for b in bugs:
        bwords = set(_tokenise(_bug_corpus(b)))
        overlap = sum(1 for w in words if w in bwords)
        score = overlap / len(words)
        if score > 0.15:
            scored.append((b, score))
    scored.sort(key=lambda pair: -pair[1])
    return [b for b, _score in scored[:limit]]


async def find_similar_bugs_fts(db: AsyncSession, title: str, extra_text: str, limit: int = 5) -> list[str]:
    """FTS5-ranked equivalent of find_similar_bugs() — returns matching bug
    ids in bm25 relevance order (best first), for the caller to fetch and
    tenant-filter.

    Deliberately OR, not AND, between terms: this is a "surface anything
    loosely related" suggestion, not a precise search — requiring every
    word from the input text to also appear in an old bug (bug_tracker.py's
    search_bugs() default) would almost never match real-world phrasing.
    bm25 ranking naturally favours candidates matching *more* terms, which
    is what "most similar first" actually needs here."""
    terms = set(re.findall(r"\w+", f"{title} {extra_text}"))
    if not terms:
        return []
    match_q = " OR ".join(f'"{t}"*' for t in terms)
    rows = (await db.execute(
        text("SELECT id FROM bugs_fts WHERE bugs_fts MATCH :match ORDER BY bm25(bugs_fts) LIMIT :limit"),
        {"match": match_q, "limit": limit * 4},  # over-fetch; tenant filtering happens after
    )).all()
    return [r.id for r in rows]


async def fts_index_bug(db: AsyncSession, bug: Bug) -> None:
    """Keep bugs_fts in sync with a bug's current title/description/tags.
    Every write path that creates or edits one of those fields must call
    this — find_similar_bugs_fts() (and therefore the auto-filer's
    recurrence check, bug_pattern_scan.py) only sees what's indexed here.
    Originally a private helper duplicated implicitly by call site; moved
    here once bug_pattern_scan.py needed the same behaviour a services
    module can't reach by importing a private name from an api/v1 file."""
    if not settings.is_sqlite:
        return
    await db.execute(text("DELETE FROM bugs_fts WHERE id = :id"), {"id": bug.id})
    await db.execute(
        text("INSERT INTO bugs_fts (id, title, description, tags) VALUES (:id, :title, :description, :tags)"),
        {"id": bug.id, "title": bug.title, "description": bug.description, "tags": bug.tags_json},
    )


async def fts_unindex_bug(db: AsyncSession, bug_id: str) -> None:
    if not settings.is_sqlite:
        return
    await db.execute(text("DELETE FROM bugs_fts WHERE id = :id"), {"id": bug_id})
