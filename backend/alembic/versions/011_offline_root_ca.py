"""011 — Offline Root CA support.

Makes key_blob nullable on certificate_authorities table to support
imported CAs where the private key is kept offline/air-gapped.
"""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite doesn't support ALTER COLUMN, use batch mode
    with op.batch_alter_table("certificate_authorities") as batch_op:
        batch_op.alter_column("key_blob", existing_type=sa.LargeBinary, nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("certificate_authorities") as batch_op:
        batch_op.alter_column("key_blob", existing_type=sa.LargeBinary, nullable=False)
