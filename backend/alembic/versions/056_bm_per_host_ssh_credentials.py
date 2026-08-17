"""Build Manager Hardening Plan, Stage 5 — per-host SSH credentials.

Every host previously shared one SSH key with no alternative. Adds an
opt-in per-host credential: ssh_auth_method ("shared_key" | "private_key" |
"password", defaulting to "shared_key" so every existing host keeps working
exactly as before) and ssh_credential_encrypted (Fernet-encrypted at rest,
same key as bm_secrets — see secrets_service.py's encrypt_value/decrypt_value,
holding whichever of the two credential types applies).

Host-key verification (StrictHostKeyChecking) remains a separate, still-open
item — not addressed by this migration.

Revision ID: 056
Revises: 055
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '056'
down_revision = '055'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_hosts', sa.Column('ssh_auth_method', sa.String(16), nullable=False, server_default='shared_key'))
    op.add_column('bm_hosts', sa.Column('ssh_credential_encrypted', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('bm_hosts', 'ssh_credential_encrypted')
    op.drop_column('bm_hosts', 'ssh_auth_method')
