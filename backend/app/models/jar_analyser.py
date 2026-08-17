"""JAR Analyser database models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TZDateTime

# Plain TEXT caps at 64KB in MySQL; full-schema diffs between large JAR
# analysis reports routinely exceed that (observed 300KB+ in practice).
_LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")


def _uuid() -> str:
    return str(uuid.uuid4())


# Multi-tenancy — same default-tenant convention as certificate.py/compliance.py/etc.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class JarUpload(Base):
    __tablename__ = "jar_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stored_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # pending | analysing | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, default=DEFAULT_TENANT_ID
    )

    reports: Mapped[list["AnalysisReport"]] = relationship("AnalysisReport", back_populates="upload", cascade="all, delete-orphan")


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    upload_id: Mapped[str] = mapped_column(String(36), ForeignKey("jar_uploads.id", ondelete="CASCADE"), nullable=False)
    jar_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    implementation_title: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    implementation_version: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    implementation_vendor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    spring_boot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    java_version_required: Mapped[str | None] = mapped_column(String(8), nullable=True)
    build_jdk: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manifest_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    analysis_started_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    analysis_completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    analysis_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analyser_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    warnings_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    errors_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    consistency_findings_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    # Infra-requirements plan — {iam, database, messaging} provisioning requirements.
    # See app/services/jar_analyser/infra_requirements.py.
    infra_requirements_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    # Actuator/management endpoint exposure findings. See
    # app/services/jar_analyser/actuator_exposure.py.
    actuator_exposure_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    # Improvements Plan Stage 12 — automated cross-report bug pattern scan.
    # JSON list of open Bug ids (best-first), computed once right after
    # analysis completes. See app/services/jar_analyser/bug_pattern_scan.py.
    # Null means "not yet scanned" (e.g. a report analysed before this
    # column existed); an empty list "[]" means "scanned, nothing related
    # found" — the two are deliberately distinguishable.
    related_bug_ids_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    # pending | analysing | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, default=DEFAULT_TENANT_ID
    )

    upload: Mapped["JarUpload"] = relationship("JarUpload", back_populates="reports")
    sub_reports: Mapped[list["SubReport"]] = relationship("SubReport", back_populates="parent_report", cascade="all, delete-orphan")
    # report_id-keyed, not sub_report_id-keyed — this is what makes a
    # "decompile all jars" run (sub_report_id null) still get cleaned up
    # when the report is deleted; SubReport.decompile_runs below only ever
    # reaches single-jar-scoped runs, since a report-scoped run has no
    # sub_report_id to be reached through.
    decompile_runs: Mapped[list["JarDecompileRun"]] = relationship("JarDecompileRun", back_populates="report", cascade="all, delete-orphan")


class SubReport(Base):
    __tablename__ = "sub_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parent_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    installer_jar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    jar_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    service_name: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    declared_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    install_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_class: Mapped[str | None] = mapped_column(String(512), nullable=True)
    spring_boot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    implementation_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    manifest_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    installer_metadata_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    package_structure_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    class_file_versions_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    analysis_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stage 6 — "Perceived Purpose" narrative. See purpose_narrative.py.
    purpose_narrative_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)

    parent_report: Mapped["AnalysisReport"] = relationship("AnalysisReport", back_populates="sub_reports")
    endpoints: Mapped[list["JarEndpoint"]] = relationship("JarEndpoint", back_populates="sub_report", cascade="all, delete-orphan")
    dependencies: Mapped[list["JarDependency"]] = relationship("JarDependency", back_populates="sub_report", cascade="all, delete-orphan")
    config_files: Mapped[list["JarConfigFile"]] = relationship("JarConfigFile", back_populates="sub_report", cascade="all, delete-orphan")
    migration_scripts: Mapped[list["JarMigrationScript"]] = relationship("JarMigrationScript", back_populates="sub_report", cascade="all, delete-orphan")
    event_files: Mapped[list["JarEventFile"]] = relationship("JarEventFile", back_populates="sub_report", cascade="all, delete-orphan")
    dto_schemas: Mapped[list["JarDtoSchema"]] = relationship("JarDtoSchema", back_populates="sub_report", cascade="all, delete-orphan")
    workflows: Mapped[list["JarWorkflow"]] = relationship("JarWorkflow", back_populates="sub_report", cascade="all, delete-orphan")
    error_responses: Mapped[list["JarErrorResponse"]] = relationship("JarErrorResponse", back_populates="sub_report", cascade="all, delete-orphan")
    scheduled_jobs: Mapped[list["JarScheduledJob"]] = relationship("JarScheduledJob", back_populates="sub_report", cascade="all, delete-orphan")
    decompiled_classes: Mapped[list["JarDecompiledClass"]] = relationship("JarDecompiledClass", back_populates="sub_report", cascade="all, delete-orphan")
    config_examples: Mapped[list["JarConfigExample"]] = relationship("JarConfigExample", back_populates="sub_report", cascade="all, delete-orphan")
    string_constants: Mapped[list["JarStringConstant"]] = relationship("JarStringConstant", back_populates="sub_report", cascade="all, delete-orphan")
    outbound_integrations: Mapped[list["JarOutboundIntegration"]] = relationship("JarOutboundIntegration", back_populates="sub_report", cascade="all, delete-orphan")
    outbound_call_sites: Mapped[list["JarOutboundCallSite"]] = relationship("JarOutboundCallSite", back_populates="sub_report", cascade="all, delete-orphan")


class JarEndpoint(Base):
    __tablename__ = "jar_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    controller_class: Mapped[str] = mapped_column(String(512), nullable=False)
    controller_simple: Mapped[str] = mapped_column(String(256), nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    full_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    base_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    method_name: Mapped[str] = mapped_column(String(256), nullable=False)
    parameters_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    request_body_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    return_type_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    security_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    parsed_auth_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="HIGH")
    source_annotation: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    signature_key: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    is_paginated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    page_param: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_param: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_param: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_page_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # @Operation(summary=..., description=...) — developer-authored, not inferred.
    doc_summary: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    doc_description: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    linked_tables_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    is_proxied: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Stage 5 — false when the return/request type is a generic container whose
    # element type is erased at the bytecode level, Object, or an unresolvable
    # external type. See endpoint_confidence.py.
    payload_shape_known: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="endpoints")


class JarDependency(Base):
    __tablename__ = "jar_dependencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    group_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    artifact_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    maven_coordinates: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    manifest_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    manifest_vendor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # pom.properties | manifest | filename_parse
    coordinates_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="dependencies")


class JarConfigFile(Base):
    __tablename__ = "jar_config_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    path_in_jar: Mapped[str] = mapped_column(String(512), nullable=False)
    # properties | yaml | xml
    file_type: Mapped[str] = mapped_column(String(32), nullable=False, default="properties")
    profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    key_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    encrypted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    placeholder_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ssl_key_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    db_key_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mq_key_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keys_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="config_files")


class JarMigrationScript(Base):
    __tablename__ = "jar_migration_scripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # versioned | repeatable
    script_type: Mapped[str] = mapped_column(String(16), nullable=False, default="versioned")
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statement_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ddl_operations_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    tables_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    content: Mapped[str | None] = mapped_column(_LongText, nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="migration_scripts")


class JarEventFile(Base):
    __tablename__ = "jar_event_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    path_in_jar: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    published_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    consumed_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="event_files")


class JarDtoSchema(Base):
    __tablename__ = "jar_dto_schemas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    class_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    simple_name: Mapped[str] = mapped_column(String(256), nullable=False)
    is_enum: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_lombok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enum_values_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)   # JSON array
    fields_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)         # JSON array
    # @Schema(description=...) on the class — developer-authored, not inferred.
    # Field-level descriptions live inside fields_json (per-field "description" key).
    description: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    # Populated when this class is a concrete @JsonSubTypes.Type of some other
    # scanned class (polymorphic_base = that base class's FQCN, discriminator_value
    # = the "name" string that selects this subtype, e.g. Flow -> CreateFlow/"CREATE").
    # Both null for a class that isn't a polymorphic subtype of anything scanned.
    polymorphic_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    discriminator_value: Mapped[str | None] = mapped_column(String(128), nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="dto_schemas")


class JarConfigExample(Base):
    """An example instance document (YAML) for a discovered Jackson-modeled
    "root" config/design class — e.g. a service's CompositeDesign. Either a
    real document found bundled in the jar itself (source="bundled", the
    strongest possible evidence — see config_examples.py's find_bundled_examples)
    or one synthesized from the class's own structure (source="synthesized" —
    synthesize_example): required fields populated, real enum/discriminator
    values, annotation-sourced defaults where present. Never AI-generated —
    see the project's no-embedded-AI constraint. One row per (sub_report,
    root_class) — a fresh analysis replaces prior rows for that sub-report."""
    __tablename__ = "jar_config_examples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    root_class_name: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="yaml")
    # "bundled" (found as a real resource in the jar) | "synthesized"
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(_LongText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="config_examples")


class JarWorkflow(Base):
    __tablename__ = "jar_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # auto_detected | manual
    steps_json: Mapped[str] = mapped_column(_LongText, nullable=False)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="workflows")


class JarScheduledJob(Base):
    __tablename__ = "jar_scheduled_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    declaring_class: Mapped[str] = mapped_column(String(512), nullable=False)
    declaring_class_simple: Mapped[str] = mapped_column(String(256), nullable=False)
    method_name: Mapped[str] = mapped_column(String(256), nullable=False)
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fixed_rate_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fixed_delay_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    initial_delay_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_config_driven: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="scheduled_jobs")


class JarErrorResponse(Base):
    __tablename__ = "jar_error_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exception_class: Mapped[str | None] = mapped_column(String(512), nullable=True)
    response_schema_class: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="global")
    controller_class: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fields_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="error_responses")


class JarKbEntry(Base):
    __tablename__ = "jar_kb_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # critical | high | medium | low
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    plain_english: Mapped[str] = mapped_column(Text, nullable=False)
    causes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    fix_steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    see_also_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")  # 'builtin' | 'user'
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)


class JarDiffReport(Base):
    __tablename__ = "jar_diff_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    report_a_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False)
    report_b_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False)
    label_a: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label_b: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    summary_json: Mapped[str] = mapped_column(_LongText, nullable=False, default="{}")
    diff_json: Mapped[str] = mapped_column(_LongText, nullable=False, default="{}")
    warnings_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)


class JarDiagnosticRun(Base):
    __tablename__ = "jar_diagnostic_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    report_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    bundle_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bundle_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(256), nullable=True)
    os_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    summary_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    findings_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    cert_results_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    port_results_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    rmq_summary_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    config_issues_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    log_findings_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    os_info: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    error: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    run_label: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    report_data: Mapped[str | None] = mapped_column(_LongText, nullable=True)


class JarDecompileRun(Base):
    """On-demand decompile job — scoped to one sub-report (single jar) if
    sub_report_id is set, or every sub-report under the report if null
    ("decompile all jars")."""
    __tablename__ = "jar_decompile_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False)
    sub_report_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=True)
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    jars_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jars_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jars_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    # Per-sub-report outcome summary when scope is "all jars" — JSON array of
    # {sub_report_id, filename, status, classes_decompiled, error}.
    results_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    error: Mapped[str | None] = mapped_column(_LongText, nullable=True)

    # report_id-keyed cascade (AnalysisReport.decompile_runs above) is what
    # actually cleans these up on delete — reaches every run regardless of
    # scope, since report_id is always set but sub_report_id is null for a
    # "decompile all jars" run and so can't be reached through SubReport.
    report: Mapped["AnalysisReport"] = relationship("AnalysisReport", back_populates="decompile_runs")


class JarDecompiledClass(Base):
    """One decompiled .java source file, produced by CFR or Vineflower from a
    single class in a sub-report's jar — one row per (sub_report, class,
    engine), since both engines run on every decompile and either may
    produce output the other doesn't. Populated by a JarDecompileRun."""
    __tablename__ = "jar_decompiled_classes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jar_decompile_runs.id", ondelete="SET NULL"), nullable=True)
    class_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)  # fully-qualified, / separated
    package_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    simple_name: Mapped[str] = mapped_column(String(256), nullable=False)
    # "cfr" | "vineflower" — default matches pre-dual-engine rows, which were
    # always CFR.
    engine: Mapped[str] = mapped_column(String(16), nullable=False, default="cfr")
    source: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    decompiled_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="decompiled_classes")


