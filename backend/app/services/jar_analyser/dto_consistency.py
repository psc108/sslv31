"""Cross-service DTO consistency checker.

Groups DTO schemas by simple_name across all sub-reports in a bundle and
flags cases where two or more services define the same class name with
different fields or enum values — a common source of silent integration bugs.
"""
from __future__ import annotations


def _field_key(f: dict) -> str:
    """Stable identity key for a DTO field."""
    return f.get("json_name") or f.get("name") or ""


def _compare_fields(fields_a: list[dict], fields_b: list[dict]) -> list[dict]:
    """Return a list of field-level mismatches between two DTO definitions."""
    map_a = {_field_key(f): f for f in fields_a if _field_key(f)}
    map_b = {_field_key(f): f for f in fields_b if _field_key(f)}

    mismatches: list[dict] = []

    for name in sorted(set(map_a) - set(map_b)):
        mismatches.append({"kind": "FIELD_REMOVED", "field": name,
                           "type_a": map_a[name].get("java_type"), "type_b": None})

    for name in sorted(set(map_b) - set(map_a)):
        mismatches.append({"kind": "FIELD_ADDED", "field": name,
                           "type_a": None, "type_b": map_b[name].get("java_type")})

    for name in sorted(set(map_a) & set(map_b)):
        ta = (map_a[name].get("java_type") or "").strip()
        tb = (map_b[name].get("java_type") or "").strip()
        if ta != tb:
            mismatches.append({"kind": "TYPE_CHANGED", "field": name,
                               "type_a": ta, "type_b": tb})

    return mismatches


def _compare_enums(values_a: list[dict], values_b: list[dict]) -> list[dict]:
    """Return a list of enum value mismatches."""
    def _serialised(v: dict) -> str:
        return v.get("serialised_as") or v.get("name") or ""

    set_a = {_serialised(v) for v in values_a if _serialised(v)}
    set_b = {_serialised(v) for v in values_b if _serialised(v)}

    mismatches: list[dict] = []
    for val in sorted(set_a - set_b):
        mismatches.append({"kind": "ENUM_VALUE_REMOVED", "value": val})
    for val in sorted(set_b - set_a):
        mismatches.append({"kind": "ENUM_VALUE_ADDED", "value": val})
    return mismatches


def check_dto_consistency(sub_reports: list[dict]) -> list[dict]:
    """
    Compare DTO schemas across sub-reports and return conflicts.

    Each sub_report dict must have:
      service_name: str | None
      filename: str
      schemas: list[dict]  — each with simple_name, is_enum, fields, enum_values

    Returns a list of conflict dicts:
      {
        simple_name: str,
        is_enum: bool,
        services: [str, ...],          # all services that define this name
        mismatches: [                  # pairwise mismatches
          {
            service_a: str,
            service_b: str,
            differences: [{ kind, field?, value?, type_a?, type_b? }]
          }
        ],
        definitions: [                 # one entry per service
          { service: str, fields: [...], enum_values: [...] }
        ]
      }
    """
    # Group by simple_name → list of (service_label, schema_dict)
    by_name: dict[str, list[tuple[str, dict]]] = {}
    for sub in sub_reports:
        label = sub.get("service_name") or sub.get("filename") or "unknown"
        for schema in sub.get("schemas", []):
            name = schema.get("simple_name") or ""
            if not name:
                continue
            by_name.setdefault(name, []).append((label, schema))

    conflicts: list[dict] = []

    for simple_name, entries in sorted(by_name.items()):
        if len(entries) < 2:
            continue  # only one service defines this — no conflict possible

        is_enum = any(e[1].get("is_enum") for _, e in entries)

        # Deduplicate by service (keep first occurrence per service)
        seen_services: dict[str, dict] = {}
        for label, schema in entries:
            if label not in seen_services:
                seen_services[label] = schema

        if len(seen_services) < 2:
            continue

        service_labels = list(seen_services.keys())

        # Pairwise comparison — compare each pair once
        pairwise: list[dict] = []
        labels = service_labels
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                svc_a, svc_b = labels[i], labels[j]
                schema_a = seen_services[svc_a]
                schema_b = seen_services[svc_b]

                if is_enum:
                    diffs = _compare_enums(
                        schema_a.get("enum_values") or [],
                        schema_b.get("enum_values") or [],
                    )
                else:
                    diffs = _compare_fields(
                        schema_a.get("fields") or [],
                        schema_b.get("fields") or [],
                    )

                if diffs:
                    pairwise.append({
                        "service_a": svc_a,
                        "service_b": svc_b,
                        "differences": diffs,
                    })

        if not pairwise:
            continue  # identical across all services — no conflict

        definitions = []
        for svc, schema in seen_services.items():
            definitions.append({
                "service": svc,
                "fields": schema.get("fields") or [],
                "enum_values": schema.get("enum_values") or [],
            })

        conflicts.append({
            "simple_name": simple_name,
            "is_enum": is_enum,
            "services": service_labels,
            "mismatches": pairwise,
            "definitions": definitions,
        })

    return conflicts
