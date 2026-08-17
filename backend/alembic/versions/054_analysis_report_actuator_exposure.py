"""add analysis_reports.actuator_exposure_json — flags services where Spring
Boot Actuator's management.endpoints.web.exposure.include config broadens
exposure to sensitive endpoints (env, heapdump, threaddump, beans,
configprops, mappings, loggers, httptrace/httpexchanges, auditevents, or an
explicitly-enabled shutdown), cross-referenced with whether the management
port matches the main app port and whether that port is reachable via the
Nginx proxy. Purely static evidence — custom Spring Security rules that
separately restrict /actuator/** are not parsed (existing, documented
limitation of this tool).

Revision ID: 054
Revises: 053
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '054'
down_revision = '053'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    op.add_column('analysis_reports', sa.Column('actuator_exposure_json', _LONGTEXT_ON_MYSQL, nullable=True))


def downgrade():
    op.drop_column('analysis_reports', 'actuator_exposure_json')
