"""Unit tests for Stage 3's static cross-validation checks — DTO/schema and
service-wiring consistency. Pure dict-level tests, no bytecode/JAR needed,
matching the same fast/offline pattern as the persistence regression tests.
"""
from __future__ import annotations

from app.services.jar_analyser.dto_schema_consistency import (
    check_dto_schema_consistency,
    check_event_payload_resolution,
    check_cross_service_dto_resolution_gaps,
)
from app.services.jar_analyser.service_wiring_consistency import check_service_wiring_consistency
from app.services.jar_analyser.schema_reconstructor import reconstruct_schema


# ---------------------------------------------------------------------------
# DTO field type vs column type
# ---------------------------------------------------------------------------

def _migration(sql: str, tables_affected: list[str]) -> dict:
    return {"version": "1", "content": sql, "tables_affected": tables_affected, "description": "init"}


def test_flags_genuine_type_mismatch():
    migrations = [_migration(
        "CREATE TABLE orders (id INT PRIMARY KEY, total INT);", ["orders"]
    )]
    schema = reconstruct_schema(migrations)
    endpoints = [{
        "signature_key": "GET:/orders/{id}",
        "controller_simple": "OrderController",
        "return_type": {"simple_type": "OrderDto", "generic_parameter": "unknown"},
    }]
    dto_schemas = [{
        "simple_name": "OrderDto",
        "fields": [{"name": "total", "simple_type": "String"}],  # DTO says String, column is INT
    }]
    table_map = {"GET:/orders/{id}": ["orders"]}

    findings = check_dto_schema_consistency(endpoints, dto_schemas, table_map, schema)
    assert len(findings) == 1
    assert findings[0]["field"] == "total"
    assert findings[0]["column"] == "total"


def test_does_not_flag_compatible_types():
    migrations = [_migration(
        "CREATE TABLE orders (id INT PRIMARY KEY, total BIGINT);", ["orders"]
    )]
    schema = reconstruct_schema(migrations)
    endpoints = [{
        "signature_key": "GET:/orders/{id}",
        "controller_simple": "OrderController",
        "return_type": {"simple_type": "OrderDto", "generic_parameter": "unknown"},
    }]
    dto_schemas = [{
        "simple_name": "OrderDto",
        "fields": [{"name": "total", "simple_type": "Long"}],  # Long vs BIGINT — compatible
    }]
    table_map = {"GET:/orders/{id}": ["orders"]}

    findings = check_dto_schema_consistency(endpoints, dto_schemas, table_map, schema)
    assert findings == []


def test_does_not_flag_boolean_backed_by_tinyint():
    """TINYINT is MySQL/Hibernate's standard boolean-storage convention —
    a real analysis run against production data found 292 near-identical
    false positives from exactly this pattern before this test was added."""
    migrations = [_migration(
        "CREATE TABLE blob_table (id INT PRIMARY KEY, basic_content TINYINT);", ["blob_table"]
    )]
    schema = reconstruct_schema(migrations)
    endpoints = [{
        "signature_key": "GET:/blobs/{id}",
        "controller_simple": "BlobController",
        "return_type": {"simple_type": "BlobDto", "generic_parameter": "unknown"},
    }]
    dto_schemas = [{
        "simple_name": "BlobDto",
        "fields": [{"name": "basicContent", "simple_type": "boolean"}],
    }]
    table_map = {"GET:/blobs/{id}": ["blob_table"]}

    findings = check_dto_schema_consistency(endpoints, dto_schemas, table_map, schema)
    assert findings == []


def test_does_not_flag_unmatched_field_names():
    """No high-confidence name match — silently skipped, not a finding."""
    migrations = [_migration("CREATE TABLE orders (id INT PRIMARY KEY);", ["orders"])]
    schema = reconstruct_schema(migrations)
    endpoints = [{
        "signature_key": "GET:/orders/{id}",
        "controller_simple": "OrderController",
        "return_type": {"simple_type": "OrderDto", "generic_parameter": "unknown"},
    }]
    dto_schemas = [{
        "simple_name": "OrderDto",
        "fields": [{"name": "somethingElseEntirely", "simple_type": "String"}],
    }]
    table_map = {"GET:/orders/{id}": ["orders"]}

    findings = check_dto_schema_consistency(endpoints, dto_schemas, table_map, schema)
    assert findings == []


def test_unwraps_generic_wrapper_type():
    """Page<OrderDto> should resolve to OrderDto, not 'Page'."""
    migrations = [_migration("CREATE TABLE orders (id INT PRIMARY KEY, total VARCHAR(255));", ["orders"])]
    schema = reconstruct_schema(migrations)
    endpoints = [{
        "signature_key": "GET:/orders",
        "controller_simple": "OrderController",
        "return_type": {"simple_type": "Page", "generic_parameter": "OrderDto"},
    }]
    dto_schemas = [{
        "simple_name": "OrderDto",
        "fields": [{"name": "total", "simple_type": "Integer"}],  # mismatch vs VARCHAR
    }]
    table_map = {"GET:/orders": ["orders"]}

    findings = check_dto_schema_consistency(endpoints, dto_schemas, table_map, schema)
    assert len(findings) == 1
    assert findings[0]["dto"] == "OrderDto"


