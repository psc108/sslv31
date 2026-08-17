"""JAR Analyser persistence service.

Writes the structured AnalysisJobResult into the database.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.jar_analyser import (
    JarUpload, AnalysisReport, SubReport,
    JarEndpoint, JarDependency, JarConfigFile,
    JarMigrationScript, JarEventFile, JarDtoSchema, JarWorkflow, JarErrorResponse,
    JarScheduledJob, JarConfigExample, JarStringConstant, JarOutboundIntegration,
)

logger = logging.getLogger(__name__)


async def persist_report(
    db: AsyncSession,
    report: AnalysisReport,
    upload: JarUpload,
    result,  # AnalysisJobResult
) -> None:
    """Persist a completed analysis result into the database."""
    now = datetime.now(timezone.utc)

    # Update top-level report
    report.jar_type = result.jar_type
    report.detection_confidence = result.detection_confidence
    report.manifest_json = json.dumps(result.manifest)
    report.summary_json = json.dumps(result.summary)
    report.implementation_title = result.manifest.get("implementation_title")
    report.implementation_version = result.manifest.get("implementation_version")
    report.implementation_vendor = result.manifest.get("implementation_vendor")
    report.spring_boot_version = result.summary.get("spring_boot_version")
    report.build_jdk = result.manifest.get("build_jdk")
    report.analysis_completed_at = now
    report.analysis_duration_ms = result.duration_ms
    report.consistency_findings_json = (
        json.dumps(result.consistency_findings) if getattr(result, "consistency_findings", None) else None
    )
    report.infra_requirements_json = (
        json.dumps(result.infra_requirements) if getattr(result, "infra_requirements", None) else None
    )
    report.actuator_exposure_json = (
        json.dumps(result.actuator_exposure) if getattr(result, "actuator_exposure", None) else None
    )

    # Errors from the extraction phase (per-service, already isolated in job.py) —
    # persistence-phase failures below are appended to this same list.
    persistence_errors: list[str] = list(result.errors)

    # Build proxied-service set once across all sub-reports (needs nginx sub-reports)
    from app.services.jar_analyser.proxy_checker import build_proxied_services, is_service_proxied
    all_sr_dicts = [
        {
            "service_name": sr.service_name,
            "jar_type": sr.jar_type,
            "installer_metadata": sr.installer_metadata,
        }
        for sr in result.sub_reports
    ]
    proxied_services = build_proxied_services(all_sr_dicts)

    # Persist each sub-report — isolated per service via a SAVEPOINT so one bad
    # sub-report (e.g. a persistence-time bug on one service's extracted data)
    # can't discard every other successfully-analysed service. Previously a
    # single failure here escaped to job.py's outer handler and marked the
    # *entire* report (and every already-flushed sub-report) as failed — this
    # is exactly the class of failure that cost 2 of 5 real analysis runs in
    # production data (see Documentation/jar_analyser_dissection_accuracy_plan.md).
    persisted_count = 0
    for sr_data in result.sub_reports:
        svc_label = sr_data.service_name or sr_data.filename
        try:
            async with db.begin_nested():
                sub = SubReport(
                    parent_report_id=report.id,
                    depth=sr_data.depth,
                    filename=sr_data.filename,
                    installer_jar=sr_data.installer_jar,
                    jar_type=sr_data.jar_type,
                    detection_confidence=sr_data.detection_confidence,
                    service_name=sr_data.service_name,
                    declared_port=sr_data.declared_port,
                    application_name=sr_data.application_name,
                    group_name=sr_data.group_name,
                    install_path=sr_data.install_path,
                    start_class=sr_data.start_class,
                    spring_boot_version=sr_data.spring_boot_version,
                    implementation_version=sr_data.implementation_version,
                    size_bytes=sr_data.size_bytes,
                    manifest_json=json.dumps(sr_data.manifest) if sr_data.manifest else None,
                    installer_metadata_json=json.dumps(sr_data.installer_metadata) if sr_data.installer_metadata else None,
                    package_structure_json=json.dumps(sr_data.package_structure) if sr_data.package_structure else None,
                    class_file_versions_json=json.dumps(sr_data.class_file_versions) if sr_data.class_file_versions else None,
                    analysis_duration_ms=sr_data.duration_ms,
                    purpose_narrative_json=json.dumps(sr_data.purpose_narrative) if sr_data.purpose_narrative else None,
                )
                db.add(sub)
                await db.flush()  # get sub.id

                # Endpoints
                from app.services.jar_analyser.table_linker import link_tables
                table_map = link_tables(sr_data.endpoints, sr_data.migration_scripts)
                for ep in sr_data.endpoints:
                    from app.services.jar_analyser.pagination_detector import detect_pagination
                    pag = detect_pagination(ep)
                    db.add(JarEndpoint(
                        sub_report_id=sub.id,
                        controller_class=ep["controller_class"],
                        controller_simple=ep["controller_simple"],
                        http_method=ep["http_method"],
                        path=ep["path"],
                        full_path=ep["full_path"],
                        base_path=ep.get("base_path"),
                        method_name=ep["method_name"],
                        parameters_json=json.dumps(ep.get("parameters")) if ep.get("parameters") else None,
                        request_body_json=json.dumps(ep["request_body"]) if ep.get("request_body") else None,
                        return_type_json=json.dumps(ep["return_type"]) if ep.get("return_type") else None,
                        security_json=json.dumps(ep["security"]) if ep.get("security") else None,
                        parsed_auth_json=json.dumps(ep["security"]["parsed_auth"]) if ep.get("security") and ep["security"].get("parsed_auth") else None,
                        confidence=ep.get("confidence", "HIGH"),
                        source_annotation=ep.get("source_annotation", ""),
                        signature_key=ep.get("signature_key", f"{ep['http_method']}:{ep['full_path']}"),
                        is_paginated=pag["is_paginated"],
                        page_param=pag["page_param"],
                        size_param=pag["size_param"],
                        sort_param=pag["sort_param"],
                        default_page_size=pag["default_page_size"],
                        is_deprecated=ep.get("deprecated", False),
                        linked_tables_json=json.dumps(table_map.get(ep.get("signature_key", ""), [])) if table_map else None,
                        is_proxied=is_service_proxied(sr_data.service_name, proxied_services) if proxied_services else None,
                        doc_summary=ep.get("doc_summary"),
                        doc_description=ep.get("doc_description"),
                        payload_shape_known=ep.get("payload_shape_known"),
                    ))

                # Dependencies
                for dep in sr_data.dependencies:
                    db.add(JarDependency(
                        sub_report_id=sub.id,
                        filename=dep["filename"],
                        group_id=dep.get("group_id"),
                        artifact_id=dep.get("artifact_id"),
                        version=dep.get("version"),
                        category=dep.get("category"),
                        size_bytes=dep.get("size_bytes"),
                        maven_coordinates=dep.get("maven_coordinates"),
                        source_path=dep.get("source_path"),
                        manifest_title=dep.get("manifest_title"),
                        manifest_vendor=dep.get("manifest_vendor"),
                        coordinates_source=dep.get("coordinates_source"),
                    ))

                # Config files
                for cf in sr_data.config_files:
                    db.add(JarConfigFile(
                        sub_report_id=sub.id,
                        filename=cf["filename"],
                        path_in_jar=cf["path_in_jar"],
                        file_type=cf.get("file_type", "properties"),
                        profile=cf.get("profile"),
                        content=cf.get("content"),
                        key_count=cf.get("key_count"),
                        encrypted_count=cf.get("encrypted_count"),
                        placeholder_count=cf.get("placeholder_count"),
                        ssl_key_count=cf.get("ssl_key_count"),
                        db_key_count=cf.get("db_key_count"),
                        mq_key_count=cf.get("mq_key_count"),
                        keys_json=json.dumps(cf.get("keys")) if cf.get("keys") else None,
                    ))

                # Migration scripts
                for ms in sr_data.migration_scripts:
                    db.add(JarMigrationScript(
                        sub_report_id=sub.id,
                        filename=ms["filename"],
                        version=ms.get("version"),
                        description=ms.get("description"),
                        script_type=ms.get("script_type", "versioned"),
                        size_bytes=ms.get("size_bytes"),
                        statement_count=ms.get("statement_count"),
                        ddl_operations_json=json.dumps(ms.get("ddl_operations")) if ms.get("ddl_operations") else None,
                        tables_json=json.dumps(ms.get("tables_affected")) if ms.get("tables_affected") else None,
                        content=ms.get("content"),
                    ))

                # Event files
                for ev in sr_data.event_files:
                    db.add(JarEventFile(
                        sub_report_id=sub.id,
                        filename=ev["filename"],
                        path_in_jar=ev["path_in_jar"],
                        content=ev.get("content"),
                        published_json=json.dumps(ev.get("published")) if ev.get("published") else None,
                        consumed_json=json.dumps(ev.get("consumed")) if ev.get("consumed") else None,
                    ))

                # DTO schemas (Stage 1+2)
                for schema in getattr(sr_data, "dto_schemas", []):
                    db.add(JarDtoSchema(
                        sub_report_id=sub.id,
                        class_name=schema["class_name"],
                        simple_name=schema["simple_name"],
                        is_enum=schema.get("is_enum", False),
                        is_lombok=schema.get("is_lombok", False),
                        source_note=schema.get("source_note"),
                        enum_values_json=json.dumps(schema["enum_values"]) if schema.get("enum_values") else None,
                        fields_json=json.dumps(schema["fields"]) if schema.get("fields") else None,
                        description=schema.get("description"),
                        polymorphic_base=schema.get("polymorphic_base"),
                        discriminator_value=schema.get("discriminator_value"),
                    ))

                # Config/design document examples (bundled or synthesized)
                for ex in getattr(sr_data, "config_examples", []):
                    db.add(JarConfigExample(
                        sub_report_id=sub.id,
                        root_class_name=ex["root_class_name"],
                        format=ex.get("format", "yaml"),
                        source=ex["source"],
                        content=ex["content"],
                    ))

                # Scheduled jobs (@Scheduled / @Schedules)
                for sj in getattr(sr_data, "scheduled_jobs", []):
                    db.add(JarScheduledJob(
                        sub_report_id=sub.id,
                        declaring_class=sj["declaring_class"],
                        declaring_class_simple=sj["declaring_class_simple"],
                        method_name=sj["method_name"],
                        cron=sj.get("cron"),
                        fixed_rate_ms=sj.get("fixed_rate_ms"),
                        fixed_delay_ms=sj.get("fixed_delay_ms"),
                        initial_delay_ms=sj.get("initial_delay_ms"),
                        zone=sj.get("zone"),
                        is_config_driven=sj.get("is_config_driven", False),
                        display=sj.get("display", ""),
                    ))

                # Workflows (Stage 3)
                for wf in getattr(sr_data, "workflows", []):
                    db.add(JarWorkflow(
                        sub_report_id=sub.id,
                        name=wf["name"],
                        description=wf.get("description"),
                        category=wf.get("category"),
                        source=wf.get("source", "auto_detected"),
                        steps_json=json.dumps(wf["steps"]),
                    ))

                # Error responses (Stage 6)
                for er in getattr(sr_data, "error_responses", []):
                    db.add(JarErrorResponse(
                        sub_report_id=sub.id,
                        http_status=er.get("http_status"),
                        exception_class=er.get("exception_class"),
                        response_schema_class=er.get("response_schema_class"),
                        scope=er.get("scope", "global"),
                        controller_class=er.get("controller_class"),
                        fields_json=json.dumps(er["fields"]) if er.get("fields") else None,
                    ))

                # String constants — see JarStringConstant's model docstring.
                # Bulk FTS insert (not a per-row helper like Docs/Bugs use)
                # since one sub-report can produce hundreds of rows at once;
                # needs a flush first to get each row's generated id.
                string_rows = [
                    JarStringConstant(
                        sub_report_id=sub.id,
                        class_name=sc["class_name"],
                        value=sc["value"],
                    )
                    for sc in getattr(sr_data, "string_constants", [])
                ]
                db.add_all(string_rows)
                if string_rows and settings.is_sqlite:
                    await db.flush()  # populate each row's generated id
                    for row in string_rows:
                        await db.execute(
                            text("INSERT INTO jar_strings_fts (id, value) VALUES (:id, :value)"),
                            {"id": row.id, "value": row.value},
                        )

                # Outbound integrations — see JarOutboundIntegration's model
                # docstring. No FTS table, just plain rows.
                for oi in getattr(sr_data, "outbound_integrations", []):
                    db.add(JarOutboundIntegration(
                        sub_report_id=sub.id,
                        kind=oi["kind"],
                        class_name=oi["class_name"],
                        target=oi["target"],
                        config_key=oi.get("config_key"),
                        raw_value=oi.get("raw_value"),
                        resolved_value=oi.get("resolved_value"),
                    ))
            persisted_count += 1
        except Exception as e:
            logger.exception(f"Failed to persist sub-report for service '{svc_label}'")
            persistence_errors.append(f"{svc_label}: persistence failed — {e}")

    report.warnings_json = json.dumps(result.warnings) if result.warnings else None
    report.errors_json = json.dumps(persistence_errors) if persistence_errors else None
    # "completed" even with some per-service errors — partial results are far
    # more useful than none. Only a total wipeout (every sub-report failed to
    # persist, on a bundle that actually had sub-reports) counts as "failed".
    report.status = "completed" if (persisted_count > 0 or not result.sub_reports) else "failed"

    upload.status = report.status
    await db.commit()
