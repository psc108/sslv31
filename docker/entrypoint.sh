#!/bin/bash
set -e

DATA_DIR="${DATA_DIR:-/data}"
VENV="/opt/certmanager/venv/bin"

# Ensure data directories exist
mkdir -p "$DATA_DIR"/{self,exports,backups}

# Generate secrets on first run if not provided
if [ -z "$CERT_MASTER_KEY" ]; then
    if [ -f "$DATA_DIR/.master_key" ]; then
        export CERT_MASTER_KEY=$(cat "$DATA_DIR/.master_key")
    else
        echo "Generating CERT_MASTER_KEY (first run)..."
        export CERT_MASTER_KEY=$($VENV/python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
        echo "$CERT_MASTER_KEY" > "$DATA_DIR/.master_key"
        chmod 600 "$DATA_DIR/.master_key"
    fi
fi

if [ -z "$API_KEY" ]; then
    if [ -f "$DATA_DIR/.api_key" ]; then
        export API_KEY=$(cat "$DATA_DIR/.api_key")
    else
        echo "Generating API_KEY (first run)..."
        export API_KEY=$($VENV/python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        echo "$API_KEY" > "$DATA_DIR/.api_key"
        chmod 600 "$DATA_DIR/.api_key"
        echo ""
        echo "============================================"
        echo "  API_KEY: $API_KEY"
        echo "  Save this — paste into Settings in browser"
        echo "============================================"
        echo ""
    fi
fi

# Run database migrations
echo "Running migrations..."
cd /opt/certmanager
$VENV/alembic upgrade head

# Seed built-in KB entries into the docs table (idempotent — skips existing)
echo "Seeding KB entries..."
$VENV/python3 /opt/certmanager/scripts/seed_kb_as_docs.py

# Ensure log directory exists for Neural ML log ingestion
mkdir -p "$DATA_DIR/logs"

# Generate SSH keypair for Build Manager (if not exists)
if [ ! -f "$DATA_DIR/ssh/id_ed25519" ]; then
    echo "Generating SSH keypair for Build Manager..."
    mkdir -p "$DATA_DIR/ssh"
    ssh-keygen -t ed25519 -f "$DATA_DIR/ssh/id_ed25519" -N "" -C "buildmanager@certmanager"
    chmod 600 "$DATA_DIR/ssh/id_ed25519"
    echo ""
    echo "Build Manager SSH public key:"
    cat "$DATA_DIR/ssh/id_ed25519.pub"
    echo ""
fi

# Create ansible.cfg if not exists
if [ ! -f "$DATA_DIR/ansible.cfg" ]; then
    cat > "$DATA_DIR/ansible.cfg" << 'EOF'
[defaults]
inventory = /data/ansible_inventory.py
remote_tmp = /tmp/.ansible/tmp
host_key_checking = False
timeout = 30
forks = 10
roles_path = /opt/certmanager/playbooks/roles:/data/playbooks/roles

[ssh_connection]
# ControlMaster restored: removing it (tried first) made things worse, not
# better — dpkg.log evidence from a real live build showed the remote apt
# process getting killed exactly when a *new* SSH connection was being
# negotiated (every task opens a fresh one with ControlMaster off), not
# during an established, idle, or long-running session. A persisted master
# connection means most tasks reuse an already-negotiated session instead of
# repeatedly hitting whatever is fragile about connection setup on this
# Docker host's network. Keepalive probes are added so that persisted
# connection gets kept warm/detected-dead reliably instead of silently
# rotting, and retries still covers genuinely transient drops.
ssh_args = -o StrictHostKeyChecking=no -o ControlMaster=auto -o ControlPersist=300s -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o TCPKeepAlive=yes
retries = 3
pipelining = True
EOF
fi
export ANSIBLE_CONFIG="$DATA_DIR/ansible.cfg"

# Seed /data/tofu from the image's bundled copy on first start
# (VOLUME mount shadows build-time COPY into /data, so we do it here instead)
if [ ! -d "$DATA_DIR/tofu/bootstrap" ]; then
    echo "Seeding OpenTofu workspaces into $DATA_DIR/tofu/..."
    cp -r /opt/certmanager/tofu/. "$DATA_DIR/tofu/"
fi

# Start Nginx in background
echo "Starting Nginx..."
nginx

# Start application
echo "Starting SSL Certificate Manager..."
exec $VENV/gunicorn \
    -k uvicorn.workers.UvicornWorker \
    -w 2 \
    --bind 0.0.0.0:8000 \
    --timeout 600 \
    --access-logfile - \
    app.main:app
