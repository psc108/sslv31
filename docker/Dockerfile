# Stage 1: Frontend build
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json ./
RUN npm install
COPY frontend/ .
RUN npx vite build

# Stage 2: Python runtime with JDK
FROM python:3.12-slim AS runtime

# Install system dependencies (openssl, curl, nginx, ssh, ansible, mysqldump/mysql for MySQL backup/restore,
# libpango/libcairo/fonts-dejavu for weasyprint's HTML->PDF rendering used by
# the JAR Analyser change-report export and the Build Manager compliance export)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssl curl nginx wget gnupg openssh-client sshpass default-mysql-client \
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

# Install Eclipse Temurin JRE 17 (direct tarball — no repo needed)
RUN wget --no-check-certificate -qO /tmp/jre.tar.gz \
    "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.13%2B11/OpenJDK17U-jre_x64_linux_hotspot_17.0.13_11.tar.gz" && \
    mkdir -p /opt/java && \
    tar -xzf /tmp/jre.tar.gz -C /opt/java --strip-components=1 && \
    rm /tmp/jre.tar.gz && \
    ln -s /opt/java/bin/java /usr/local/bin/java && \
    ln -s /opt/java/bin/keytool /usr/local/bin/keytool

ENV JAVA_HOME=/opt/java
ENV JDK_HOME=/opt/java

# Install CFR (standalone Java decompiler, single self-contained jar — no
# other deps beyond the JRE already installed above) for the JAR Analyser's
# on-demand decompile feature. Same download pattern as the JRE/OpenTofu
# above (wget --no-check-certificate to bypass the TLS-inspecting corporate
# proxy this build environment sits behind).
ARG CFR_VERSION=0.152
RUN mkdir -p /opt/certmanager/tools && \
    wget --no-check-certificate -qO /opt/certmanager/tools/cfr.jar \
    "https://github.com/leibnitz27/cfr/releases/download/${CFR_VERSION}/cfr-${CFR_VERSION}.jar"

# Install Vineflower (second decompiler engine, run alongside CFR on every
# decompile — the two use different internal heuristics, so a class that
# comes out thin/wrong from one is often fine from the other). "Slim" jar:
# decompiler only, none of the bundled plugins we don't need. Same download
# pattern as CFR above.
ARG VINEFLOWER_VERSION=1.12.0
RUN wget --no-check-certificate -qO /opt/certmanager/tools/vineflower.jar \
    "https://github.com/Vineflower/vineflower/releases/download/${VINEFLOWER_VERSION}/vineflower-${VINEFLOWER_VERSION}-slim.jar"

# Record the two decompiler jars' versions for the About page's "Regenerate
# from installed packages" action (app/services/about_generator.py) — CFR
# and Vineflower are plain jars downloaded and renamed generically above,
# with no `--version` flag or filename to introspect at runtime, so this
# ARG-interpolated file is the only place their version survives past the
# build. Everything else the generator reports is detected live at request
# time instead (pip metadata, package-lock.json, `tofu version`, etc.) —
# this manifest exists specifically because these two can't be.
RUN echo "{\"cfr_version\": \"${CFR_VERSION}\", \"vineflower_version\": \"${VINEFLOWER_VERSION}\"}" \
    > /opt/certmanager/tools/bundled_tool_versions.json

# Create application user
RUN groupadd -r certmgr && useradd -r -g certmgr -s /bin/false -d /opt/certmanager certmgr

# Application directory
WORKDIR /opt/certmanager

# Install OpenTofu (direct binary download — bypasses TLS-inspecting proxy
# the same way the JRE download above does)
ARG TOFU_VERSION=1.8.3
RUN wget --no-check-certificate -qO /tmp/tofu.tar.gz \
    "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_amd64.tar.gz" && \
    tar -xzf /tmp/tofu.tar.gz -C /usr/local/bin tofu && \
    rm /tmp/tofu.tar.gz && \
    tofu version

# Python dependencies
COPY backend/requirements.txt .
RUN python -m venv venv && \
    venv/bin/pip install --no-cache-dir --upgrade pip && \
    venv/bin/pip install --no-cache-dir -r requirements.txt && \
    venv/bin/pip install --no-cache-dir boto3 && \
    venv/bin/pip install --no-cache-dir ansible-core && \
    venv/bin/ansible-galaxy collection install ansible.posix --ignore-certs

# Neural — ML intelligence layer
# Copied before the backend source so Docker layer-caches it independently.
# torch CPU-only wheel keeps the image ~1.8 GB smaller than the default CUDA build.
COPY Neural/ Neural/
RUN venv/bin/pip install --no-cache-dir --upgrade setuptools wheel && \
    venv/bin/pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    ./Neural
# ansible.posix provides the `mount` module — ansible-core alone (installed
# above) only bundles ansible.builtin, and `mount` was moved out of that into
# this separate collection in ansible-core 2.10+. Found the hard way: the
# nfs_client role's "Mount NFS shares" task (playbooks/roles/nfs_client/tasks/main.yml)
# had never actually been exercised through a real Ansible run until the Full
# Stack template's NFS-based redesign was live-tested — it failed immediately
# with "couldn't resolve module/action 'mount'" the very first time.
# --ignore-certs: this build environment sits behind TLS-inspecting corporate
# network security software that galaxy.ansible.com's cert chain doesn't
# verify against cleanly ("unable to get local issuer certificate") — the
# exact same class of issue already worked around a few lines up with
# `wget --no-check-certificate` for the JRE download.

# Backend source
COPY backend/app/ app/
COPY backend/alembic/ alembic/
COPY backend/alembic.ini .
COPY scripts/ scripts/

# Documentation (for in-app help)
COPY Documentation/ Documentation/

# Ansible playbooks and roles
COPY playbooks/ playbooks/

# OpenTofu workspaces (bootstrap + modules) — stored outside /data so they
# survive the VOLUME mount; entrypoint.sh copies them into /data/tofu/ on
# first start if not already present.
COPY tofu/ tofu/

# Frontend dist from build stage
COPY --from=frontend-build /build/dist/ frontend/dist/

# Frontend package manifest + lockfile (not the dist build, which is already
# copied above) — the About page's "Regenerate" action parses these at
# request time to report each shipped frontend dependency's exact resolved
# version, the same way it reads pip metadata for backend packages. Tiny
# text files, no build-tooling weight added to the runtime image.
COPY frontend/package.json frontend/package-lock.json frontend-meta/

# Nginx config
COPY docker/nginx.conf /etc/nginx/sites-available/default

# Entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Data volume
RUN mkdir -p /data/self /data/exports /data/backups /data/ssh /data/playbooks /data/tofu && \
    chown -R certmgr:certmgr /data
VOLUME ["/data"]

# Environment defaults
ENV DATA_DIR=/data \
    BACKUP_DIR=/data/backups \
    LOG_LEVEL=INFO \
    LOG_FILE=/dev/stdout \
    PYTHONPATH=/opt/certmanager

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 443 80 8000

ENTRYPOINT ["/entrypoint.sh"]