class JarStringConstant(Base):
    """One string literal pulled from a class's own bytecode constant pool
    (a JVMS CONSTANT_String entry, resolved to its backing CONSTANT_Utf8) —
    populated automatically for every class AnnotationScanner reaches during
    analysis, not opt-in like decompilation. This is the precise mechanism:
    a class's constant pool only gets a String-tag entry for a Utf8 the
    compiler actually used as a literal somewhere (ldc in bytecode, an
    annotation's string value, or a static final field initialiser) — so no
    heuristic filtering of descriptors/type-name noise is needed, unlike a
    naive dump of every Utf8 entry (which is mostly method/field descriptors
    and internal type names).

    Exists to answer "which service logs this message" without needing to
    have already decompiled every class by hand — see string_search.py.
    class_name is dot-separated (java_class_name), matching the majority
    convention across this file's other per-class tables (JarEndpoint,
    JarScheduledJob, JarDtoSchema) rather than JarDecompiledClass's
    slash-separated one."""
    __tablename__ = "jar_string_constants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    class_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    value: Mapped[str] = mapped_column(_LongText, nullable=False)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="string_constants")


class JarOutboundIntegration(Base):
    """One statically-discovered signal that a class calls out to a system
    outside the analysed bundle — either a Feign client declaration or a
    field carrying @Value("${some.url.like.key}"). See
    outbound_integrations.py's module docstring for the full rationale and
    the (deliberate) limits of what this can and can't prove without
    decoding method bodies.

    kind: "feign_client" | "config_value"
    target: the Feign client's declared name/value, or the field's own name
    config_key: the placeholder's property name, e.g. "vra.api.url" — null
      for a Feign client whose url/name were literal, not placeholder-driven
    raw_value: the literal annotation value / placeholder expression as
      written in the bytecode, e.g. "${vra.api.url:http://default}"
    resolved_value: raw_value resolved against this same sub-report's own
      config files (or the placeholder's own inline default) when possible
      — null if neither this bundle's config nor the placeholder itself
      pins down an actual value (e.g. supplied only via external env/K8s
      ConfigMap at deploy time, outside anything this tool can see)."""
    __tablename__ = "jar_outbound_integrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    class_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(256), nullable=False)
    config_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    raw_value: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resolved_value: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="outbound_integrations")


