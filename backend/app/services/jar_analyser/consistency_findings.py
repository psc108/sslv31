"""Aggregates all of Stage 3's static cross-validation checks into a single
findings list for a whole jar-of-jars bundle. See
Documentation/jar_analyser_dissection_accuracy_plan.md, Stage 3.

Each individual check is a pure function operating on already-extracted
dicts — no new JAR/bytecode scanning, no live system access. This module's
only job is running them all against the same bundle and tagging each
finding with which check produced it.
"""
from __future__ import annotations

from app.services.jar_analyser.dto_schema_consistency import (
    check_dto_schema_consistency,
    check_event_payload_resolution,
    check_cross_service_dto_resolution_gaps,
)
from app.services.jar_analyser.service_wiring_consistency import check_service_wiring_consistency
from app.services.jar_analyser.schema_reconstructor import reconstruct_schema
from app.services.jar_analyser.table_linker import link_tables


def compute_consistency_findings(sub_reports: list[dict]) -> list[dict]:
    """sub_reports: list of plain dicts (see job.py's SubReportData, converted
    via dataclasses.asdict() by the caller) with at least: service_name,
    filename, installer_metadata, endpoints, dependencies, migration_scripts,
    event_files, dto_schemas."""
    findings: list[dict] = []

    # Per-service checks: DTO-vs-column-type, event payload resolution.
    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename")
        endpoints = sr.get("endpoints") or []
        migration_scripts = sr.get("migration_scripts") or []
        dto_schemas = sr.get("dto_schemas") or []
        event_files = sr.get("event_files") or []

        if endpoints and migration_scripts:
            table_map = link_tables(endpoints, migration_scripts)
            schema = reconstruct_schema(migration_scripts)
            for f in check_dto_schema_consistency(endpoints, dto_schemas, table_map, schema):
                f["service"] = svc
                findings.append(f)

        if event_files:
            for f in check_event_payload_resolution(event_files, dto_schemas):
                f["service"] = svc
                findings.append(f)

    # Bundle-level checks: need every sub-report at once.
    findings.extend(check_service_wiring_consistency(sub_reports))
    findings.extend(check_cross_service_dto_resolution_gaps(sub_reports))

    return findings