# ---------------------------------------------------------------------------
# Event payload resolution
# ---------------------------------------------------------------------------

def test_flags_unresolved_event_payload():
    event_files = [{
        "filename": "Order.event.yml",
        "published": [{"entity": "Order", "payload_class": "com.example.dto.OrderEvent"}],
    }]
    findings = check_event_payload_resolution(event_files, dto_schemas=[])
    assert len(findings) == 1
    assert findings[0]["payload_class"] == "com.example.dto.OrderEvent"


def test_does_not_flag_resolved_event_payload():
    event_files = [{
        "filename": "Order.event.yml",
        "published": [{"entity": "Order", "payload_class": "com.example.dto.OrderEvent"}],
    }]
    dto_schemas = [{"simple_name": "OrderEvent", "fields": []}]
    findings = check_event_payload_resolution(event_files, dto_schemas)
    assert findings == []


def test_does_not_flag_when_no_payload_class_claimed():
    event_files = [{"filename": "Order.event.yml", "published": [{"entity": "Order", "payload_class": None}]}]
    findings = check_event_payload_resolution(event_files, dto_schemas=[])
    assert findings == []


# ---------------------------------------------------------------------------
# Service wiring consistency
# ---------------------------------------------------------------------------

def test_flags_nginx_reference_to_unknown_service():
    sub_reports = [
        {"filename": "frontend.conf", "service_name": None,
         "installer_metadata": {"nginx": {"service_dependencies": ["catalog", "ghost-service"]}}},
        {"filename": "catalog-installer.jar", "service_name": "catalog", "installer_metadata": {}},
    ]
    findings = check_service_wiring_consistency(sub_reports)
    assert len(findings) == 1
    assert findings[0]["referenced_service"] == "ghost-service"


def test_handles_naming_convention_differences():
    """serviceInstances (camelCase, frontend/nginx key style) should match
    service-instances (kebab-case, real service_name) — not a false positive."""
    sub_reports = [
        {"filename": "frontend.conf", "service_name": None,
         "installer_metadata": {"nginx": {"service_dependencies": ["serviceInstances-upstream"]}}},
        {"filename": "service-instances-installer.jar", "service_name": "service-instances", "installer_metadata": {}},
    ]
    findings = check_service_wiring_consistency(sub_reports)
    assert findings == []


def test_flags_frontend_reference_to_unknown_service():
    sub_reports = [
        {"filename": "portal-ui-installer.jar", "service_name": "portal-ui",
         "installer_metadata": {"frontend": {"api_urls": [{"key": "mystery-service.url", "value": "${x}"}]}}},
    ]
    findings = check_service_wiring_consistency(sub_reports)
    assert len(findings) == 1
    assert findings[0]["type"] == "frontend_references_unknown_service"


def test_no_findings_when_everything_matches():
    sub_reports = [
        {"filename": "frontend.conf", "service_name": None,
         "installer_metadata": {"nginx": {"service_dependencies": ["catalog"]}}},
        {"filename": "catalog-installer.jar", "service_name": "catalog", "installer_metadata": {}},
    ]
    findings = check_service_wiring_consistency(sub_reports)
    assert findings == []


# ---------------------------------------------------------------------------
# Cross-service / shared-library DTO resolution gaps
# ---------------------------------------------------------------------------

def test_flags_type_resolved_in_a_different_service():
    sub_reports = [
        {
            "service_name": "ticketing",
            "dto_schemas": [],  # CommonAddress not defined in ticketing's own JAR
            "endpoints": [{
                "signature_key": "GET:/tickets/{id}",
                "return_type": {"simple_type": "CommonAddress", "generic_parameter": "unknown"},
            }],
        },
        {
            "service_name": "commons",
            "dto_schemas": [{"simple_name": "CommonAddress", "fields": []}],
            "endpoints": [],
        },
    ]
    findings = check_cross_service_dto_resolution_gaps(sub_reports)
    assert len(findings) == 1
    assert findings[0]["unresolved_type"] == "CommonAddress"
    assert findings[0]["resolved_in_services"] == ["commons"]


def test_does_not_flag_when_resolved_locally():
    sub_reports = [
        {
            "service_name": "ticketing",
            "dto_schemas": [{"simple_name": "TicketDto", "fields": []}],
            "endpoints": [{
                "signature_key": "GET:/tickets/{id}",
                "return_type": {"simple_type": "TicketDto", "generic_parameter": "unknown"},
            }],
        },
    ]
    findings = check_cross_service_dto_resolution_gaps(sub_reports)
    assert findings == []


def test_does_not_flag_primitives_or_unresolved_anywhere():
    sub_reports = [
        {
            "service_name": "ticketing",
            "dto_schemas": [],
            "endpoints": [
                {"signature_key": "GET:/a", "return_type": {"simple_type": "String", "generic_parameter": "unknown"}},
                {"signature_key": "GET:/b", "return_type": {"simple_type": "TrulyNowhereDefined", "generic_parameter": "unknown"}},
            ],
        },
    ]
    findings = check_cross_service_dto_resolution_gaps(sub_reports)
    assert findings == []
