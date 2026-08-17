"""012 — Serial number management.

Adds serial_counters table for database-backed serial allocation per CA.
Also adds serial_format column to certificate_authorities for per-CA config.
"""

from alembic import op
import sqlalchemy as sa


revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "serial_counters",
        sa.Column("ca_id", sa.String(36), primary_key=True),
        sa.Column("next_value", sa.Integer, nullable=False, default=1),
        sa.Column("format", sa.String(32), nullable=False, default="random"),
        sa.Column("prefix", sa.String(16), nullable=False, default=""),
    )

    with op.batch_alter_table("certificate_authorities") as batch_op:
        batch_op.add_column(
            sa.Column("serial_format", sa.String(32), nullable=True, default=None)
        )


def downgrade() -> None:
    op.drop_table("serial_counters")
    with op.batch_alter_table("certificate_authorities") as batch_op:
        batch_op.drop_column("serial_format")
