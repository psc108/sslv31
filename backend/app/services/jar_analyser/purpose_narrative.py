"""Stage 6 of the dissection accuracy plan — service purpose/intention narrative.

New capability: nothing elsewhere in this tool synthesises a narrative — every
other view is a mechanical listing of extracted facts. This module combines
signals already extracted by earlier stages (domain vocabulary, event
topology role, DB ownership, dependency fingerprint, part.yml categorisation,
auth posture, and Stage 4's authored annotation text) into a "Perceived
Purpose" summary per sub-report.

Hard constraint (non-negotiable, per the plan): every inferred statement is
phrased as "Based on the following static evidence, this service appears
to..." with the evidence cited inline — never asserted as fact. Statements
built from data that IS a direct fact (part.yml categorisation, developer-
authored @Operation/@Schema text) are marked `is_inference: False` and phrased
plainly instead, since hedging a fact would be dishonest in the other
direction.

This is a purely static, rule-based synthesiser — no live system access, no
model inference, only recombination of data this tool already extracted.
"""
from __future__ import annotations

import re
from collections import Counter

# Structural/technical words that don't carry domain meaning on their own —
# excluded so "CustomerDto" contributes "customer", not "customer" + "dto".
_STRUCTURAL_STOPWORDS = {
    "dto", "entity", "controller", "service", "resource", "impl", "repository",
    "response", "request", "id", "ids", "list", "lists", "map", "maps", "set",
    "sets", "object", "objects", "base", "abstract", "config", "configuration",
    "util", "utils", "helper", "helpers", "factory", "builder", "manager",
    "handler", "handlers", "exception", "exceptions", "event", "events",
    "model", "models", "info", "metadata", "type", "types", "value", "values",
    "result", "results", "wrapper", "bean", "component", "table", "tables",
    "column", "columns", "field", "fields", "key", "keys", "name", "names",
    "status", "code", "codes", "number", "numbers", "date", "dates", "time",
    "times", "flag", "flags", "count", "total", "summary", "detail", "details",
    "record", "records", "row", "rows", "view", "views", "form", "forms",
    "filter", "filters", "param", "params", "parameter", "parameters", "body",
    "bodies", "header", "headers", "query", "queries", "page", "pages", "size",
    "sizes", "enum", "enums", "data", "impl2", "v1", "v2", "v3",
}

_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# @Operation/@Schema description text is developer-authored prose, but often
# includes markdown sub-sections (roles-allowed lists, example request/response
# JSON bodies) meant for API-reference docs, not a one-line purpose summary.
# Everything from the first sub-heading onward is dropped for the narrative —
# the full text remains available verbatim on the endpoint/schema itself.
_HEADING_SPLIT = re.compile(r"#{2,6}\s")
_WHITESPACE = re.compile(r"\s+")
_SNIPPET_MAX_LEN = 200


def _clean_snippet(text: str) -> str:
    head = _HEADING_SPLIT.split(text, maxsplit=1)[0]
    head = head.replace("**", "").replace("`", "")
    head = _WHITESPACE.sub(" ", head).strip()
    if len(head) > _SNIPPET_MAX_LEN:
        head = head[:_SNIPPET_MAX_LEN].rstrip() + "…"
    return head

_CLOUD_VENDOR_HINTS = [
    (("aws", "amazonaws"), "AWS"),
    (("azure",), "Azure"),
    (("google", "gcp"), "Google Cloud"),
]


def _split_identifier(name: str) -> list[str]:
    s = _WORD_BOUNDARY.sub(" ", name).replace("_", " ").replace("-", " ")
    return [w.lower() for w in s.split() if len(w) >= 3]


def _domain_vocabulary(sr) -> dict | None:
    counter: Counter[str] = Counter()
    examples: dict[str, str] = {}

    def _feed(source: str, weight: int) -> None:
        for word in _split_identifier(source):
            if word in _STRUCTURAL_STOPWORDS or word.isdigit():
                continue
            counter[word] += weight
            examples.setdefault(word, source)

    for s in sr.dto_schemas:
        _feed(s.get("simple_name", ""), weight=3)
    for ms in sr.migration_scripts:
        for t in ms.get("tables_affected") or []:
            _feed(t, weight=2)
    for ep in sr.endpoints:
        _feed(ep.get("controller_simple", ""), weight=1)

    top = [(w, c) for w, c in counter.most_common(8) if c >= 2][:5]
    if not top:
        return None
    return {"terms": [{"term": w, "weight": c, "example": examples[w]} for w, c in top]}


def _event_topology(sr) -> dict | None:
    published = sum(len(ef.get("published", []) or []) for ef in sr.event_files)
    consumed = sum(len(ef.get("consumed", []) or []) for ef in sr.event_files)
    if published == 0 and consumed == 0:
        return None
    if published > consumed * 2:
        role = "primarily a publisher of domain events (a likely system-of-record)"
    elif consumed > published * 2:
        role = "primarily a consumer of upstream domain events (a likely downstream adapter)"
    else:
        role = "both a publisher and a consumer of domain events"
    return {"published_count": published, "consumed_count": consumed, "role": role}


def _db_ownership(sr) -> dict | None:
    tables: set[str] = set()
    for ms in sr.migration_scripts:
        tables.update(ms.get("tables_affected") or [])
    if not tables:
        return None
    return {"tables": sorted(tables), "migration_count": len(sr.migration_scripts)}


def _scheduled_jobs_signal(sr) -> dict | None:
    jobs = getattr(sr, "scheduled_jobs", None) or []
    if not jobs:
        return None
    return {"count": len(jobs), "examples": [j.get("display", "") for j in jobs[:3]]}


