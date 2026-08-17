"""Add OCSP signing delegation columns to certificate_authorities.

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("certificate_authorities") as batch_op:
        batch_op.add_column(sa.Column("ocsp_cert_pem", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ocsp_key_blob", sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column("ocsp_cert_expires", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("certificate_authorities") as batch_op:
        batch_op.drop_column("ocsp_cert_expires")
        batch_op.drop_column("ocsp_key_blob")
        batch_op.drop_column("ocsp_cert_pem")
