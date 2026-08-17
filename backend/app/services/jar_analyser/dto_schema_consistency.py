"""DTO field type vs. reconstructed DB column type cross-check.

A static consistency check that doesn't need a live database — cross-
references two extraction passes that already exist independently
(bytecode-derived DTO schemas, and schema_reconstructor.py's Flyway-derived
column types) against each other via table_linker.py's endpoint-to-table
linkage. See Documentation/jar_analyser_dissection_accuracy_plan.md, Stage 3.1.

Deliberately conservative to avoid noise from the inherently fuzzy table-name
linking: only compares fields with a high-confidence name match (exact after
camelCase -> snake_case normalisation — the standard Jackson/JPA convention),
and only flags CLEARLY incompatible type families (e.g. a string DTO field
mapped to a numeric column) — never subtler differences like INT vs BIGINT,
which are compatible in practice.
"""
from __future__ import annotations

import re

from app.services.jar_analyser.schema_reconstructor import TableDef

_CAMEL_TO_SNAKE_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_TO_SNAKE_2 = re.compile(r"([a-z\d])([A-Z])")


def _to_snake_case(name: str) -> str:
    s = _CAMEL_TO_SNAKE_1.sub(r"\1_\2", name)
    s = _CAMEL_TO_SNAKE_2.sub(r"\1_\2", s)
    return s.lower()


# DTO simple_type (lower-cased) -> type family
_DTO_TYPE_FAMILY: dict[str, str] = {
    "string": "text", "uuid": "text", "char": "text", "character": "text",
    "integer": "numeric", "int": "numeric", "long": "numeric", "short": "numeric",
    "biginteger": "numeric", "bigdecimal": "numeric", "double": "numeric", "float": "numeric",
    "number": "numeric",
    "boolean": "boolean",
    "localdate": "datetime", "localdatetime": "datetime", "localtime": "datetime",
    "instant": "datetime", "date": "datetime", "offsetdatetime": "datetime",
    "zoneddatetime": "datetime", "timestamp": "datetime",
}

# SQL data_type substring (checked in order — first match wins, so more
# specific keywords must precede more general ones they'd otherwise be
# swallowed by, e.g. "tinyint" before "int") -> type family.
_SQL_FAMILY_KEYWORDS: list[tuple[str, str]] = [
    ("bool", "boolean"), ("bit", "boolean"),
    # TINYINT is MySQL/JDBC's standard boolean-storage convention (Hibernate,
    # Connector/J, etc. all map a Java boolean to TINYINT) — without this,
    # every boolean-backed-by-TINYINT field in a real MySQL schema is a false
    # positive. This was found and fixed after a real analysis run produced
    # 292 near-identical false-positive findings, all this exact pattern.
    ("tinyint", "boolean"),
    ("timestamp", "datetime"), ("datetime", "datetime"), ("date", "datetime"), ("time", "datetime"),
    ("varchar", "text"), ("char", "text"), ("text", "text"), ("clob", "text"), ("uuid", "text"), ("enum", "text"),
    ("decimal", "numeric"), ("numeric", "numeric"), ("float", "numeric"), ("double", "numeric"),
    ("real", "numeric"), ("int", "numeric"), ("serial", "numeric"),
]


def _dto_field_family(simple_type: str | None) -> str | None:
    if not simple_type:
        return None
    return _DTO_TYPE_FAMILY.get(simple_type.lower())


def _sql_type_family(data_type: str | None) -> str | None:
    if not data_type:
        return None
    lowered = data_type.lower()
    for keyword, family in _SQL_FAMILY_KEYWORDS:
        if keyword in lowered:
            return family
    return None


def _resolve_dto_type_name(field_holder: dict | None) -> str | None:
    """An endpoint's return_type/request_body dict — prefer the unwrapped
    generic parameter (e.g. Page<CatalogItem> -> CatalogItem) over the
    wrapper's own simple_type (e.g. Page, ResponseEntity, List)."""
    if not field_holder:
        return None
    generic = field_holder.get("generic_parameter")
    if generic and generic != "unknown":
        return generic
    return field_holder.get("simple_type")


def check_dto_schema_consistency(
    endpoints: list[dict],
    dto_schemas: list[dict],
    table_map: dict[str, list[str]],
    reconstructed_schema: dict[str, TableDef],
) -> list[dict]:
    """Returns a list of finding dicts, each a high-confidence DTO-field/
    column-type mismatch. Empty list means nothing suspicious was found —
    not proof of correctness, just no *conflicting* static evidence."""
    if not table_map or not reconstructed_schema:
        return []

    dto_by_name = {d["simple_name"]: d for d in dto_schemas if d.get("simple_name")}
    if not dto_by_name:
        return []

    findings: list[dict] = []
    seen: set[tuple] = set()

    for ep in endpoints:
        sig = ep.get("signature_key", "")
        tables = table_map.get(sig)
        if not tables:
            continue

        type_names = [
            _resolve_dto_type_name(ep.get("return_type")),
            _resolve_dto_type_name(ep.get("request_body")),
        ]

        for type_name in filter(None, type_names):
            dto = dto_by_name.get(type_name)
            if not dto or not dto.get("fields"):
                continue

            for table_name in tables:
                table = reconstructed_schema.get(table_name.lower())
                if not table:
                    continue

                for f in dto["fields"]:
                    fname = f.get("name")
                    ftype = f.get("simple_type")
                    if not fname or not ftype:
                        continue

                    col = table.column(_to_snake_case(fname))
                    if not col:
                        continue  # no high-confidence name match — not a finding, just skip

                    dto_family = _dto_field_family(ftype)
                    sql_family = _sql_type_family(col.data_type)
                    if not dto_family or not sql_family or dto_family == sql_family:
                        continue

                    key = (sig, type_name, fname, table_name)
                    if key in seen:
                        continue
                    seen.add(key)

                    findings.append({
                        "type": "dto_column_type_mismatch",
                        "endpoint_signature_key": sig,
                        "controller": ep.get("controller_simple"),
                        "dto": type_name,
                        "field": fname,
                        "field_type": ftype,
                        "table": table_name,
                        "column": col.name,
                        "column_type": col.data_type,
                        "note": (
                            f"{type_name}.{fname} ({ftype}) looks like a '{dto_family}' field but "
                            f"{table_name}.{col.name} ({col.data_type}) looks like '{sql_family}' — "
                            f"worth manually checking — this is a static heuristic, not a live-verified fact."
                        ),
                    })

    return findings


