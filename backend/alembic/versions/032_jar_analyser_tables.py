"""032 jar analyser tables

Revision ID: 032
Revises: 031
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jar_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, index=True),
        sa.Column("md5", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("stored_path", sa.String(1024), nullable=True),
        sa.Column("uploaded_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("uploaded_by", sa.String(256), nullable=True),
        sa.Column("label", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.String(36), sa.ForeignKey("jar_uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jar_type", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("detection_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("implementation_title", sa.String(512), nullable=True),
        sa.Column("implementation_version", sa.String(64), nullable=True),
        sa.Column("implementation_vendor", sa.String(256), nullable=True),
        sa.Column("spring_boot_version", sa.String(32), nullable=True),
        sa.Column("java_version_required", sa.String(8), nullable=True),
        sa.Column("build_jdk", sa.String(32), nullable=True),
        sa.Column("manifest_json", sa.Text, nullable=True),
        sa.Column("summary_json", sa.Text, nullable=True),
        sa.Column("analysis_started_at", sa.DateTime, nullable=True),
        sa.Column("analysis_completed_at", sa.DateTime, nullable=True),
        sa.Column("analysis_duration_ms", sa.Integer, nullable=True),
        sa.Column("analyser_version", sa.String(16), nullable=False, server_default="1.0.0"),
        sa.Column("warnings_json", sa.Text, nullable=True),
        sa.Column("errors_json", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.create_index("ix_analysis_reports_implementation_title", "analysis_reports", ["implementation_title"])
    op.create_index("ix_analysis_reports_implementation_version", "analysis_reports", ["implementation_version"])

    op.create_table(
        "sub_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parent_report_id", sa.String(36), sa.ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("depth", sa.Integer, nullable=False, server_default="1"),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("installer_jar", sa.String(512), nullable=True),
        sa.Column("jar_type", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("detection_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("service_name", sa.String(256), nullable=True),
        sa.Column("declared_port", sa.Integer, nullable=True),
        sa.Column("application_name", sa.String(256), nullable=True),
        sa.Column("group_name", sa.String(64), nullable=True),
        sa.Column("install_path", sa.String(512), nullable=True),
        sa.Column("start_class", sa.String(512), nullable=True),
        sa.Column("spring_boot_version", sa.String(32), nullable=True),
        sa.Column("implementation_version", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("manifest_json", sa.Text, nullable=True),
        sa.Column("installer_metadata_json", sa.Text, nullable=True),
        sa.Column("package_structure_json", sa.Text, nullable=True),
        sa.Column("class_file_versions_json", sa.Text, nullable=True),
        sa.Column("analysis_duration_ms", sa.Integer, nullable=True),
    )
    op.create_index("ix_sub_reports_service_name", "sub_reports", ["service_name"])

    op.create_table(
        "jar_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sub_report_id", sa.String(36), sa.ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("controller_class", sa.String(512), nullable=False),
        sa.Column("controller_simple", sa.String(256), nullable=False),
        sa.Column("http_method", sa.String(16), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("full_path", sa.String(1024), nullable=False),
        sa.Column("base_path", sa.String(512), nullable=True),
        sa.Column("method_name", sa.String(256), nullable=False),
        sa.Column("parameters_json", sa.Text, nullable=True),
        sa.Column("request_body_json", sa.Text, nullable=True),
        sa.Column("return_type_json", sa.Text, nullable=True),
        sa.Column("security_json", sa.Text, nullable=True),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="HIGH"),
        sa.Column("source_annotation", sa.String(64), nullable=False, server_default=""),
        sa.Column("signature_key", sa.String(1024), nullable=False),
    )
    # mysql_length: signature_key is String(1024); at utf8mb4 (4 bytes/char) a full-length
    # index exceeds MySQL's 3072-byte InnoDB key limit. Ignored by SQLite/PostgreSQL.
    op.create_index("ix_jar_endpoints_signature_key", "jar_endpoints", ["signature_key"], mysql_length=255)

    op.create_table(
        "jar_dependencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sub_report_id", sa.String(36), sa.ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("group_id", sa.String(256), nullable=True),
        sa.Column("artifact_id", sa.String(256), nullable=True),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("maven_coordinates", sa.String(512), nullable=True),
        sa.Column("source_path", sa.String(512), nullable=True),
        sa.Column("manifest_title", sa.String(256), nullable=True),
        sa.Column("manifest_vendor", sa.String(256), nullable=True),
        sa.Column("coordinates_source", sa.String(32), nullable=True),
    )
    op.create_index("ix_jar_dependencies_group_id", "jar_dependencies", ["group_id"])
    op.create_index("ix_jar_dependencies_maven_coordinates", "jar_dependencies", ["maven_coordinates"])

    op.create_table(
        "jar_config_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sub_report_id", sa.String(36), sa.ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("path_in_jar", sa.String(512), nullable=False),
        sa.Column("file_type", sa.String(32), nullable=False, server_default="properties"),
        sa.Column("profile", sa.String(64), nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("key_count", sa.Integer, nullable=True),
        sa.Column("encrypted_count", sa.Integer, nullable=True),
        sa.Column("placeholder_count", sa.Integer, nullable=True),
        sa.Column("ssl_key_count", sa.Integer, nullable=True),
        sa.Column("db_key_count", sa.Integer, nullable=True),
        sa.Column("mq_key_count", sa.Integer, nullable=True),
        sa.Column("keys_json", sa.Text, nullable=True),
    )

    op.create_table(
        "jar_migration_scripts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sub_report_id", sa.String(36), sa.ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("description", sa.String(256), nullable=True),
        sa.Column("script_type", sa.String(16), nullable=False, server_default="versioned"),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("statement_count", sa.Integer, nullable=True),
        sa.Column("ddl_operations_json", sa.Text, nullable=True),
        sa.Column("tables_json", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
    )

    op.create_table(
        "jar_event_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sub_report_id", sa.String(36), sa.ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("path_in_jar", sa.String(512), nullable=False),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("published_json", sa.Text, nullable=True),
        sa.Column("consumed_json", sa.Text, nullable=True),
    )

    op.create_table(
        "jar_diff_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_a_id", sa.String(36), sa.ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_b_id", sa.String(36), sa.ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label_a", sa.String(64), nullable=True),
        sa.Column("label_b", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("summary_json", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("diff_json", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("warnings_json", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("jar_diff_reports")
    op.drop_table("jar_event_files")
    op.drop_table("jar_migration_scripts")
    op.drop_table("jar_config_files")
    op.drop_table("jar_dependencies")
    op.drop_table("jar_endpoints")
    op.drop_table("sub_reports")
    op.drop_table("analysis_reports")
    op.drop_table("jar_uploads")
