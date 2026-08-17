"""Structured View category rules — Improvements Plan Stage 13. Replaces the
previously-hardcoded ~25-pattern regex map in structuredParse.ts with a real,
admin-editable table. Seeded here with the exact same patterns/labels/order
the hardcoded list used, so out-of-the-box behaviour is unchanged until an
admin edits it. Global (no tenant_id) — see CategoryRule's own docstring in
app/models/docs.py for why.

Revision ID: 080
Revises: 079
"""
from alembic import op
import sqlalchemy as sa

revision = '080'
down_revision = '079'
branch_labels = None
depends_on = None

# Mirrors structuredParse.ts's old hardcoded `map` array exactly, in the
# same match-order (first match wins).
_SEED_RULES = [
    (r"database|rds|sql|dynamo|data", "Data"),
    (r"cache|redis|elastic", "Cache"),
    (r"queue|sqs|rabbit|kafka|message", "Queue"),
    (r"api|gateway|endpoint|route", "API"),
    (r"auth|identity|iam|cognito|keystone", "Auth"),
    (r"monitor|alarm|cloud\s?watch|log", "Monitor"),
    (r"storage|s3|efs|bucket|file", "Storage"),
    (r"network|vpc|subnet|dns|route", "Network"),
    (r"deploy|ci|cd|pipeline|build", "Deploy"),
    (r"security|encrypt|kms|secret|tls|ssl", "Security"),
    (r"server|ec2|instance|compute|lambda|container", "Compute"),
    (r"frontend|ui|web|nginx|react", "Frontend"),
    (r"backend|service|micro", "Backend"),
    (r"test|qa|check", "Test"),
    (r"config|setting|param", "Config"),
    (r"keyboard|shortcut|key", "Keys"),
    (r"feature|overview|intro|start|getting", "Overview"),
    (r"table|list|item", "List"),
    (r"code|block|syntax|example", "Code"),
    (r"callout|note|warning|tip|alert", "Info"),
    (r"quote|blockquote|cite", "Quote"),
    (r"task|todo|checklist", "Tasks"),
    (r"arch|design|pattern|struct", "Arch"),
    (r"render|display|view|format", "Render"),
    (r"search|find|filter|query", "Search"),
    (r"add|new|creat|extend|plugin", "Extend"),
]


def upgrade():
    op.create_table(
        'category_rules',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('pattern', sa.String(256), nullable=False),
        sa.Column('label', sa.String(32), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_category_rules_sort_order', 'category_rules', ['sort_order'])

    import uuid
    conn = op.get_bind()
    table = sa.table(
        'category_rules',
        sa.column('id', sa.String), sa.column('pattern', sa.String), sa.column('label', sa.String),
        sa.column('sort_order', sa.Integer), sa.column('created_by', sa.String),
    )
    conn.execute(table.insert(), [
        {'id': str(uuid.uuid4()), 'pattern': pattern, 'label': label, 'sort_order': i, 'created_by': 'system'}
        for i, (pattern, label) in enumerate(_SEED_RULES)
    ])


def downgrade():
    op.drop_index('ix_category_rules_sort_order', table_name='category_rules')
    op.drop_table('category_rules')
