"""Regression test for the JAR Analyser persistence write-path.

Exercises persist_report() with representative data for every downstream
table it writes to, without needing a real JAR or bytecode extraction — it
directly verifies that every field name persistence.py passes into a model
constructor actually exists on that model and round-trips through a real
(if directly-created, not migrated) schema.

This is a narrower, faster complement to scripts/check_schema_drift.py: that
script catches "declared on the model but no migration creates it"; this test
catches "persistence.py passes a kwarg that isn't even a real attribute on the
model at all" — both are variants of the same class of bug that cost two of
five real analysis runs (see Documentation/jar_analyser_dissection_accuracy_plan.md).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import async_session
from app.models.jar_analyser import (
    JarUpload, AnalysisReport, SubReport,
    JarEndpoint, JarDependency, JarConfigFile,
    JarMigrationScript, JarEventFile, JarDtoSchema, JarWorkflow, JarErrorResponse,
)
from app.services.jar_analyser.job import SubReportData, AnalysisJobResult
from app.services.jar_analyser.persistence import persist_report


def _sample_sub_report() -> SubReportData:
    """One representative item per downstream table persist_report() writes to."""
    return SubReportData(
        filename="sample-service.jar",
        installer_jar="sample-service.jar",
        jar_path=None,  # not read by persist_report
        size_bytes=1234,
        depth=1,
        jar_type="spring_boot_fat",
        detection_confidence=1.0,
        manifest={"main_class": "com.example.App"},
        installer_metadata={},
        service_name="sample",
        declared_port=8080,
        endpoints=[{
            "controller_class": "com.example.SampleController",
            "controller_simple": "SampleController",
            "http_method": "GET",
            "path": "/{id}",
            "full_path": "/sample/{id}",
            "base_path": "/sample",
            "method_name": "getById",
            "parameters": [{"name": "id", "type": "String"}],
            "request_body": None,
            "return_type": {"simple_type": "SampleDto"},
            "security": {"expression": "hasRole('ADMIN')", "parsed_auth": {"roles": ["ADMIN"]}},
            "confidence": "HIGH",
            "source_annotation": "GetMapping",
            "signature_key": "GET:/sample/{id}",
            "deprecated": False,
        }],
        dependencies=[{
            "filename": "spring-web-6.1.0.jar",
            "group_id": "org.springframework",
            "artifact_id": "spring-web",
            "version": "6.1.0",
            "category": "framework",
        }],
        config_files=[{
            "filename": "application.properties",
            "path_in_jar": "BOOT-INF/classes/application.properties",
            "file_type": "properties",
            "content": "server.port=8080",
            "key_count": 1,
            "keys": [{"key": "server.port", "value": "8080", "is_placeholder": False, "category": "port"}],
        }],
        migration_scripts=[{
            "filename": "V1__init.sql",
            "version": "1",
            "description": "init",
            "script_type": "versioned",
            "ddl_operations": ["CREATE TABLE sample"],
            "tables_affected": ["sample"],
            "content": "CREATE TABLE sample (id INT);",
        }],
        event_files=[{
            "filename": "Sample.event.yml",
            "path_in_jar": "BOOT-INF/classes/Sample.event.yml",
            "content": "events: {}",
            "published": [{"name": "SampleCreated"}],
            "consumed": [],
        }],
        dto_schemas=[{
            "class_name": "com.example.dto.SampleDto",
            "simple_name": "SampleDto",
            "is_enum": False,
            "fields": [{"name": "id", "simple_type": "String"}],
        }],
        workflows=[{
            "name": "sample-flow",
            "description": "A sample workflow",
            "category": "test",
            "source": "auto_detected",
            "steps": [{"step": 1}],
        }],
        error_responses=[{
            "http_status": 404,
            "exception_class": "SampleNotFoundException",
            "response_schema_class": "ErrorResponse",
            "scope": "global",
            "fields": [{"name": "message", "simple_type": "String"}],
        }],
    )


@pytest.mark.asyncio
async def test_persist_report_writes_every_downstream_table(setup_db):
    async with async_session() as db:
        upload = JarUpload(
            filename="sample.jar", original_name="sample.jar",
            sha256="0" * 64, md5="0" * 32, size_bytes=1, stored_path="/tmp/sample.jar",
            status="analysing",
        )
        db.add(upload)
        await db.flush()

        report = AnalysisReport(upload_id=upload.id, status="analysing", analyser_version="test")
        db.add(report)
        await db.flush()

        result = AnalysisJobResult(
            report_id=report.id,
            jar_type="jar_of_jars",
            detection_confidence=1.0,
            manifest={},
            summary={},
            sub_reports=[_sample_sub_report()],
            warnings=[],
            errors=[],
            duration_ms=100,
        )

        await persist_report(db, report, upload, result)

        assert report.status == "completed"
        assert report.errors_json is None, f"persist_report reported errors: {report.errors_json}"

        sub = (await db.execute(
            select(SubReport).where(SubReport.parent_report_id == report.id)
        )).scalar_one()

        for model in (JarEndpoint, JarDependency, JarConfigFile, JarMigrationScript,
                      JarEventFile, JarDtoSchema, JarWorkflow, JarErrorResponse):
            row = (await db.execute(
                select(model).where(model.sub_report_id == sub.id)
            )).scalar_one()
            assert row is not None, f"{model.__name__} row was not persisted"


@pytest.mark.asyncio
async def test_persist_report_isolates_a_failing_sub_report(setup_db, monkeypatch):
    """A single sub-report that fails to persist must not discard the others,
    and the report must still complete with the failure recorded, not silently
    swallowed or escalated to a total failure. Reproduces the exact bug found
    and fixed in this stage — see JarEndpoint construction in persistence.py."""
    good = _sample_sub_report()
    good.service_name = "good-service"
    bad = _sample_sub_report()
    bad.service_name = "bad-service"
    # Force this one sub-report's endpoint construction to fail, the same way
    # a stale/mismatched field name did in production.
    bad.endpoints[0]["signature_key"] = object()  # not JSON-serialisable in linked_tables_json lookup path

    async with async_session() as db:
        upload = JarUpload(
            filename="sample2.jar", original_name="sample2.jar",
            sha256="1" * 64, md5="1" * 32, size_bytes=1, stored_path="/tmp/sample2.jar",
            status="analysing",
        )
        db.add(upload)
        await db.flush()

        report = AnalysisReport(upload_id=upload.id, status="analysing", analyser_version="test")
        db.add(report)
        await db.flush()

        result = AnalysisJobResult(
            report_id=report.id,
            jar_type="jar_of_jars",
            detection_confidence=1.0,
            manifest={},
            summary={},
            sub_reports=[good, bad],
            warnings=[],
            errors=[],
            duration_ms=100,
        )

        await persist_report(db, report, upload, result)

        assert report.status == "completed", "one bad sub-report must not fail the whole report"
        assert report.errors_json is not None
        assert "bad-service" in report.errors_json

        subs = (await db.execute(
            select(SubReport).where(SubReport.parent_report_id == report.id)
        )).scalars().all()
        service_names = {s.service_name for s in subs}
        assert "good-service" in service_names
        assert "bad-service" not in service_names