def check_event_payload_resolution(
    event_files: list[dict],
    dto_schemas: list[dict],
) -> list[dict]:
    """An event's declared payload class (set on PublishedEvent.payload_class
    in events.py, resolved against ALL non-framework classes in the JAR) should
    also exist as a structured DTO schema (dto_scanner.py's narrower, endpoint-
    referenced extraction) — if it doesn't, the class exists but this report
    can't show its field shape. See Stage 3.2 of the accuracy plan."""
    if not event_files:
        return []

    dto_names = {d["simple_name"] for d in dto_schemas if d.get("simple_name")}
    findings: list[dict] = []
    seen: set[str] = set()

    for ev in event_files:
        for pub in (ev.get("published") or []):
            payload_class = pub.get("payload_class")
            if not payload_class:
                continue  # no claim made — nothing to check
            simple = payload_class.rsplit(".", 1)[-1]
            if simple in dto_names or simple in seen:
                continue
            seen.add(simple)
            findings.append({
                "type": "event_payload_not_resolved",
                "event_file": ev.get("filename"),
                "entity": pub.get("entity"),
                "payload_class": payload_class,
                "note": (
                    f"Event payload class '{payload_class}' exists in the JAR but wasn't "
                    f"captured as a structured DTO schema — its field shape is unknown to this report."
                ),
            })

    return findings


# Simple type names that are never themselves DTOs — skip these when looking
# for a cross-service match, they'd never legitimately appear as a
# dto_schemas[].simple_name anyway, but guards against coincidental collisions.
_NOT_A_DTO = {
    "String", "Integer", "Long", "Short", "Byte", "Boolean", "Character",
    "Double", "Float", "BigDecimal", "BigInteger", "UUID", "Void", "Object",
    "List", "Set", "Map", "Collection", "ResponseEntity", "Page", "Optional",
}


def check_cross_service_dto_resolution_gaps(sub_reports: list[dict]) -> list[dict]:
    """dto_scanner.py resolves DTO field types by scanning a single service's
    own nested JAR only (see Stage 3.4 of the accuracy plan) — a field type
    that isn't defined in its own service's JAR is silently left unresolved,
    with no indication that the reason is scope rather than the type being
    genuinely uninteresting. In a multi-service jar-of-jars, a shared/commons
    library type is a very plausible explanation: if the same simple name IS
    resolved as a real DTO schema in a *different* service in this same
    bundle, that's worth surfacing directly rather than leaving it opaque.

    This is a detect-and-flag mitigation, not a fix to dto_scanner.py's scan
    scope itself — the field's shape still won't appear in the referencing
    service's own report, but at least this makes visible *why*, and points
    at where the real definition lives in this bundle.
    """
    resolved_index: dict[str, list[str]] = {}
    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename")
        for d in (sr.get("dto_schemas") or []):
            name = d.get("simple_name")
            if name:
                resolved_index.setdefault(name, []).append(svc)

    findings: list[dict] = []
    seen: set[tuple] = set()

    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename")
        own_dto_names = {d.get("simple_name") for d in (sr.get("dto_schemas") or [])}

        for ep in (sr.get("endpoints") or []):
            for holder_key in ("return_type", "request_body"):
                holder = ep.get(holder_key)
                if not holder:
                    continue
                candidate = holder.get("generic_parameter")
                if not candidate or candidate == "unknown":
                    candidate = holder.get("simple_type")
                if not candidate or candidate in own_dto_names or candidate in _NOT_A_DTO:
                    continue

                other_services = sorted({s for s in resolved_index.get(candidate, []) if s != svc})
                if not other_services:
                    continue

                key = (svc, candidate)
                if key in seen:
                    continue
                seen.add(key)

                findings.append({
                    "type": "cross_service_dto_reference",
                    "service": svc,
                    "endpoint_signature_key": ep.get("signature_key"),
                    "unresolved_type": candidate,
                    "resolved_in_services": other_services,
                    "note": (
                        f"'{candidate}' isn't defined in {svc}'s own JAR, but matches a DTO "
                        f"schema found in {', '.join(other_services)} — likely a shared/commons "
                        f"library type. The scanner only searches a single service JAR at a time, "
                        f"so this field's shape is missing here even though it's known elsewhere "
                        f"in the bundle."
                    ),
                })

    return findings
