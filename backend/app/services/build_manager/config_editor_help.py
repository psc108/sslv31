"""Config editor contextual help — per-file documentation."""

from typing import Any

# Help content keyed by file path (matches registry paths)
_HELP: dict[str, dict[str, Any]] = {
    "/data/ansible.cfg": {
        "summary": "Ansible runtime configuration. Controls SSH behaviour, parallelism, timeouts, and role search paths.",
        "directives": [
            {"key": "host_key_checking", "purpose": "Verify SSH host keys on connect", "default": "False"},
            {"key": "timeout", "purpose": "SSH connection timeout (seconds)", "default": "30"},
            {"key": "forks", "purpose": "Max parallel host connections", "default": "10"},
            {"key": "pipelining", "purpose": "Reduce SSH round-trips (faster execution)", "default": "True"},
            {"key": "roles_path", "purpose": "Where Ansible searches for roles", "default": "/opt/certmanager/playbooks/roles"},
            {"key": "retry_files_enabled", "purpose": "Create .retry files on failure", "default": "False"},
        ],
        "examples": [
            {"title": "Increase parallelism", "code": "[defaults]\nforks = 20"},
            {"title": "Add custom roles path", "code": "[defaults]\nroles_path = /opt/certmanager/playbooks/roles:/data/custom-roles"},
        ],
        "related_docs": ["Section 4 — Inventory & Hosts", "Section 6 — Jobs"],
    },
    "/etc/nginx/sites-available/default": {
        "summary": "Nginx reverse proxy configuration. Routes browser requests to the React frontend and API requests to the FastAPI backend.",
        "directives": [
            {"key": "listen", "purpose": "Port and protocol to listen on", "default": "80"},
            {"key": "proxy_pass", "purpose": "Backend URL to forward requests to", "default": "http://127.0.0.1:8000"},
            {"key": "location /api/", "purpose": "API route prefix forwarded to FastAPI", "default": ""},
            {"key": "location /", "purpose": "All other routes serve the React SPA", "default": ""},
        ],
        "examples": [
            {"title": "Add HTTPS", "code": "listen 443 ssl;\nssl_certificate /etc/ssl/certs/server.pem;\nssl_certificate_key /etc/ssl/private/server-key.pem;"},
        ],
        "related_docs": ["Section 7 — Product Deployment (Nginx Role)"],
    },
    "/opt/certmanager/playbooks/site.yml": {
        "summary": "Master playbook that orchestrates the full provisioning workflow. Imports base-provision.yml and products.yml in sequence.",
        "directives": [
            {"key": "import_playbook", "purpose": "Include another playbook in execution order", "default": ""},
            {"key": "hosts", "purpose": "Target host pattern (usually 'all')", "default": "all"},
        ],
        "examples": [
            {"title": "Add a post-deploy step", "code": "- import_playbook: post-deploy.yml"},
        ],
        "related_docs": ["Section 7 — Product Deployment", "Section 6 — Jobs"],
    },
    "/opt/certmanager/playbooks/base-provision.yml": {
        "summary": "Base host provisioning entry point. Applies the 'base' role to all hosts — installs Java, deploys CA chain, issues certificates, builds JKS/PKCS12.",
        "directives": [
            {"key": "hosts", "purpose": "Target hosts (all managed hosts)", "default": "all"},
            {"key": "roles", "purpose": "Roles to apply", "default": "[base]"},
            {"key": "become", "purpose": "Run with sudo/root privileges", "default": "true"},
        ],
        "examples": [],
        "related_docs": ["Section 3 — Environments (Base Provisioning)"],
    },
    "/opt/certmanager/playbooks/products.yml": {
        "summary": "Product deployment entry point. Applies product-specific roles (nginx, mysql, rabbitmq, etc.) based on the template spec's host_products mapping.",
        "directives": [
            {"key": "hosts", "purpose": "Target hosts for product deployment", "default": "all"},
            {"key": "roles", "purpose": "Dynamically assigned from template spec", "default": ""},
        ],
        "examples": [],
        "related_docs": ["Section 7 — Product Deployment", "Section 5 — Product Catalogue"],
    },
    "/opt/certmanager/playbooks/verify.yml": {
        "summary": "Post-deployment TLS verification playbook. Checks that certificates are correctly installed and services respond over TLS.",
        "directives": [],
        "examples": [],
        "related_docs": ["Section 10 — TLS Verification"],
    },
    "/opt/certmanager/playbooks/roles/base/tasks/main.yml": {
        "summary": "Base provisioning role applied to all managed hosts. Installs Java 17, deploys CA chain to system trust store, issues server certificates, builds Java TrustStore/KeyStore.",
        "directives": [
            {"key": "server_cert_pem", "purpose": "Server certificate PEM content (injected by provisioner)", "default": ""},
            {"key": "server_key_pem", "purpose": "Server private key PEM content", "default": ""},
            {"key": "ca_chain_pem", "purpose": "Full CA chain PEM (root + intermediate)", "default": ""},
            {"key": "truststore_password", "purpose": "Auto-generated password for Java TrustStore", "default": ""},
            {"key": "keystore_password", "purpose": "Auto-generated password for Java KeyStore", "default": ""},
            {"key": "ansible_facts.os_family", "purpose": "Detected OS family (Debian, RedHat, Alpine, Archlinux)", "default": ""},
        ],
        "examples": [
            {"title": "Add a custom CA trust step", "code": "- name: Deploy custom CA\n  copy:\n    content: \"{{ custom_ca_pem }}\"\n    dest: /usr/local/share/ca-certificates/custom.crt\n  notify: update-ca-trust"},
        ],
        "related_docs": ["Section 3 — Environments (Base Provisioning)", "Section 11 — Certificate Lifecycle"],
    },
    "/opt/certmanager/playbooks/roles/nginx/tasks/main.yml": {
        "summary": "Installs Nginx, deploys TLS certificates, configures server blocks with SSL termination, and enables the service.",
        "directives": [
            {"key": "nginx_server_name", "purpose": "Server name for the virtual host", "default": "{{ inventory_hostname }}"},
            {"key": "nginx_listen_port", "purpose": "HTTPS listen port", "default": "443"},
            {"key": "nginx_upstream_port", "purpose": "Backend port to proxy to", "default": "8000"},
        ],
        "examples": [
            {"title": "Change upstream port", "code": "nginx_upstream_port: 3000"},
        ],
        "related_docs": ["Section 7 — Product Deployment (Nginx Role)"],
    },
    "/opt/certmanager/playbooks/roles/mysql/tasks/main.yml": {
        "summary": "Installs MySQL 8.x, configures TLS (require_secure_transport), creates databases and users, and restarts the service.",
        "directives": [
            {"key": "mysql_root_password", "purpose": "Root password (from vault)", "default": "vault_mysql_root_password"},
            {"key": "mysql_databases", "purpose": "List of databases to create", "default": "[]"},
            {"key": "mysql_users", "purpose": "List of users with privileges", "default": "[]"},
            {"key": "mysql_bind_address", "purpose": "Network bind address", "default": "0.0.0.0"},
        ],
        "examples": [
            {"title": "Add a database", "code": "mysql_databases:\n  - name: myapp\n    encoding: utf8mb4"},
        ],
        "related_docs": ["Section 7 — Product Deployment (MySQL Role)", "Section 12 — Secrets Management"],
    },
    "/opt/certmanager/playbooks/roles/rabbitmq/tasks/main.yml": {
        "summary": "Installs RabbitMQ with management plugin, configures TLS listeners, creates vhosts and users.",
        "directives": [
            {"key": "rabbitmq_admin_password", "purpose": "Admin password (from vault)", "default": "vault_rabbitmq_admin_password"},
            {"key": "rabbitmq_vhosts", "purpose": "List of virtual hosts to create", "default": "[]"},
            {"key": "rabbitmq_users", "purpose": "List of users with permissions", "default": "[]"},
            {"key": "rabbitmq_ssl_port", "purpose": "AMQPS listener port", "default": "5671"},
            {"key": "rabbitmq_management_port", "purpose": "Management UI port", "default": "15672"},
        ],
        "examples": [
            {"title": "Add a vhost", "code": "rabbitmq_vhosts:\n  - name: /myapp\n    tracing: false"},
        ],
        "related_docs": ["Section 7 — Product Deployment (RabbitMQ Role)"],
    },
    "/opt/certmanager/playbooks/roles/keystone/tasks/main.yml": {
        "summary": "Installs OpenStack Keystone in a Python venv with Apache mod_wsgi, configures TLS, and bootstraps the admin project/user.",
        "directives": [
            {"key": "keystone_admin_token", "purpose": "Bootstrap admin token (from vault)", "default": "vault_keystone_admin_token"},
            {"key": "keystone_db_connection", "purpose": "Database connection string", "default": "sqlite:////var/lib/keystone/keystone.db"},
            {"key": "keystone_public_endpoint", "purpose": "Public API endpoint URL", "default": "https://{{ inventory_hostname }}:5000"},
        ],
        "examples": [],
        "related_docs": ["Section 7 — Product Deployment (Keystone Role)"],
    },
    "/opt/certmanager/playbooks/roles/uvicorn/tasks/main.yml": {
        "summary": "Deploys a FastAPI application with Uvicorn, configures TLS with optional mTLS client certificates, and manages it via systemd.",
        "directives": [
            {"key": "uvicorn_app_module", "purpose": "Python module path for the ASGI app", "default": "main:app"},
            {"key": "uvicorn_port", "purpose": "Listen port", "default": "8000"},
            {"key": "uvicorn_workers", "purpose": "Number of worker processes", "default": "2"},
            {"key": "uvicorn_require_client_cert", "purpose": "Require mTLS client certificate", "default": "false"},
            {"key": "uvicorn_git_repo", "purpose": "Git repository to clone (optional)", "default": ""},
        ],
        "examples": [
            {"title": "Enable mTLS", "code": "uvicorn_require_client_cert: true"},
            {"title": "Deploy from git", "code": "uvicorn_git_repo: https://github.com/org/myapi.git\nuvicorn_git_branch: main"},
        ],
        "related_docs": ["Section 7 — Product Deployment (Uvicorn Role)"],
    },
    "/opt/certmanager/docker-compose.build-manager.yml": {
        "summary": "Docker Compose file defining the Build Manager development environment. Includes certmanager and all target containers on the bm-net network.",
        "directives": [
            {"key": "services", "purpose": "Container definitions (certmanager + targets)", "default": ""},
            {"key": "networks.bm-net", "purpose": "Shared Docker network for inter-container communication", "default": ""},
            {"key": "volumes", "purpose": "Named volumes for persistent data", "default": ""},
            {"key": "privileged: true", "purpose": "Required for systemd in target containers", "default": ""},
        ],
        "examples": [
            {"title": "Add a new target", "code": "  target-newhost:\n    build:\n      context: .\n      dockerfile: Dockerfile.target\n    privileged: true\n    networks:\n      - bm-net"},
        ],
        "related_docs": ["Section 1 — Getting Started"],
    },
}

# Default help for files without specific content
_DEFAULT_HELP: dict[str, Any] = {
    "summary": "",
    "directives": [],
    "examples": [],
    "related_docs": [],
}


def get_file_help(path: str) -> dict[str, Any]:
    """Return contextual help for a file by its path."""
    help_data = _HELP.get(path, _DEFAULT_HELP)
    return {
        "summary": help_data["summary"],
        "directives": help_data["directives"],
        "examples": help_data["examples"],
        "related_docs": help_data["related_docs"],
    }
