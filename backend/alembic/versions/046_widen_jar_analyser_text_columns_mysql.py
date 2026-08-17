"""widen remaining JAR Analyser large JSON/content blob columns for MySQL —
same class of issue as 045 (plain TEXT caps at 64KB in MySQL). This feature
area routinely produces large payloads (decompiled endpoint lists, full
config file contents, DTO schemas, migration script bodies), and a real
migration dry-run hit this limit on jar_config_files.content with genuine
data. SQLite/PostgreSQL TEXT has no such practical limit and are unaffected.

Deliberately excludes jar_kb_entries' text columns (pattern, plain_english,
causes_json, fix_steps_json, see_also_json) — those hold short, manually-authored
KB content, not decompiled-JAR blobs, and are in regular use with regex search.

Revision ID: 046
Revises: 045
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '046'
down_revision = '045'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")

# (table, [(column, nullable), ...])
_TABLES = [
    ("analysis_reports", [("manifest_json", True), ("summary_json", True), ("warnings_json", True), ("errors_json", True)]),
    ("sub_reports", [("manifest_json", True), ("installer_metadata_json", True), ("package_structure_json", True), ("class_file_versions_json", True)]),
    # parsed_auth_json intentionally excluded here — migration 047 creates it
    # directly with the correct MySQL-safe type, since it didn't exist before that.
    ("jar_endpoints", [("parameters_json", True), ("request_body_json", True), ("return_type_json", True), ("security_json", True), ("linked_tables_json", True)]),
    ("jar_config_files", [("content", True), ("keys_json", True)]),
    ("jar_migration_scripts", [("ddl_operations_json", True), ("tables_json", True), ("content", True)]),
    ("jar_event_files", [("content", True), ("published_json", True), ("consumed_json", True)]),
    ("jar_dto_schemas", [("enum_values_json", True), ("fields_json", True)]),
    ("jar_workflows", [("description", True), ("steps_json", False)]),
    ("jar_error_responses", [("fields_json", True)]),
    ("jar_diagnostic_runs", [
        ("summary_json", True), ("findings_json", True), ("cert_results_json", True),
        ("port_results_json", True), ("rmq_summary_json", True), ("config_issues_json", True),
        ("log_findings_json", True), ("os_info", True), ("error", True),
        ("run_label", True), ("report_data", True),
    ]),
]


def upgrade():
    for table_name, columns in _TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            for col_name, nullable in columns:
                batch_op.alter_column(col_name, existing_type=sa.Text(), existing_nullable=nullable, type_=_LONGTEXT_ON_MYSQL)


def downgrade():
    for table_name, columns in _TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            for col_name, nullable in columns:
                batch_op.alter_column(col_name, existing_type=_LONGTEXT_ON_MYSQL, existing_nullable=nullable, type_=sa.Text())
