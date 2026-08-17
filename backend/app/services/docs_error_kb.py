"""Error-KB entries as ordinary Docs — the JAR Analyser's error lookup no
longer has its own table; it now lives as one Doc per entry, organised into
one Library per category (Keystone, RabbitMQ, SSL/TLS, ...), each doc
encoding its regex match pattern and severity as two parseable metadata
lines at the top of otherwise-normal markdown. A doc with no **Pattern:**
line is just a regular doc and is skipped by KB search/diagnosis — the
pattern line is both the functional field and the "this is a KB entry"
marker, so no separate flag/table is needed.

Template a KB doc's content follows (see render_kb_doc_content):

    **Severity:** critical
    **Pattern:** `PKIX path building failed|unable to find valid certification path`

    Java cannot verify the server's certificate because the signing CA is
    not in the JVM trust store.

    ## Likely Causes

    - The server presents a self-signed or internal CA certificate ...

    ## Fix Steps

    1. Import the root/intermediate CA into the JVM trust store: ...

    ## See Also

    - [[SSL handshake failure]]
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.docs import Doc, DocLibrary, DocShelf, KbMatchCount

_SEVERITY_RE = re.compile(r"^\*\*Severity:\*\*\s*(\w+)\s*$", re.MULTILINE)
_PATTERN_RE = re.compile(r"^\*\*Pattern:\*\*\s*`(.+)`\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*-\s+(.+)$", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)")


def _section_body(content: str, heading: str) -> str | None:
    for m in _HEADING_RE.finditer(content):
        if m.group(1).strip().lower() == heading.lower():
            start = m.end()
            nxt = _HEADING_RE.search(content, start)
            return content[start:(nxt.start() if nxt else len(content))]
    return None


def parse_kb_doc(content: str) -> dict | None:
    """Reconstructs {severity, pattern, plain_english, causes, fix_steps,
    see_also_titles} from a doc's content, or None if it has no **Pattern:**
    line (i.e. it's not a KB entry — an ordinary doc)."""
    pattern_m = _PATTERN_RE.search(content)
    if not pattern_m:
        return None
    severity_m = _SEVERITY_RE.search(content)

    meta_end = max(m.end() for m in (pattern_m, severity_m) if m)
    first_heading = _HEADING_RE.search(content)
    intro_end = first_heading.start() if first_heading else len(content)
    plain_english = content[meta_end:intro_end].strip()

    causes_body = _section_body(content, "Likely Causes") or ""
    fix_steps_body = _section_body(content, "Fix Steps") or ""
    see_also_body = _section_body(content, "See Also") or ""

    return {
        "severity": (severity_m.group(1).lower() if severity_m else "medium"),
        "pattern": pattern_m.group(1),
        "plain_english": plain_english,
        "causes": [m.group(1).strip() for m in _BULLET_RE.finditer(causes_body)],
        "fix_steps": [m.group(1).strip() for m in _NUMBERED_RE.finditer(fix_steps_body)],
        "see_also_titles": [m.group(1).strip() for m in _WIKILINK_RE.finditer(see_also_body)],
    }


async def fetch_all_current_docs_with_paths(db: AsyncSession, tenant_id: str, is_global_admin: bool) -> list[dict]:
    """Every doc's latest version, tenant-scoped, joined with its shelf/library
    names — the raw material for build_kb_entries(), shared by both the
    /docs/error-kb/search endpoint and JAR Analyser's diagnose/questionnaire/
    diagnostic-bundle analysers (which used to read a dedicated jar_kb_entries
    table; that table's data now lives here as ordinary docs). Takes plain
    tenant_id/is_global_admin rather than a full AuthContext so background
    tasks (which outlive the request's AuthContext) can call this too."""
    subq = (
        select(Doc.shelf_id, Doc.name, func.max(Doc.version).label("max_version"))
        .where(Doc.deleted_at.is_(None))
        .group_by(Doc.shelf_id, Doc.name)
        .subquery()
    )
    query = (
        select(Doc, DocShelf.id, DocShelf.name, DocLibrary.id, DocLibrary.name)
        .join(subq, (Doc.shelf_id == subq.c.shelf_id) & (Doc.name == subq.c.name) & (Doc.version == subq.c.max_version))
        .join(DocShelf, Doc.shelf_id == DocShelf.id)
        .join(DocLibrary, DocShelf.library_id == DocLibrary.id)
        .where(Doc.deleted_at.is_(None))
    )
    if not is_global_admin:
        query = query.where(Doc.tenant_id == tenant_id)
    rows = (await db.execute(query)).all()
    return [
        {
            "id": doc.id, "name": doc.name, "content": doc.content,
            "shelf_id": shelf_id, "shelf_name": shelf_name,
            "library_id": library_id, "library_name": library_name,
        }
        for doc, shelf_id, shelf_name, library_id, library_name in rows
    ]


def build_kb_entries(docs: list[dict]) -> list[dict]:
    """docs: list of {"id","name","content","library_id","library_name",
    "shelf_id","shelf_name"} (latest version only). Returns the legacy
    KBEntry-shape dict list (id/category/severity/pattern/title/
    plain_english/causes/fix_steps/see_also) that search_kb() and
    diagnose() already expect — category is the doc's library name, id is
    the doc's own UUID (stable, already unique — no separate slug scheme
    needed), see_also is resolved from [[Doc Title]] wiki-links to sibling
    doc ids. Docs without a **Pattern:** line are silently skipped."""
    name_to_id = {d["name"].strip().lower(): d["id"] for d in docs}
    entries: list[dict] = []
    for d in docs:
        parsed = parse_kb_doc(d["content"])
        if parsed is None:
            continue
        see_also = [
            name_to_id[t.strip().lower()]
            for t in parsed["see_also_titles"]
            if t.strip().lower() in name_to_id
        ]
        entries.append({
            "id": d["id"],
            "category": d["library_name"],
            "severity": parsed["severity"],
            "pattern": parsed["pattern"],
            "title": d["name"],
            "plain_english": parsed["plain_english"],
            "causes": parsed["causes"],
            "fix_steps": parsed["fix_steps"],
            "see_also": see_also,
            "doc_id": d["id"],
            "library_id": d["library_id"],
            "library_name": d["library_name"],
            "shelf_id": d["shelf_id"],
            "shelf_name": d["shelf_name"],
        })
    return entries


async def record_kb_matches(db: AsyncSession, doc_ids: list[str]) -> None:
    """Bumps match_count/last_matched_at for every KB entry that matched
    real error text (Improvements Plan Stage 16) — called from both places
    that run search_kb()/diagnose() against real pasted/scanned text: the
    Docs Search tab's pattern mode and JAR Analyser's Diagnose. Not called
    for topic-mode search (a keyword browse, not a pattern match) or the
    background bundle/questionnaire log scanners (a much larger, less
    clearly "a diagnose run" surface — see the plan doc's own scoping note
    on this). Flushes but doesn't commit — the caller's existing commit
    covers this too, same as every other mutation helper in this codebase."""
    unique_ids = list(dict.fromkeys(doc_ids))  # de-dupe, preserve order
    if not unique_ids:
        return
    now = datetime.now(timezone.utc)
    existing = {
        row.doc_id: row
        for row in (await db.execute(
            select(KbMatchCount).where(KbMatchCount.doc_id.in_(unique_ids))
        )).scalars().all()
    }
    for doc_id in unique_ids:
        row = existing.get(doc_id)
        if row:
            row.match_count += 1
            row.last_matched_at = now
        else:
            db.add(KbMatchCount(doc_id=doc_id, match_count=1, last_matched_at=now))
    await db.flush()


async def fetch_kb_usage(db: AsyncSession, kb_entries: list[dict]) -> list[dict]:
    """Merges match_count/last_matched_at (Improvements Plan Stage 16) onto
    each KB entry dict for the "most/least matched" usage view — an entry
    with no KbMatchCount row (never matched) gets count 0 / last_matched_at
    None rather than being silently omitted, since "never matched" is
    exactly the signal this view exists to surface."""
    doc_ids = [e["id"] for e in kb_entries]
    if not doc_ids:
        return []
    rows = (await db.execute(
        select(KbMatchCount).where(KbMatchCount.doc_id.in_(doc_ids))
    )).scalars().all()
    counts = {r.doc_id: r for r in rows}
    result = []
    for e in kb_entries:
        row = counts.get(e["id"])
        result.append({
            **e,
            "match_count": row.match_count if row else 0,
            "last_matched_at": row.last_matched_at.isoformat() if row else None,
        })
    return result


def render_kb_doc_content(
    severity: str, pattern: str, plain_english: str,
    causes: list[str], fix_steps: list[str], see_also_titles: list[str],
) -> str:
    """Assembles a KB doc's markdown content from form fields — the inverse
    of parse_kb_doc(), used by the create/edit KB entry form."""
    lines = [f"**Severity:** {severity}", f"**Pattern:** `{pattern}`", ""]
    if plain_english.strip():
        lines += [plain_english.strip(), ""]
    if causes:
        lines += ["## Likely Causes", ""]
        lines += [f"- {c}" for c in causes]
        lines += [""]
    if fix_steps:
        lines += ["## Fix Steps", ""]
        lines += [f"{i + 1}. {s}" for i, s in enumerate(fix_steps)]
        lines += [""]
    if see_also_titles:
        lines += ["## See Also", ""]
        lines += [f"- [[{t}]]" for t in see_also_titles]
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"