class JarOutboundCallSite(Base):
    """One statically-discovered outbound HTTP call site inside an already-
    decompiled class — the response type it reads, and any status-code
    branches / caught / thrown exceptions found in the same enclosing
    method. See outbound_call_analysis.py's module docstring for the full
    rationale, the three call shapes matched (JAX-RS Client, RestTemplate,
    WebClient), and the caveats on what a text scan over decompiled source
    can and can't prove.

    Populated only when a class is decompiled (Section 36) — never
    automatically like JarStringConstant/JarOutboundIntegration, since it
    needs real source text, not just structural bytecode facts.

    class_name is slash-separated ("fully-qualified, / separated"), matching
    JarDecompiledClass.class_name exactly — these rows are derived directly
    from that same decompiled source, in the same loop, so reusing its
    convention avoids yet another dot/slash inconsistency across this
    file's tables (see the class-facts endpoint's own docstring in
    jar_analyser.py for the pre-existing inconsistency this deliberately
    doesn't add to)."""
    __tablename__ = "jar_outbound_call_sites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sub_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jar_decompile_runs.id", ondelete="SET NULL"), nullable=True)
    engine: Mapped[str] = mapped_column(String(16), nullable=False)
    class_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    method_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    call_type: Mapped[str] = mapped_column(String(16), nullable=False)  # jaxrs_client | resttemplate | webclient
    call_snippet: Mapped[str] = mapped_column(_LongText, nullable=False)
    response_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    caught_exceptions_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    thrown_exceptions_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    status_checks_json: Mapped[str | None] = mapped_column(_LongText, nullable=True)

    sub_report: Mapped["SubReport"] = relationship("SubReport", back_populates="outbound_call_sites")
