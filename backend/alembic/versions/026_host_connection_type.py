"""Add connection_type and container_name to bm_hosts."""

from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bm_hosts", sa.Column("connection_type", sa.String(16), nullable=False, server_default="docker"))
    op.add_column("bm_hosts", sa.Column("container_name", sa.String(255), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("bm_hosts", "container_name")
    op.drop_column("bm_hosts", "connection_type")
