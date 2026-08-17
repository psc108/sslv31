"""About page — Improvements: open-source attribution page.

New `about_page` table, single global content row (same "one fixed row"
shape as `bm_settings`/`category_rules`' singleton pattern), holding the
markdown shown on the sidebar's "About" page. Seeded here (unlike
`bm_settings`, which is lazily created empty on first use) because a blank
About page on a fresh install is a worse first impression than a
slightly-stale one — the seed content is a real inventory of this
project's actual open-source dependencies as of this migration, not a
placeholder.

Revision ID: 089
Revises: 088
"""
from alembic import op
import sqlalchemy as sa

revision = '089'
down_revision = '088'
branch_labels = None
depends_on = None

_SEED_CONTENT = """\
LabTool is a self-hosted suite for SSL certificate management, \
infrastructure build automation, JAR bytecode analysis, and internal \
documentation/bug tracking. It is built entirely on open-source software; \
this page credits everything it is built on, with the exact versions \
currently deployed (useful for license evaluation before production use).

## Runtime & base images

- **Python 3.12.13** (`python:3.12-slim`, Debian 13 "trixie") - the backend runtime
- **Node.js 20.20.2** (`node:20-alpine`) - used only to build the frontend \
bundle at image build time; not present in the running container
- **nginx 1.26.3** - serves the built frontend and reverse-proxies API requests
- **Eclipse Temurin JRE 17.0.13+11** - runs the bundled Java decompilers \
and `keytool`

## Backend (Python)

Exact versions currently installed (see `backend/requirements.txt` for \
the version constraints; these are the resolved versions actually \
running):

- **FastAPI 0.141.1** - the API framework
- **Uvicorn 0.52.1** / **Gunicorn 26.0.0** - ASGI server
- **SQLAlchemy 2.0.52** + **Alembic 1.19.1** - ORM and schema migrations
- **aiosqlite 0.22.1** / **asyncpg 0.31.0** / **aiomysql 0.3.2** (with \
**PyMySQL 1.2.0**) - async database drivers (SQLite/PostgreSQL/MySQL)
- **cryptography 50.0.0** / **pyasn1 0.6.4** - certificate and key \
generation/parsing
- **Jinja2 3.1.6** - config and playbook templating
- **PyYAML 6.0.3** - YAML parsing (Ansible playbooks, templates)
- **Markdown 3.10.3** - server-side markdown rendering (PDF export)
- **WeasyPrint 69.0** - PDF generation
- **slowapi 0.1.10** - API rate limiting
- **PyJWT 2.13.0** - JWT authentication tokens
- **argon2-cffi 25.1.0** - password hashing
- **ldap3 2.9.1** - LDAP authentication
- **httpx 0.28.1** - outbound HTTP client
- **boto3 1.43.70** (with **botocore 1.43.70**) - AWS SDK (S3/KMS \
integrations)
- **Pydantic 2.13.4** / **pydantic-settings 2.15.0** - request validation \
and config

## Frontend (JavaScript/TypeScript)

Exact resolved versions from `frontend/package-lock.json`:

- **React 18.3.1** / **React DOM 18.3.1** - UI framework
- **react-router-dom 7.18.1** - client-side routing
- **@tanstack/react-query 5.101.2** - server-state and data fetching
- **axios 1.18.1** - HTTP client
- **CodeMirror** (`@codemirror/view` 6.43.6, `@codemirror/state` 6.7.1, \
`@codemirror/language` 6.12.4, `@codemirror/commands` 6.10.4, \
`@codemirror/autocomplete` 6.20.3, `@codemirror/search` 6.7.1, plus \
per-language packages, `@lezer/highlight` 1.2.3) - the code and markdown \
editor used throughout Docs
- **react-markdown 10.1.0**, **remark-gfm 4.0.1**, **rehype-highlight \
7.0.2**, **rehype-slug 6.0.0** - markdown rendering
- **mermaid 11.16.1** - diagram rendering in Docs
- **d3-force 3.0.0** - the Doc Map's force-directed graph layout
- **highlight.js 11.11.1** - syntax highlighting
- **lucide-react 0.468.0** - icon set
- **sonner 1.7.4** - toast notifications
- **class-variance-authority 0.7.1**, **clsx 2.1.1**, **tailwind-merge \
2.6.1** - styling utilities
- **Vite**, **TypeScript**, **ESLint**, **Tailwind CSS** - build tooling \
(not shipped - used only to produce the static bundle)

## Bundled tools

- **CFR 0.152** (github.com/leibnitz27/cfr) - one of two Java decompilers \
used by JAR Analyser
- **Vineflower 1.12.0** (github.com/Vineflower/vineflower) - the other \
Java decompiler used by JAR Analyser
- **ansible-core 2.21.3** + the **ansible.posix 2.2.2** collection - runs \
every Build Manager playbook
- **OpenTofu 1.8.3** (github.com/opentofu/opentofu) - infrastructure-as-\
code provisioning in Build Manager

## Build Manager target images

The Ubuntu and RHEL8 target images Build Manager ships for exercising its \
own Ansible roles are themselves built from:

- **Ubuntu 24.04** (`ubuntu:24.04`)
- **Red Hat UBI8** (`registry.access.redhat.com/ubi8/ubi-init:8.10`)

---

*Admins: if we add, remove, or upgrade a dependency in a way that changes \
this list, please keep this page up to date via the Edit button above. \
Versions above reflect what was actually installed in this image as of \
the last time this page was updated - re-check them (e.g. `pip freeze` \
in the running container, `frontend/package-lock.json`) after any \
rebuild if you need current-to-the-minute figures for a license review.*
"""


def upgrade():
    op.create_table(
        'about_page',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('updated_by', sa.String(128), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    about_page = sa.table(
        'about_page',
        sa.column('id', sa.String(16)),
        sa.column('content', sa.Text()),
    )
    op.bulk_insert(about_page, [{'id': 'global', 'content': _SEED_CONTENT}])


def downgrade():
    op.drop_table('about_page')
