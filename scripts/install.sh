#!/bin/bash
# SSL Certificate Manager — Ubuntu Installation Script
# Covers: system prep, venv, frontend build, bootstrap, nginx, systemd, smoke test
#
# Run as root on Ubuntu 22.04 or 24.04 LTS
# Usage: sudo bash install.sh

set -euo pipefail

APP_DIR="/opt/certmanager"
CONF_DIR="/etc/certmanager"
DATA_DIR="/var/lib/certmanager"
LOG_DIR="/var/log/certmanager"
SERVICE_USER="certmgr"

echo "=== SSL Certificate Manager Installation ==="
echo ""

# --- F-01: System Preparation ---
echo "[1/7] System preparation..."

# Create user
if ! id -u ${SERVICE_USER} &>/dev/null; then
    useradd -r -s /bin/false -d ${APP_DIR} ${SERVICE_USER}
    echo "  Created user: ${SERVICE_USER}"
fi

# Install packages
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    openjdk-17-jre-headless \
    nginx openssl curl

echo "  System packages installed"

# Directory structure
mkdir -p ${APP_DIR}/{app,alembic,frontend/dist}
mkdir -p ${CONF_DIR}
mkdir -p ${DATA_DIR}/{self,exports,backups}
mkdir -p ${LOG_DIR}

chown -R ${SERVICE_USER}:${SERVICE_USER} ${APP_DIR}
chown -R ${SERVICE_USER}:${SERVICE_USER} ${DATA_DIR}
chown root:${SERVICE_USER} ${CONF_DIR}
chmod 750 ${CONF_DIR}
chown ${SERVICE_USER}:adm ${LOG_DIR}
chmod 750 ${LOG_DIR}
chmod 700 ${DATA_DIR}

echo "  Directory structure created"

# --- F-02: Python Virtual Environment ---
echo "[2/7] Setting up Python environment..."

if [ ! -d "${APP_DIR}/venv" ]; then
    python3 -m venv ${APP_DIR}/venv
fi
${APP_DIR}/venv/bin/pip install --quiet --upgrade pip
${APP_DIR}/venv/bin/pip install --quiet -r ${APP_DIR}/requirements.txt
chown -R ${SERVICE_USER}:${SERVICE_USER} ${APP_DIR}/venv

echo "  Python venv ready"

# --- F-03: Frontend Build ---
echo "[3/7] Building frontend..."

if command -v node &>/dev/null; then
    if [ -f "${APP_DIR}/frontend/package.json" ]; then
        cd ${APP_DIR}/frontend
        npm ci --quiet
        npm run build --quiet
        echo "  Frontend built"
    else
        echo "  SKIP: No package.json found (frontend may be pre-built)"
    fi
else
    echo "  SKIP: Node.js not installed (frontend must be pre-built)"
fi

# --- F-04: Bootstrap ---
echo "[4/7] Running bootstrap..."

# Generate master key if not set
ENV_FILE="${CONF_DIR}/certmanager.env"
if [ ! -f "${ENV_FILE}" ]; then
    MASTER_KEY=$(${APP_DIR}/venv/bin/python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    cat > ${ENV_FILE} << EOF
CERT_MASTER_KEY=${MASTER_KEY}
API_KEY=placeholder
DATA_DIR=${DATA_DIR}
BACKUP_DIR=${DATA_DIR}/backups
LOG_LEVEL=INFO
LOG_FILE=${LOG_DIR}/app.log
BASE_URL=https://$(hostname -f)
BOOTSTRAP_IP=$(hostname -I | awk '{print $1}')
EOF
    chown root:${SERVICE_USER} ${ENV_FILE}
    chmod 640 ${ENV_FILE}
    echo "  Environment file created: ${ENV_FILE}"
fi

# Source env for bootstrap
set -a
source ${ENV_FILE}
set +a

# Pass 1
cd ${APP_DIR}
sudo -u ${SERVICE_USER} ${APP_DIR}/venv/bin/python -m app.bootstrap --pass1
echo "  Pass 1 complete"

# --- F-05: Nginx Configuration ---
echo "[5/7] Configuring Nginx..."

cp ${APP_DIR}/scripts/certmanager.nginx.conf /etc/nginx/sites-available/certmanager

# Update server_name to actual hostname
HOSTNAME=$(hostname -f)
sed -i "s/certs.cso.internal/${HOSTNAME}/g" /etc/nginx/sites-available/certmanager

ln -sf /etc/nginx/sites-available/certmanager /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx

echo "  Nginx configured and reloaded"

# --- Pass 2 (after nginx reload) ---
echo "  Running bootstrap pass 2..."
cd ${APP_DIR}
API_KEY_OUTPUT=$(sudo -u ${SERVICE_USER} ${APP_DIR}/venv/bin/python -m app.bootstrap --pass2 2>&1)
echo "${API_KEY_OUTPUT}"

# Extract API key from output and update env file
NEW_API_KEY=$(echo "${API_KEY_OUTPUT}" | grep -oP '(?<=  )[A-Za-z0-9_-]{32,}' | head -1)
if [ -n "${NEW_API_KEY}" ]; then
    sed -i "s/API_KEY=placeholder/API_KEY=${NEW_API_KEY}/" ${ENV_FILE}
    echo "  API key saved to ${ENV_FILE}"
fi

# --- F-06: systemd Service ---
echo "[6/7] Installing systemd service..."

cp ${APP_DIR}/scripts/certmanager.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now certmanager

sleep 3
echo "  Service status:"
systemctl status certmanager --no-pager -l | head -5

# --- F-07: Smoke Test ---
echo "[7/7] Smoke test..."

sleep 2
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost/api/v1/health)
if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✓ Health check passed (HTTP ${HTTP_CODE})"
    curl -sk https://localhost/api/v1/health | python3 -m json.tool
else
    echo "  ✗ Health check failed (HTTP ${HTTP_CODE})"
    echo "    Check logs: journalctl -u certmanager -n 20"
    exit 1
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "  1. Download root CA: https://${HOSTNAME}/settings"
echo "  2. Import root CA into browser and client truststores"
echo "  3. API key stored in: ${ENV_FILE}"
echo ""