def _dependency_fingerprint(sr) -> list[dict]:
    findings = []
    for d in sr.dependencies:
        if d.get("category") != "cloud_sdk":
            continue
        haystack = f"{d.get('group_id') or ''} {d.get('artifact_id') or ''}".lower()
        vendor = next((v for tokens, v in _CLOUD_VENDOR_HINTS if any(t in haystack for t in tokens)), None)
        if vendor:
            findings.append({"vendor": vendor, "artifact": d.get("artifact_id") or d.get("filename")})
    return findings


def _auth_posture(sr) -> dict | None:
    total = len(sr.endpoints)
    if total == 0:
        return None
    public = admin_gated = authenticated_only = 0
    for ep in sr.endpoints:
        sec = ep.get("security")
        pa = sec.get("parsed_auth") if sec else None
        if not pa:
            continue
        if pa.get("public"):
            public += 1
        elif pa.get("roles") or pa.get("authorities"):
            admin_gated += 1
        elif pa.get("authenticated_only"):
            authenticated_only += 1
    return {"total": total, "public": public, "admin_gated": admin_gated, "authenticated_only": authenticated_only}


def _authored_text(sr) -> list[str]:
    """Short, clean snippets for the narrative — prefer @Operation(summary=...)
    since it's already meant to be a one-liner by OpenAPI convention; only fall
    back to the (usually much longer) description, and clean it, when no
    summary was authored."""
    texts: list[str] = []
    seen: set[str] = set()
    for ep in sr.endpoints:
        raw = ep.get("doc_summary") or ep.get("doc_description")
        if not raw:
            continue
        t = _clean_snippet(raw)
        if t and t not in seen:
            seen.add(t)
            texts.append(t)
    for s in sr.dto_schemas:
        raw = s.get("description")
        if not raw:
            continue
        t = _clean_snippet(raw)
        if t and t not in seen:
            seen.add(t)
            texts.append(t)
    return texts[:4]


def compute_purpose_narrative(sr) -> list[dict]:
    """Build the "Perceived Purpose" statement list for one sub-report.

    `sr` is a SubReportData instance (or anything exposing the same
    attributes) — called after endpoints/dependencies/dto_schemas/migration
    scripts/event files have all been populated for this sub-report.
    """
    statements: list[dict] = []

    authored = _authored_text(sr)
    if authored:
        statements.append({
            "category": "authored_intent",
            "is_inference": False,
            "text": "Developer-authored documentation (from @Operation/@Schema annotations):",
            "evidence": authored,
        })

    if sr.group_name or sr.service_name:
        statements.append({
            "category": "platform_categorisation",
            "is_inference": False,
            "text": (
                f"The platform's own part.yml categorises this service as '{sr.service_name}'"
                + (f" in group '{sr.group_name}'." if sr.group_name else ".")
            ),
            "evidence": {"group": sr.group_name, "name": sr.service_name},
        })

    vocab = _domain_vocabulary(sr)
    if vocab:
        term_list = ", ".join(f"{t['term']} (e.g. {t['example']})" for t in vocab["terms"])
        statements.append({
            "category": "domain_vocabulary",
            "is_inference": True,
            "text": f"Based on the following static evidence — DTO, database table, and controller names "
                    f"most frequently referencing: {term_list} — this service appears to manage data related "
                    f"to those concepts.",
            "evidence": vocab["terms"],
        })

    topology = _event_topology(sr)
    if topology:
        statements.append({
            "category": "event_topology",
            "is_inference": True,
            "text": f"Based on the following static evidence — this service publishes "
                    f"{topology['published_count']} event type(s) and consumes {topology['consumed_count']} — "
                    f"this service appears to be {topology['role']}.",
            "evidence": topology,
        })

    scheduled = _scheduled_jobs_signal(sr)
    if scheduled:
        example_list = "; ".join(scheduled["examples"])
        statements.append({
            "category": "scheduled_jobs",
            "is_inference": True,
            "text": f"Based on the following static evidence — {scheduled['count']} @Scheduled job(s) declared "
                    f"in code (e.g. {example_list}) — this service appears to perform periodic/background "
                    f"processing in addition to handling requests.",
            "evidence": scheduled,
        })

    ownership = _db_ownership(sr)
    if ownership:
        table_list = ", ".join(ownership["tables"][:10])
        more = f" and {len(ownership['tables']) - 10} more" if len(ownership["tables"]) > 10 else ""
        statements.append({
            "category": "db_ownership",
            "is_inference": True,
            "text": f"Based on the following static evidence — {ownership['migration_count']} Flyway migration "
                    f"script(s) defining/managing tables: {table_list}{more} — this service appears to be the "
                    f"system of record for that data.",
            "evidence": ownership,
        })

    for dep in _dependency_fingerprint(sr):
        statements.append({
            "category": "dependency_fingerprint",
            "is_inference": True,
            "text": f"Based on the following static evidence — a bundled dependency on {dep['artifact']} — "
                    f"this service appears to integrate with {dep['vendor']}.",
            "evidence": dep,
        })

    posture = _auth_posture(sr)
    if posture and (posture["admin_gated"] or posture["public"]):
        if posture["admin_gated"] and not posture["public"]:
            audience = "an internal/administrative audience"
        elif posture["public"] and not posture["admin_gated"]:
            audience = "general end-user or public consumption"
        else:
            audience = "a mixed audience (some public, some admin-gated endpoints)"
        statements.append({
            "category": "auth_posture",
            "is_inference": True,
            "text": f"Based on the following static evidence — of {posture['total']} endpoints, "
                    f"{posture['public']} are public and {posture['admin_gated']} are role/authority-gated — "
                    f"this service appears intended for {audience}.",
            "evidence": posture,
        })

    return statements
