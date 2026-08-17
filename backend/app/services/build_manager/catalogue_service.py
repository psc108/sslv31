"""Product Catalogue service — CRUD, compatibility checking, seed data."""

import json
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.build_manager import BMProduct, BMProductVersion, BMProductConfig


# ============================================================
# CONSTANTS
# ============================================================

VALID_DEPLOYMENT_TARGETS = {"ec2", "rds", "s3"}

ENGINE_COMPAT_MAP = {
    "rds_mysql":      "mysql-rds",
    "aurora_mysql":   "aurora-mysql",
    "rds_postgres":   "postgres-rds",
    "aurora_postgres": "aurora-postgres",
}

ENGINE_TOFU_MAP = {
    "mysql-rds":      "rds_mysql",
    "aurora-mysql":   "aurora_mysql",
    "postgres-rds":   "rds_postgres",
    "aurora-postgres": "aurora_postgres",
}


# ============================================================
# SEED DATA
# ============================================================

SEED_PRODUCTS = [
    {
        "name": "nginx",
        "display_name": "Nginx",
        "category": "web_server",
        "icon": "🌐",
        "description": "High-performance HTTP server and reverse proxy",
        "default_ports": [80, 443],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "nginx_server_name", "label": "Server Name", "type": "text", "required": False, "default": "_", "placeholder": "e.g. app.example.com"},
            {"key": "nginx_upstream", "label": "Upstream (proxy_pass)", "type": "text", "required": False, "default": "", "placeholder": "e.g. http://backend:8000"},
            {"key": "nginx_root", "label": "Document Root", "type": "text", "required": False, "default": "/var/www/html"},
            {"key": "nginx_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "nginx_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "nginx_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": "", "placeholder": "Paste file content (or use upload)"},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644", "placeholder": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "1.24", "ansible_role": "nginx", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {"nginx_worker_processes": "auto"}},
            {"version": "1.26", "ansible_role": "nginx", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {"nginx_worker_processes": "auto"},
             "aws_defaults": {"instance_type": "t3.small", "root_volume_gb": 20}},
        ],
    },
    {
        "name": "nginx_lb",
        "display_name": "Nginx Load Balancer",
        "category": "networking",
        "icon": "🔀",
        # Modeled directly on the real application's own frontend-lb/backend-lb
        # nginx configs (captured via the JAR Analyser, jar_type
        # "nginx_installer") — both terminate client-facing TLS with their own
        # cert, then re-encrypt outbound (proxy_pass https://, not plaintext)
        # to each named upstream service. This is deliberately one reusable
        # product used for both roles, since the real app deploys the exact
        # same nginx_installer artifact for both, just with a different .conf.
        "description": "TLS-terminating, multi-service reverse-proxy load balancer that re-encrypts to each upstream over HTTPS — used as both frontend-lb and backend-lb.",
        "default_ports": [80, 443],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "lb_upstreams", "label": "Upstream Services", "type": "list", "required": True, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Name", "type": "text", "required": True, "placeholder": "catalog"},
                 {"key": "path", "label": "Path", "type": "text", "required": True, "placeholder": "/api/catalog/"},
                 {"key": "host", "label": "Host", "type": "text", "required": True, "placeholder": "catalog"},
                 {"key": "port", "label": "Port", "type": "number", "required": True, "placeholder": 8090},
             ]},
            {"key": "nginx_lb_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "nginx_lb_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "1", "ansible_role": "nginx_lb", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {},
             "aws_defaults": {"instance_type": "t3.small", "root_volume_gb": 20}},
        ],
    },
    {
        "name": "mysql",
        "display_name": "MySQL Server",
        "category": "database",
        "icon": "🗄️",
        "description": "Relational database with TLS and optional mTLS",
        "default_ports": [3306],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "mysql_root_password", "label": "Root Password", "type": "password", "required": True, "default": "", "placeholder": "Enter root password"},
            {"key": "mysql_port", "label": "Port", "type": "number", "required": False, "default": 3306},
            {"key": "mysql_bind_address", "label": "Bind Address", "type": "text", "required": False, "default": "0.0.0.0"},
            {"key": "mysql_databases", "label": "Databases", "type": "list", "required": False, "default": [],
             "item_schema": [{"key": "name", "label": "Database Name", "type": "text", "required": True}]},
            {"key": "mysql_users", "label": "Users", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Username", "type": "text", "required": True},
                 {"key": "password", "label": "Password", "type": "password", "required": True},
                 {"key": "host", "label": "Host", "type": "text", "required": False, "default": "%", "placeholder": "% for any host"},
                 {"key": "priv", "label": "Privileges", "type": "text", "required": False, "default": "*.*:ALL PRIVILEGES", "placeholder": "db.*:ALL PRIVILEGES"}
             ]},
            {"key": "mysql_allow_remote_root", "label": "Allow Remote Root Login", "type": "checkbox", "required": False,
             "help": "Grants root@'%' (over TLS) in addition to the default root@'localhost'. Off by default; automatically enabled when Adminer is paired with MySQL in the same environment unless set explicitly here."},
            {"key": "mysql_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "mysql_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "mysql_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": "", "placeholder": "Paste file content (or use upload)"},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644", "placeholder": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "8.0", "ansible_role": "mysql", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {"mysql_port": 3306}},
            {"version": "8.4", "ansible_role": "mysql", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {"mysql_port": 3306},
             "aws_defaults": {"instance_type": "t3.medium", "root_volume_gb": 30}},
            {"version": "9.0", "ansible_role": "mysql", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "24.04"}, {"os": "rhel", "min": "9"}],
             "default_vars": {"mysql_port": 3306},
             "eol_date": "2025-12-01"},
        ],
    },
    {
        "name": "adminer",
        "display_name": "Adminer",
        "category": "utility",
        "icon": "🛠️",
        "description": "Single-file web-based database admin panel (MySQL and others) — bundles its own PHP-FPM + Nginx TLS front, so it works as a standalone add-on without needing PHP configured by hand.",
        "default_ports": [8443],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": ["php"],
        "config_schema": [
            {"key": "adminer_server_name", "label": "Server Name", "type": "text", "required": False, "default": "_", "placeholder": "e.g. admin.example.com"},
            {"key": "adminer_listen_port", "label": "TLS Listen Port", "type": "number", "required": False, "default": 8443},
            {"key": "adminer_default_server", "label": "Default MySQL Host (pre-filled in login form)", "type": "text", "required": False, "placeholder": "auto-detected when MySQL is paired in this environment, else 127.0.0.1"},
            {"key": "adminer_version", "label": "Adminer Version", "type": "text", "required": False, "default": "4.8.1"},
            {"key": "adminer_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "adminer_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "4.8.1", "ansible_role": "adminer", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {},
             "requires": [{"product": "php", "min_version": "8.0", "reason": "PHP 8+ runtime required (Adminer installs its own PHP-FPM regardless of whether the PHP product is also selected — this is compatibility metadata, matching how Keystone declares Apache and RabbitMQ declares Erlang)"}],
             "conflicts_with": [
                 {"product": "nginx", "reason": "Adminer installs and manages its own Nginx instance — combining with a separately-selected Nginx product on the same host will overwrite each other's config."},
                 {"product": "nginx_lb", "reason": "Adminer installs and manages its own Nginx instance — combining with a separately-selected Nginx product on the same host will overwrite each other's config."},
                 {"product": "apache", "reason": "Adminer binds its own TLS-terminating web front — check for listen-port conflicts if Apache is also selected on this host."},
             ]},
        ],
    },
    {
        "name": "rabbitmq",
        "display_name": "RabbitMQ",
        "category": "messaging",
        "icon": "📨",
        "description": "Message broker with TLS on AMQP and management UI",
        "default_ports": [5671, 15671],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": ["erlang"],
        "config_schema": [
            {"key": "rabbitmq_admin_password", "label": "Admin Password", "type": "password", "required": True, "default": "", "placeholder": "Enter admin (guest) password"},
            {"key": "rabbitmq_enable_management", "label": "Enable Management UI", "type": "checkbox", "required": False, "default": True},
            {"key": "rabbitmq_vhost", "label": "VHost", "type": "text", "required": False, "default": "/", "placeholder": "e.g. /ssp"},
            {"key": "rabbitmq_ssl_port", "label": "AMQPS Port (listeners.ssl.default)", "type": "number", "required": False, "default": 5671},
            {"key": "rabbitmq_ssl_cacertfile", "label": "CA Cert Path (ssl_options.cacertfile)", "type": "text", "required": False, "default": "/etc/rabbitmq/ssl/ca.crt"},
            {"key": "rabbitmq_ssl_certfile", "label": "Server Cert Path (ssl_options.certfile)", "type": "text", "required": False, "default": "/etc/rabbitmq/ssl/server.crt"},
            {"key": "rabbitmq_ssl_keyfile", "label": "Server Key Path (ssl_options.keyfile)", "type": "select", "required": False, "default": "/etc/rabbitmq/ssl/server.key", "options": ["/etc/rabbitmq/ssl/server.key", "/etc/rabbitmq/ssl/server.key.nopass"]},
            {"key": "rabbitmq_ssl_version_1", "label": "TLS Version 1 (ssl_options.versions.1)", "type": "text", "required": False, "default": "tlsv1.3"},
            {"key": "rabbitmq_ssl_version_2", "label": "TLS Version 2 (ssl_options.versions.2)", "type": "text", "required": False, "default": "tlsv1.2"},
            {"key": "rabbitmq_ssl_verify", "label": "Peer Verification (ssl_options.verify)", "type": "text", "required": False, "default": "verify_none", "placeholder": "verify_none or verify_peer"},
            {"key": "rabbitmq_ssl_fail_if_no_peer_cert", "label": "Fail If No Peer Cert", "type": "text", "required": False, "default": "false", "placeholder": "true or false"},
            {"key": "rabbitmq_tcp_listener", "label": "TCP Listener (listeners.tcp)", "type": "text", "required": False, "default": "none", "placeholder": "none or port number e.g. 5672"},
            {"key": "rabbitmq_management_ssl_port", "label": "Management HTTPS Port", "type": "number", "required": False, "default": 15671},
            {"key": "rabbitmq_heartbeat", "label": "Heartbeat (seconds)", "type": "number", "required": False, "default": 580},
            {"key": "rabbitmq_log_level", "label": "Log Level (log.file.level)", "type": "text", "required": False, "default": "info", "placeholder": "debug, info, warning, error"},
            {"key": "rabbitmq_loopback_users", "label": "Loopback Users", "type": "text", "required": False, "default": "none", "placeholder": "none or comma-separated usernames"},
            {"key": "rabbitmq_users", "label": "Users", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Username", "type": "text", "required": True},
                 {"key": "password", "label": "Password", "type": "password", "required": True},
                 {"key": "tags", "label": "Tags", "type": "text", "required": False, "default": "", "placeholder": "e.g. administrator monitoring"},
                 {"key": "vhost", "label": "VHost", "type": "text", "required": False, "default": "/"},
                 {"key": "configure_priv", "label": "Configure", "type": "text", "required": False, "default": ".*"},
                 {"key": "write_priv", "label": "Write", "type": "text", "required": False, "default": ".*"},
                 {"key": "read_priv", "label": "Read", "type": "text", "required": False, "default": ".*"}
             ]},
            {"key": "rabbitmq_bulk_users", "label": "Bulk User Import (tab-separated: user  configure  write  read)", "type": "textarea", "required": False, "default": "", "placeholder": "blobstore\t.*\t.*\t.*\nrequest\t.*\t.*\t.*\nfulfillment\t.*\t.*\t.*"},
            {"key": "rabbitmq_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "rabbitmq_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "rabbitmq_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": "", "placeholder": "Paste file content (or use upload)"},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644", "placeholder": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "3.12", "ansible_role": "rabbitmq", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "erlang", "min_version": "25", "reason": "Erlang/OTP 25+ required"}],
             "default_vars": {"rabbitmq_ssl_port": 5671}},
            {"version": "3.13", "ansible_role": "rabbitmq", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "erlang", "min_version": "26", "reason": "Erlang/OTP 26+ required"}],
             "default_vars": {"rabbitmq_ssl_port": 5671},
             "aws_defaults": {"instance_type": "t3.medium", "root_volume_gb": 20}},
        ],
    },
    {
        "name": "keystone",
        "display_name": "Keystone",
        "category": "identity",
        "icon": "🔑",
        "description": "OpenStack Identity service with Apache mod_wsgi",
        "default_ports": [5000],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": ["apache"],
        "config_schema": [
            {"key": "keystone_admin_password", "label": "Admin Password", "type": "password", "required": True, "default": "", "placeholder": "Keystone admin user password"},
            {"key": "keystone_port", "label": "Listen Port", "type": "number", "required": False, "default": 5000},
            {"key": "keystone_region", "label": "Region", "type": "text", "required": False, "default": "RegionOne", "placeholder": "e.g. RegionOne"},
            {"key": "keystone_token_provider", "label": "Token Provider", "type": "select", "required": False, "default": "fernet", "options": ["fernet", "jws"]},
            {"key": "keystone_db_connection", "label": "Database Connection", "type": "text", "required": False, "default": "sqlite:////var/lib/keystone/keystone.db", "placeholder": "mysql+pymysql://user:pass@host/dbname"},
            {"key": "keystone_public_endpoint", "label": "Public Endpoint URL", "type": "text", "required": False, "default": "", "placeholder": "https://keystone.internal:5000 (auto-detected if blank)"},
            {"key": "keystone_extra_pip_packages", "label": "Extra Pip Packages (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. requests,boto3==1.34.0"},
            {"key": "keystone_import_params", "label": "Import Script Extra Params (space-separated key,value pairs)", "type": "text", "required": False, "default": "", "placeholder": "e.g. password,changeit — substitutes ${password} in the import YAML deployed via File Deployments below"},
            {"key": "keystone_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "keystone_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "keystone_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/keystone/import.yml to auto-run the roles/domains/users/groups importer, or any other path"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": "", "placeholder": "Paste file content (or use upload)"},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644", "placeholder": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "2024.1", "ansible_role": "keystone", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "apache", "min_version": "2.4", "reason": "Apache HTTPD + mod_wsgi required"}],
             "default_vars": {"keystone_port": 5000}},
            {"version": "2024.2", "ansible_role": "keystone", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "24.04"}, {"os": "rhel", "min": "9"}],
             "requires": [{"product": "apache", "min_version": "2.4", "reason": "Apache HTTPD + mod_wsgi required"}],
             "default_vars": {"keystone_port": 5000},
             "aws_defaults": {"instance_type": "t3.small", "root_volume_gb": 20}},
        ],
    },
    {
        "name": "python",
        "display_name": "Python",
        "category": "runtime",
        "icon": "🐍",
        "description": "Python runtime",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "python_extra_pip_packages", "label": "Extra Pip Packages (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. requests,boto3==1.34.0"},
        ],
        "versions": [
            {"version": "3.11", "ansible_role": "python", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "3.12", "ansible_role": "python", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "3.13", "ansible_role": "python", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "24.04"}, {"os": "rhel", "min": "9"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "uvicorn",
        "display_name": "Uvicorn",
        "category": "runtime",
        "icon": "⚡",
        "description": "ASGI server for FastAPI/Starlette applications",
        "default_ports": [8000],
        "cert_requirements": {"server_tls": True, "client_mtls": True},
        "dependencies": ["python"],
        "config_schema": [
            {"key": "uvicorn_port", "label": "Listen Port", "type": "number", "required": False, "default": 8000},
            {"key": "uvicorn_workers", "label": "Workers", "type": "number", "required": False, "default": 4},
            {"key": "uvicorn_app_module", "label": "App Module", "type": "text", "required": False, "default": "main:app", "placeholder": "e.g. main:app"},
            {"key": "uvicorn_app_repo", "label": "Git Repository", "type": "text", "required": False, "default": "", "placeholder": "https://git.internal/app.git (blank for sample app)"},
            {"key": "uvicorn_app_branch", "label": "Git Branch", "type": "text", "required": False, "default": "main"},
            {"key": "uvicorn_ssl_enabled", "label": "Enable TLS", "type": "text", "required": False, "default": "true"},
            {"key": "uvicorn_extra_pip_packages", "label": "Extra Pip Packages (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. requests,boto3==1.34.0 (installed alongside requirements.txt)"},
            {"key": "uvicorn_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "uvicorn_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "uvicorn_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": "", "placeholder": "Paste file content (or use upload)"},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644", "placeholder": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "0.30", "ansible_role": "uvicorn", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "python", "min_version": "3.11", "reason": "Python 3.11+ required"}],
             "default_vars": {"uvicorn_port": 8000, "uvicorn_workers": 4}},
            {"version": "0.32", "ansible_role": "uvicorn", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "python", "min_version": "3.11", "reason": "Python 3.11+ required"}],
             "default_vars": {"uvicorn_port": 8000, "uvicorn_workers": 4},
             "aws_defaults": {"instance_type": "t3.medium", "root_volume_gb": 20}},
        ],
    },
    {
        "name": "openjdk",
        "display_name": "OpenJDK",
        "category": "runtime",
        "icon": "☕",
        "description": "Java Development Kit",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "versions": [
            {"version": "17", "ansible_role": "openjdk", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "21", "ansible_role": "openjdk", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "erlang",
        "display_name": "Erlang/OTP",
        "category": "runtime",
        "icon": "🧪",
        "description": "Erlang runtime (required by RabbitMQ)",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "versions": [
            {"version": "26", "ansible_role": "erlang", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "27", "ansible_role": "erlang", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "nodejs",
        "display_name": "Node.js",
        "category": "runtime",
        "icon": "🟢",
        "description": "JavaScript runtime built on V8",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "versions": [
            {"version": "18", "ansible_role": "nodejs", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "20", "ansible_role": "nodejs", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "22", "ansible_role": "nodejs", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "9"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "php",
        "display_name": "PHP",
        "category": "runtime",
        "icon": "🐘",
        "description": "PHP-FPM runtime with common extensions (mysqli/pdo_mysql, xml, mbstring, curl)",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "versions": [
            {"version": "8.1", "ansible_role": "php", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "pyyaml",
        "display_name": "PyYAML",
        "category": "library",
        "icon": "📄",
        "description": "YAML parser and emitter for Python 3",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": ["python"],
        "config_schema": [
            {"key": "pyyaml_extra_pip_packages", "label": "Extra Pip Packages (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. requests,boto3==1.34.0"},
        ],
        "versions": [
            {"version": "6.0", "ansible_role": "pyyaml", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "python", "min_version": "3.11", "reason": "Python 3 required"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "jasypt",
        "display_name": "Jasypt",
        "category": "library",
        "icon": "🔐",
        "description": "Java Simplified Encryption library",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": ["openjdk"],
        "config_schema": [
            {"key": "jasypt_install_path", "label": "Install Path", "type": "text", "required": False, "default": "/opt/jasypt"},
        ],
        "versions": [
            {"version": "1.9.3", "ansible_role": "jasypt", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "openjdk", "min_version": "17", "reason": "Java 17+ required"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "bouncycastle",
        "display_name": "Bouncy Castle",
        "category": "library",
        "icon": "🏰",
        "description": "Java cryptography APIs (JCE provider)",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": ["openjdk"],
        "config_schema": [
            {"key": "bouncycastle_install_path", "label": "Install Path", "type": "text", "required": False, "default": "/opt/bouncycastle"},
            {"key": "bouncycastle_register_provider", "label": "Register as JCE Provider", "type": "checkbox", "required": False, "default": True},
        ],
        "versions": [
            {"version": "1.78", "ansible_role": "bouncycastle", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "openjdk", "min_version": "17", "reason": "Java 17+ required"}],
             "default_vars": {}},
            {"version": "1.79", "ansible_role": "bouncycastle", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "openjdk", "min_version": "17", "reason": "Java 17+ required"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "nfs_server",
        "display_name": "NFS Server",
        "category": "storage",
        "icon": "📁",
        "description": "NFS server (kernel nfsd) with configurable exports",
        "default_ports": [2049],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "nfs_exports", "label": "Exports", "type": "list", "required": True, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Export Path", "type": "text", "required": True, "placeholder": "/srv/nfs/share"},
                 {"key": "clients", "label": "Allowed Clients", "type": "text", "required": False, "default": "*", "placeholder": "* or 192.168.50.0/24"},
                 {"key": "options", "label": "Options", "type": "text", "required": False, "default": "rw,sync,no_subtree_check,no_root_squash"},
             ]},
            {"key": "nfs_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "nfs_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "4", "ansible_role": "nfs_server", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "nfs_client",
        "display_name": "NFS Client",
        "category": "storage",
        "icon": "📂",
        "description": "NFS client with configurable mounts",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "nfs_mounts", "label": "Mounts", "type": "list", "required": True, "default": [],
             "item_schema": [
                 {"key": "src", "label": "Server:Path", "type": "text", "required": True, "placeholder": "nfs-server:/srv/nfs-export"},
                 {"key": "path", "label": "Mount Point", "type": "text", "required": True, "placeholder": "/mnt/share"},
                 # nolock,vers=3 (not the default/nfsvers=4) — confirmed by real testing
                 # against a Docker-hosted nfs-kernel-server: NFSv4 needs a properly
                 # configured pseudo-filesystem root to mount a single export cleanly,
                 # which this minimal single-purpose appliance doesn't set up; NFSv3
                 # mounts the plain export directly and works out of the box. rpc.statd
                 # isn't running in these containers, hence nolock.
                 {"key": "opts", "label": "Mount Options", "type": "text", "required": False, "default": "nolock,vers=3", "placeholder": "nolock,vers=3"},
                 {"key": "state", "label": "State", "type": "select", "required": False, "default": "mounted", "options": ["mounted", "present", "unmounted", "absent"]},
             ]},
            {"key": "nfs_client_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "nfs_client_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "4", "ansible_role": "nfs_client", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "pkg_cache_seed",
        "display_name": "Package Cache Seed",
        "category": "utility",
        "icon": "📦",
        "description": "Downloads apt packages (and their dependencies) into a local directory and builds a repo index there, for serving to other hosts (via a shared Docker volume, not a network filesystem) as a local package source instead of every host downloading from the network itself.",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "pkg_cache_seed_dir", "label": "Cache Directory", "type": "text", "required": False,
             "default": "/mnt/pkg-cache/apt", "placeholder": "/mnt/pkg-cache/apt"},
            {"key": "pkg_cache_seed_packages", "label": "Packages to cache (plain list of apt package names)", "type": "list", "required": True, "default": []},
        ],
        "versions": [
            {"version": "1", "ansible_role": "pkg_cache_seed", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "local_repo",
        "display_name": "Local Package Repo (Client)",
        "category": "utility",
        "icon": "🗃️",
        "description": "Configures this host to prefer a local package cache (a directory with a package index — .deb/apt, .rpm/dnf, or .apk) over the network, if one is present. Falls back to normal network provisioning if the cache directory isn't found, so it's safe to add to any host.",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "local_repo_cache_dir", "label": "Cache Directory", "type": "text", "required": False,
             "default": "/certmanager-data/pkg-cache", "placeholder": "/certmanager-data/pkg-cache or /mnt/pkg-cache"},
        ],
        "versions": [
            {"version": "1", "ansible_role": "local_repo", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}, {"os": "alpine", "min": "3.18"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "openldap",
        "display_name": "OpenLDAP",
        "category": "identity",
        "icon": "📖",
        "description": "LDAP directory server for centralised authentication",
        "default_ports": [389, 636],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "ldap_domain", "label": "Domain", "type": "text", "required": True, "placeholder": "example.com"},
            {"key": "ldap_organisation", "label": "Organisation", "type": "text", "required": True, "placeholder": "Example Corp"},
            {"key": "ldap_admin_password", "label": "Admin Password", "type": "password", "required": True, "default": ""},
            {"key": "ldap_tls_enabled", "label": "Enable TLS (LDAPS)", "type": "checkbox", "required": False, "default": True},
            {"key": "ldap_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "ldap_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "ldap_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": ""},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "2.6", "ansible_role": "openldap", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "freeipa_client",
        "display_name": "FreeIPA Client",
        "category": "identity",
        "icon": "🎫",
        "description": "FreeIPA/IdM client — domain join, Kerberos, SSSD",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "freeipa_server", "label": "IPA Server", "type": "text", "required": True, "placeholder": "ipa.example.com"},
            {"key": "freeipa_domain", "label": "Domain", "type": "text", "required": True, "placeholder": "example.com"},
            {"key": "freeipa_realm", "label": "Kerberos Realm", "type": "text", "required": True, "placeholder": "EXAMPLE.COM"},
            {"key": "freeipa_principal", "label": "Enroll Principal", "type": "text", "required": False, "default": "admin", "placeholder": "admin"},
            {"key": "freeipa_password", "label": "Enroll Password", "type": "password", "required": True, "default": ""},
            {"key": "freeipa_mkhomedir", "label": "Create Home Dirs on Login", "type": "checkbox", "required": False, "default": True},
            {"key": "freeipa_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "freeipa_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "4.x", "ansible_role": "freeipa_client", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "ssh_hardening",
        "display_name": "SSH Hardening",
        "category": "networking",
        "icon": "🔒",
        "description": "SSH server hardening — key-only auth, disable root, custom port",
        "default_ports": [22],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "ssh_port", "label": "SSH Port", "type": "number", "required": False, "default": 22},
            {"key": "ssh_permit_root_login", "label": "Permit Root Login", "type": "select", "required": False, "default": "prohibit-password", "options": ["yes", "no", "prohibit-password"]},
            {"key": "ssh_password_auth", "label": "Password Authentication", "type": "select", "required": False, "default": "no", "options": ["yes", "no"]},
            {"key": "ssh_max_auth_tries", "label": "Max Auth Tries", "type": "number", "required": False, "default": 3},
            {"key": "ssh_allowed_users", "label": "Allowed Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "deploy,admin (blank = all users)"},
            {"key": "ssh_x11_forwarding", "label": "X11 Forwarding", "type": "select", "required": False, "default": "no", "options": ["yes", "no"]},
            {"key": "ssh_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "ssh_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "latest", "ansible_role": "ssh_hardening", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "node_exporter",
        "display_name": "Prometheus Node Exporter",
        "category": "monitoring",
        "icon": "📊",
        "description": "Host metrics exporter for Prometheus (CPU, memory, disk, network)",
        "default_ports": [9100],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "node_exporter_port", "label": "Listen Port", "type": "number", "required": False, "default": 9100},
            {"key": "node_exporter_collectors", "label": "Extra Collectors (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "systemd,processes,tcpstat"},
            {"key": "node_exporter_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "node_exporter_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "1.8", "ansible_role": "node_exporter", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "filebeat",
        "display_name": "Filebeat",
        "category": "monitoring",
        "icon": "📄",
        "description": "Lightweight log shipper (Elastic Beats family)",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "filebeat_inputs", "label": "Inputs", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "type", "label": "Type", "type": "select", "required": False, "default": "filestream", "options": ["filestream", "journald", "syslog"]},
                 {"key": "paths", "label": "Paths (comma-separated)", "type": "text", "required": True, "placeholder": "/var/log/*.log, /var/log/syslog"},
             ]},
            {"key": "filebeat_output_type", "label": "Output Type", "type": "select", "required": False, "default": "elasticsearch", "options": ["elasticsearch", "logstash"]},
            {"key": "filebeat_output_host", "label": "Output Host", "type": "text", "required": False, "default": "localhost", "placeholder": "elasticsearch.internal"},
            {"key": "filebeat_output_port", "label": "Output Port", "type": "number", "required": False, "default": 9200},
            {"key": "filebeat_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "filebeat_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "8.15", "ansible_role": "filebeat", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "cadvisor",
        "display_name": "cAdvisor",
        "category": "monitoring",
        "icon": "📦",
        "description": "Container metrics exporter (CPU, memory, network per container)",
        "default_ports": [8080],
        "cert_requirements": {},
        "dependencies": ["docker_ce"],
        "config_schema": [
            {"key": "cadvisor_port", "label": "Listen Port", "type": "number", "required": False, "default": 8080},
            {"key": "cadvisor_docker_socket", "label": "Docker Socket Path", "type": "text", "required": False, "default": "/var/run/docker.sock"},
            {"key": "cadvisor_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "cadvisor_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "0.49", "ansible_role": "cadvisor", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "requires": [{"product": "docker_ce", "min_version": "27.x", "reason": "Docker required for container metrics"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "golang",
        "display_name": "Go",
        "category": "runtime",
        "icon": "🐹",
        "description": "Go programming language runtime and toolchain",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "go_install_path", "label": "Install Path", "type": "text", "required": False, "default": "/usr/local/go"},
            {"key": "go_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "go_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "1.22", "ansible_role": "golang", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "1.23", "ansible_role": "golang", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "rust",
        "display_name": "Rust",
        "category": "runtime",
        "icon": "🦠",
        "description": "Rust programming language via rustup",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "rust_user", "label": "Install for User", "type": "text", "required": False, "default": "root", "placeholder": "User who gets rustup (root or app user)"},
            {"key": "rust_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "rust_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "1.80", "ansible_role": "rust", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "1.82", "ansible_role": "rust", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "docker_ce",
        "display_name": "Docker CE",
        "category": "runtime",
        "icon": "🐳",
        "description": "Docker Engine (Community Edition) for running containers",
        "default_ports": [2376],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "docker_users", "label": "Users in docker group (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "deploy,appuser"},
            {"key": "docker_daemon_json", "label": "daemon.json overrides", "type": "textarea", "required": False, "default": "", "placeholder": '{"log-driver": "json-file", "log-opts": {"max-size": "10m"}}'},
            {"key": "docker_tls_enabled", "label": "Enable TLS on the Docker API", "type": "checkbox", "required": False, "default": True},
            {"key": "docker_tls_port", "label": "TLS API Port", "type": "number", "required": False, "default": 2376},
            {"key": "docker_compose", "label": "Install Docker Compose", "type": "checkbox", "required": False, "default": True},
            {"key": "docker_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "docker_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "27.x", "ansible_role": "docker_ce", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "gcc",
        "display_name": "GCC / Build Essentials",
        "category": "devtools",
        "icon": "🔧",
        "description": "C/C++ compiler toolchain and common build tools",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "gcc_extras", "label": "Extra Packages (comma-separated)", "type": "text", "required": False, "default": "cmake,make,gdb", "placeholder": "cmake, make, gdb, valgrind, pkg-config, autoconf"},
            {"key": "gcc_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "gcc_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "13", "ansible_role": "gcc", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "14", "ansible_role": "gcc", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "24.04"}, {"os": "rhel", "min": "9"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "haproxy",
        "display_name": "HAProxy",
        "category": "networking",
        "icon": "🔀",
        "description": "High-performance TCP/HTTP load balancer and reverse proxy",
        "default_ports": [80, 443, 8404],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "haproxy_stats_port", "label": "Stats Port", "type": "number", "required": False, "default": 8404},
            {"key": "haproxy_stats_user", "label": "Stats Username", "type": "text", "required": False, "default": "admin"},
            {"key": "haproxy_stats_password", "label": "Stats Password", "type": "password", "required": False, "default": ""},
            {"key": "haproxy_tls_port", "label": "Default TLS Port", "type": "number", "required": False, "default": 443,
             "placeholder": "Used for the built-in TLS-terminating frontend when no custom Frontends are defined below"},
            {"key": "haproxy_frontends", "label": "Frontends", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Name", "type": "text", "required": True, "placeholder": "http_front"},
                 {"key": "bind", "label": "Bind", "type": "text", "required": True, "placeholder": "*:443 ssl crt /etc/haproxy/ssl/combined.pem"},
                 {"key": "mode", "label": "Mode", "type": "select", "required": False, "default": "http", "options": ["http", "tcp"]},
                 {"key": "default_backend", "label": "Default Backend", "type": "text", "required": True, "placeholder": "app_servers"},
             ]},
            {"key": "haproxy_backends", "label": "Backends", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Name", "type": "text", "required": True, "placeholder": "app_servers"},
                 {"key": "mode", "label": "Mode", "type": "select", "required": False, "default": "http", "options": ["http", "tcp"]},
                 {"key": "balance", "label": "Balance", "type": "select", "required": False, "default": "roundrobin", "options": ["roundrobin", "leastconn", "source"]},
                 {"key": "servers", "label": "Servers (name:host:port, comma-sep)", "type": "text", "required": True, "placeholder": "web1:10.0.0.1:8000, web2:10.0.0.2:8000"},
             ]},
            {"key": "haproxy_tls_enabled", "label": "Enable TLS", "type": "checkbox", "required": False, "default": True},
            {"key": "haproxy_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "haproxy_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "haproxy_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": ""},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "2.8", "ansible_role": "haproxy", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "3.0", "ansible_role": "haproxy", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "24.04"}, {"os": "rhel", "min": "9"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "ufw",
        "display_name": "UFW (Firewall)",
        "category": "networking",
        "icon": "🛡️",
        "description": "Uncomplicated Firewall — iptables frontend with simple rule management",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "ufw_default_incoming", "label": "Default Incoming", "type": "select", "required": False, "default": "deny", "options": ["deny", "allow", "reject"]},
            {"key": "ufw_default_outgoing", "label": "Default Outgoing", "type": "select", "required": False, "default": "allow", "options": ["allow", "deny", "reject"]},
            {"key": "ufw_rules", "label": "Rules", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "port", "label": "Port", "type": "text", "required": True, "placeholder": "22 or 80,443"},
                 {"key": "proto", "label": "Protocol", "type": "select", "required": False, "default": "tcp", "options": ["tcp", "udp", "any"]},
                 {"key": "from", "label": "From (source)", "type": "text", "required": False, "default": "any", "placeholder": "any or 192.168.0.0/24"},
                 {"key": "action", "label": "Action", "type": "select", "required": False, "default": "allow", "options": ["allow", "deny", "reject", "limit"]},
             ]},
            {"key": "ufw_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "ufw_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "latest", "ansible_role": "ufw", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "fail2ban",
        "display_name": "Fail2Ban",
        "category": "networking",
        "icon": "🚫",
        "description": "Intrusion prevention — bans IPs after repeated auth failures",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "fail2ban_bantime", "label": "Default Ban Time", "type": "text", "required": False, "default": "1h", "placeholder": "1h, 30m, 1d"},
            {"key": "fail2ban_findtime", "label": "Find Time", "type": "text", "required": False, "default": "10m"},
            {"key": "fail2ban_maxretry", "label": "Default Max Retry", "type": "number", "required": False, "default": 5},
            {"key": "fail2ban_jails", "label": "Jails", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Jail Name", "type": "text", "required": True, "placeholder": "sshd"},
                 {"key": "enabled", "label": "Enabled", "type": "checkbox", "required": False, "default": True},
                 {"key": "port", "label": "Port", "type": "text", "required": False, "default": "ssh", "placeholder": "ssh or 22 or 80,443"},
                 {"key": "filter", "label": "Filter", "type": "text", "required": False, "default": "", "placeholder": "sshd (blank = same as name)"},
                 {"key": "maxretry", "label": "Max Retry", "type": "number", "required": False, "default": 5},
                 {"key": "bantime", "label": "Ban Time", "type": "text", "required": False, "default": "", "placeholder": "Blank = use default"},
             ]},
            {"key": "fail2ban_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "fail2ban_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "1.1", "ansible_role": "fail2ban", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "wireguard",
        "display_name": "WireGuard",
        "category": "networking",
        "icon": "🔐",
        "description": "Modern VPN tunnel — fast, simple, kernel-level encryption",
        "default_ports": [51820],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "wireguard_address", "label": "Interface Address", "type": "text", "required": True, "placeholder": "10.0.0.1/24"},
            {"key": "wireguard_listen_port", "label": "Listen Port", "type": "number", "required": False, "default": 51820},
            {"key": "wireguard_post_up", "label": "PostUp Command", "type": "text", "required": False, "default": "", "placeholder": "iptables -A FORWARD -i wg0 -j ACCEPT"},
            {"key": "wireguard_post_down", "label": "PostDown Command", "type": "text", "required": False, "default": "", "placeholder": "iptables -D FORWARD -i wg0 -j ACCEPT"},
            {"key": "wireguard_peers", "label": "Peers", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Peer Name", "type": "text", "required": True, "placeholder": "client-1"},
                 {"key": "public_key", "label": "Public Key", "type": "text", "required": True},
                 {"key": "allowed_ips", "label": "Allowed IPs", "type": "text", "required": True, "placeholder": "10.0.0.2/32"},
                 {"key": "endpoint", "label": "Endpoint", "type": "text", "required": False, "default": "", "placeholder": "peer.example.com:51820"},
             ]},
            {"key": "wireguard_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "wireguard_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "latest", "ansible_role": "wireguard", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "redis",
        "display_name": "Redis",
        "category": "database",
        "icon": "🔴",
        "description": "In-memory data store for caching, sessions, and messaging",
        "default_ports": [6379],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "redis_port", "label": "Port", "type": "number", "required": False, "default": 6379},
            {"key": "redis_password", "label": "Password (requirepass)", "type": "password", "required": False, "default": "", "placeholder": "Blank = no auth"},
            {"key": "redis_bind", "label": "Bind Address", "type": "text", "required": False, "default": "0.0.0.0", "placeholder": "0.0.0.0 or 127.0.0.1"},
            {"key": "redis_maxmemory", "label": "Max Memory", "type": "text", "required": False, "default": "256mb", "placeholder": "e.g. 256mb, 1gb"},
            {"key": "redis_maxmemory_policy", "label": "Eviction Policy", "type": "select", "required": False, "default": "allkeys-lru", "options": ["noeviction", "allkeys-lru", "volatile-lru", "allkeys-random", "volatile-random", "volatile-ttl"]},
            {"key": "redis_tls_enabled", "label": "Enable TLS", "type": "checkbox", "required": False, "default": True},
            {"key": "redis_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "redis_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "redis_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": ""},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "7.2", "ansible_role": "redis", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "7.4", "ansible_role": "redis", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "postgresql",
        "display_name": "PostgreSQL",
        "category": "database",
        "icon": "🐘",
        "description": "Advanced open-source relational database with TLS support",
        "default_ports": [5432],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "pg_port", "label": "Port", "type": "number", "required": False, "default": 5432},
            {"key": "pg_superuser_password", "label": "Superuser (postgres) Password", "type": "password", "required": True, "default": ""},
            {"key": "pg_listen_addresses", "label": "Listen Addresses", "type": "text", "required": False, "default": "*", "placeholder": "* or 0.0.0.0 or localhost"},
            {"key": "pg_databases", "label": "Databases", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Database Name", "type": "text", "required": True},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "postgres"},
             ]},
            {"key": "pg_users", "label": "Users", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Username", "type": "text", "required": True},
                 {"key": "password", "label": "Password", "type": "password", "required": True},
                 {"key": "priv", "label": "Privileges", "type": "text", "required": False, "default": "", "placeholder": "CREATEDB,LOGIN"},
             ]},
            {"key": "pg_hba_entries", "label": "pg_hba.conf Entries", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "type", "label": "Type", "type": "select", "required": True, "default": "host", "options": ["local", "host", "hostssl"]},
                 {"key": "database", "label": "Database", "type": "text", "required": False, "default": "all"},
                 {"key": "user", "label": "User", "type": "text", "required": False, "default": "all"},
                 {"key": "address", "label": "Address", "type": "text", "required": False, "default": "0.0.0.0/0"},
                 {"key": "method", "label": "Method", "type": "select", "required": False, "default": "scram-sha-256", "options": ["scram-sha-256", "md5", "trust", "reject", "cert"]},
             ]},
            {"key": "pg_tls_enabled", "label": "Enable TLS", "type": "checkbox", "required": False, "default": True},
            {"key": "pg_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "pg_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "pg_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": ""},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "15", "ansible_role": "postgresql", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "16", "ansible_role": "postgresql", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "17", "ansible_role": "postgresql", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "24.04"}, {"os": "rhel", "min": "9"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "mongodb",
        "display_name": "MongoDB",
        "category": "database",
        "icon": "🍃",
        "description": "Document database with optional TLS",
        "default_ports": [27017],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "mongo_port", "label": "Port", "type": "number", "required": False, "default": 27017},
            {"key": "mongo_bind_ip", "label": "Bind IP", "type": "text", "required": False, "default": "0.0.0.0"},
            {"key": "mongo_admin_password", "label": "Admin Password", "type": "password", "required": True, "default": ""},
            {"key": "mongo_databases", "label": "Databases", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Database Name", "type": "text", "required": True},
             ]},
            {"key": "mongo_users", "label": "Users", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Username", "type": "text", "required": True},
                 {"key": "password", "label": "Password", "type": "password", "required": True},
                 {"key": "database", "label": "Database", "type": "text", "required": True, "placeholder": "admin"},
                 {"key": "roles", "label": "Roles", "type": "text", "required": False, "default": "readWrite", "placeholder": "readWrite, dbAdmin"},
             ]},
            {"key": "mongo_tls_enabled", "label": "Enable TLS", "type": "checkbox", "required": False, "default": True},
            {"key": "mongo_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "mongo_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "mongo_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": ""},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "7.0", "ansible_role": "mongodb", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "8.0", "ansible_role": "mongodb", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "memcached",
        "display_name": "Memcached",
        "category": "database",
        "icon": "⚡",
        "description": "High-performance distributed memory caching system",
        "default_ports": [11211],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "memcached_port", "label": "Port", "type": "number", "required": False, "default": 11211},
            {"key": "memcached_memory_mb", "label": "Memory (MB)", "type": "number", "required": False, "default": 64},
            {"key": "memcached_listen", "label": "Listen Address", "type": "text", "required": False, "default": "0.0.0.0"},
            {"key": "memcached_max_connections", "label": "Max Connections", "type": "number", "required": False, "default": 1024},
            {"key": "memcached_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "memcached_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "1.6", "ansible_role": "memcached", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "chrony",
        "display_name": "Chrony (NTP)",
        "category": "utility",
        "icon": "🕐",
        "description": "NTP time synchronisation (critical for TLS cert validation)",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "chrony_ntp_servers", "label": "NTP Servers", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "server", "label": "Server", "type": "text", "required": True, "placeholder": "pool.ntp.org"},
                 {"key": "options", "label": "Options", "type": "text", "required": False, "default": "iburst"},
             ]},
            {"key": "chrony_allow_networks", "label": "Allow Networks (serve time to)", "type": "text", "required": False, "default": "", "placeholder": "192.168.0.0/16 (blank = client only)"},
            {"key": "chrony_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "chrony_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "4.x", "ansible_role": "chrony", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "rsyslog",
        "display_name": "rsyslog",
        "category": "utility",
        "icon": "📋",
        "description": "System logging with optional remote forwarding",
        "default_ports": [514],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "rsyslog_remote_host", "label": "Remote Log Host", "type": "text", "required": False, "default": "", "placeholder": "logserver.internal"},
            {"key": "rsyslog_remote_port", "label": "Remote Port", "type": "number", "required": False, "default": 514},
            {"key": "rsyslog_protocol", "label": "Protocol", "type": "select", "required": False, "default": "tcp", "options": ["tcp", "udp"]},
            {"key": "rsyslog_extra_rules", "label": "Extra Rules", "type": "textarea", "required": False, "default": "", "placeholder": "Additional rsyslog.conf rules"},
            {"key": "rsyslog_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "rsyslog_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "8.x", "ansible_role": "rsyslog", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "certbot",
        "display_name": "Certbot",
        "category": "utility",
        "icon": "🔒",
        "description": "Let's Encrypt ACME client for public TLS certificates",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "certbot_email", "label": "Email", "type": "text", "required": True, "placeholder": "admin@example.com"},
            {"key": "certbot_domains", "label": "Domains (comma-separated)", "type": "text", "required": True, "placeholder": "example.com, www.example.com"},
            {"key": "certbot_method", "label": "Validation Method", "type": "select", "required": False, "default": "webroot", "options": ["webroot", "standalone", "dns"]},
            {"key": "certbot_webroot", "label": "Webroot Path", "type": "text", "required": False, "default": "/var/www/html", "placeholder": "/var/www/html (webroot method only)"},
            {"key": "certbot_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "certbot_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "2.x", "ansible_role": "certbot", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "git",
        "display_name": "Git",
        "category": "devtools",
        "icon": "🔀",
        "description": "Distributed version control system",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "git_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "git_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "2.43", "ansible_role": "git", "is_latest": False,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
            {"version": "2.45", "ansible_role": "git", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "24.04"}, {"os": "rhel", "min": "9"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "cronjobs",
        "display_name": "Cron Jobs",
        "category": "utility",
        "icon": "⏰",
        "description": "Scheduled task definitions (log rotation, backups, health checks)",
        "default_ports": [],
        "cert_requirements": {},
        "dependencies": [],
        "config_schema": [
            {"key": "cron_jobs", "label": "Jobs", "type": "list", "required": True, "default": [],
             "item_schema": [
                 {"key": "name", "label": "Name", "type": "text", "required": True, "placeholder": "Rotate logs"},
                 {"key": "minute", "label": "Minute", "type": "text", "required": False, "default": "*"},
                 {"key": "hour", "label": "Hour", "type": "text", "required": False, "default": "*"},
                 {"key": "day", "label": "Day", "type": "text", "required": False, "default": "*"},
                 {"key": "month", "label": "Month", "type": "text", "required": False, "default": "*"},
                 {"key": "weekday", "label": "Weekday", "type": "text", "required": False, "default": "*"},
                 {"key": "job", "label": "Command", "type": "text", "required": True, "placeholder": "/usr/sbin/logrotate /etc/logrotate.conf"},
                 {"key": "user", "label": "User", "type": "text", "required": False, "default": "root"},
             ]},
            {"key": "cron_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": ""},
            {"key": "cron_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
        ],
        "versions": [
            {"version": "latest", "ansible_role": "cronjobs", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    {
        "name": "apache",
        "display_name": "Apache HTTPD",
        "category": "web_server",
        "icon": "🪶",
        "description": "Apache HTTP Server with mod_ssl",
        "default_ports": [80, 443],
        "cert_requirements": {"server_tls": True, "client_mtls": False},
        "dependencies": [],
        "config_schema": [
            {"key": "apache_server_name", "label": "Server Name", "type": "text", "required": False, "default": "_", "placeholder": "e.g. app.example.com"},
            {"key": "apache_listen_port", "label": "TLS Listen Port", "type": "number", "required": False, "default": 443},
            {"key": "apache_document_root", "label": "Document Root", "type": "text", "required": False, "default": "/var/www/html"},
            {"key": "apache_sudo_users", "label": "Sudo Users (comma-separated)", "type": "text", "required": False, "default": "", "placeholder": "e.g. deploy,appuser"},
            {"key": "apache_sudo_nopasswd", "label": "Passwordless Sudo", "type": "checkbox", "required": False, "default": False},
            {"key": "apache_file_deployments", "label": "File Deployments", "type": "list", "required": False, "default": [],
             "item_schema": [
                 {"key": "path", "label": "Destination Path", "type": "text", "required": True, "placeholder": "/opt/app/config/settings.yml"},
                 {"key": "content", "label": "File Content", "type": "textarea", "required": False, "default": "", "placeholder": "Paste file content (or use upload)"},
                 {"key": "upload", "label": "Upload File", "type": "file", "required": False},
                 {"key": "mode", "label": "Permissions", "type": "text", "required": False, "default": "0644", "placeholder": "0644"},
                 {"key": "owner", "label": "Owner", "type": "text", "required": False, "default": "root"},
             ]},
        ],
        "versions": [
            {"version": "2.4", "ansible_role": "apache", "is_latest": True,
             "supported_os": [{"os": "ubuntu", "min": "22.04"}, {"os": "rhel", "min": "8"}],
             "default_vars": {}},
        ],
    },
    # --- AWS RDS / Aurora managed database products ---
    {
        "name": "mysql-rds",
        "display_name": "MySQL (RDS)",
        "category": "database",
        "icon": "🗄️",
        "description": "AWS RDS MySQL 8.0 — managed single instance. AWS handles patching, backups, and failover. TLS enforced via AWS RDS CA.",
        "default_ports": [3306],
        "cert_requirements": {},
        "dependencies": [],
        "deployment_targets": ["rds"],
        "versions": [
            {"version": "8.0", "ansible_role": "", "is_latest": True,
             "supported_os": [],
             "default_vars": {},
             "aws_defaults": {
                 "db_instance_class": "db.t3.medium",
                 "multi_az": False,
                 "skip_final_snapshot": True,
                 "db_backup_retention_days": 7,
                 "db_allocated_storage": 20,
             }},
        ],
    },
    {
        "name": "aurora-mysql",
        "display_name": "MySQL (Aurora)",
        "category": "database",
        "icon": "🗄️",
        "description": "AWS Aurora MySQL 3.x (MySQL 8.0 compatible) — managed cluster. Writer + optional reader instances. Automatic failover, auto-scaling storage.",
        "default_ports": [3306],
        "cert_requirements": {},
        "dependencies": [],
        "deployment_targets": ["rds"],
        "versions": [
            {"version": "3.x", "ansible_role": "", "is_latest": True,
             "supported_os": [],
             "default_vars": {},
             "aws_defaults": {
                 "db_instance_class": "db.t3.medium",
                 "aurora_instance_count": 1,
                 "skip_final_snapshot": True,
                 "db_backup_retention_days": 7,
                 "enable_performance_insights": False,
             }},
        ],
    },
    {
        "name": "postgres-rds",
        "display_name": "PostgreSQL (RDS)",
        "category": "database",
        "icon": "🐘",
        "description": "AWS RDS PostgreSQL 16 — managed single instance.",
        "default_ports": [5432],
        "cert_requirements": {},
        "dependencies": [],
        "deployment_targets": ["rds"],
        "versions": [
            {"version": "16", "ansible_role": "", "is_latest": True,
             "supported_os": [],
             "default_vars": {},
             "aws_defaults": {
                 "db_instance_class": "db.t3.medium",
                 "multi_az": False,
                 "skip_final_snapshot": True,
                 "db_backup_retention_days": 7,
                 "db_allocated_storage": 20,
             }},
        ],
    },
    {
        "name": "aurora-postgres",
        "display_name": "PostgreSQL (Aurora)",
        "category": "database",
        "icon": "🐘",
        "description": "AWS Aurora PostgreSQL 16 — managed cluster.",
        "default_ports": [5432],
        "cert_requirements": {},
        "dependencies": [],
        "deployment_targets": ["rds"],
        "versions": [
            {"version": "16", "ansible_role": "", "is_latest": True,
             "supported_os": [],
             "default_vars": {},
             "aws_defaults": {
                 "db_instance_class": "db.t3.medium",
                 "aurora_instance_count": 1,
                 "skip_final_snapshot": True,
                 "db_backup_retention_days": 7,
                 "enable_performance_insights": False,
             }},
        ],
    },
]


async def seed_catalogue(db: AsyncSession) -> dict[str, int]:
    """Insert built-in products not yet present, AND sync already-seeded
    ones (and their versions) to match SEED_PRODUCTS' current definition.

    Originally insert-only ("if a product with this name exists, skip it
    entirely") — which meant any change to a builtin product's code (e.g. a
    new config_schema field, like Keystone's extra-pip-packages field) never
    reached an already-seeded database no matter how many times this ran or
    the app was rebuilt: the catalogue the UI/build actually reads from is
    the DB row, seeded once, not the live SEED_PRODUCTS list. Now an
    existing product/version's mutable fields are updated in place (same
    row, same id — nothing that already references it by id breaks), and a
    version present in SEED_PRODUCTS but missing from an existing product is
    added. Only a brand-new product (by name) counts toward "added";
    everything else that actually changed counts toward "updated"."""
    added = 0
    updated = 0
    for pdata in SEED_PRODUCTS:
        existing_result = await db.execute(select(BMProduct).where(BMProduct.name == pdata["name"]))
        product = existing_result.scalar_one_or_none()

        if not product:
            product = BMProduct(
                id=str(uuid.uuid4()),
                name=pdata["name"],
                display_name=pdata["display_name"],
                category=pdata["category"],
                icon=pdata["icon"],
                description=pdata["description"],
                default_ports=json.dumps(pdata["default_ports"]),
                cert_requirements=json.dumps(pdata["cert_requirements"]),
                dependencies=json.dumps(pdata["dependencies"]),
                deployment_targets=json.dumps(pdata.get("deployment_targets", ["ec2"])),
                is_builtin=True,
            )
            db.add(product)
            await db.flush()  # assign product.id before versions reference it
            added += 1
        else:
            product.display_name = pdata["display_name"]
            product.category = pdata["category"]
            product.icon = pdata["icon"]
            product.description = pdata["description"]
            product.default_ports = json.dumps(pdata["default_ports"])
            product.cert_requirements = json.dumps(pdata["cert_requirements"])
            product.dependencies = json.dumps(pdata["dependencies"])
            product.deployment_targets = json.dumps(pdata.get("deployment_targets", ["ec2"]))
            updated += 1

        existing_versions_result = await db.execute(
            select(BMProductVersion).where(BMProductVersion.product_id == product.id)
        )
        versions_by_number = {v.version: v for v in existing_versions_result.scalars().all()}

        for vdata in pdata["versions"]:
            aws_def = vdata.get("aws_defaults")
            pv = versions_by_number.get(vdata["version"])
            if not pv:
                db.add(BMProductVersion(
                    id=str(uuid.uuid4()),
                    product_id=product.id,
                    version=vdata["version"],
                    ansible_role=vdata.get("ansible_role", ""),
                    default_vars=json.dumps(vdata.get("default_vars", {})),
                    config_schema=json.dumps(pdata.get("config_schema", [])),
                    supported_os=json.dumps(vdata.get("supported_os", [])),
                    conflicts_with=json.dumps(vdata.get("conflicts_with", [])),
                    requires=json.dumps(vdata.get("requires", [])),
                    eol_date=vdata.get("eol_date"),
                    is_latest=vdata.get("is_latest", False),
                    aws_defaults=json.dumps(aws_def) if aws_def is not None else None,
                ))
            else:
                pv.ansible_role = vdata.get("ansible_role", "")
                pv.default_vars = json.dumps(vdata.get("default_vars", {}))
                pv.config_schema = json.dumps(pdata.get("config_schema", []))
                pv.supported_os = json.dumps(vdata.get("supported_os", []))
                pv.conflicts_with = json.dumps(vdata.get("conflicts_with", []))
                pv.requires = json.dumps(vdata.get("requires", []))
                pv.eol_date = vdata.get("eol_date")
                pv.is_latest = vdata.get("is_latest", False)
                pv.aws_defaults = json.dumps(aws_def) if aws_def is not None else None

    await db.commit()
    return {"products_added": added, "products_updated": updated}


# ============================================================
# AWS CATALOGUE HELPERS
# ============================================================


def normalise_db_block(db_block: dict) -> dict:
    """Accept old engine string format and normalise to product ID format.

    Old: {"engine": "rds_mysql", ...}
    New: {"product": "mysql-rds", ...}
    Both are accepted; old format is transparently converted.
    """
    if "engine" in db_block and "product" not in db_block:
        product_id = ENGINE_COMPAT_MAP.get(db_block["engine"])
        if product_id:
            return {**db_block, "product": product_id}
    return db_block


def validate_aws_products(spec: dict, product_map: dict[str, list[str]]) -> list[str]:
    """Validate that RDS-only products are not placed in host product lists.

    product_map: {product_name: deployment_targets} — pre-loaded by caller.
    Returns a list of error strings (empty = valid).
    """
    errors = []
    is_aws = bool(spec.get("aws"))
    for host in spec.get("hosts", []):
        for p in host.get("products", []):
            targets = product_map.get(p.get("product", ""), ["ec2"])
            if "rds" in targets and "ec2" not in targets:
                if is_aws:
                    errors.append(
                        f"Product '{p['product']}' is RDS-only and cannot be assigned to host "
                        f"'{host.get('role', '?')}'. Add it to the aws.database section instead."
                    )
                else:
                    errors.append(
                        f"Product '{p['product']}' requires AWS (deployment_targets: rds) "
                        f"but this template has no aws block."
                    )
    return errors


async def get_products_by_target(
    db: AsyncSession,
    deployment_target: str | None = None,
) -> list[BMProduct]:
    """Return products, optionally filtered to those supporting a given deployment target."""
    result = await db.execute(select(BMProduct).options(selectinload(BMProduct.versions)))
    products = result.scalars().all()
    if not deployment_target:
        return list(products)
    # Filter in Python — SQLite JSON_EACH support is version-dependent
    return [
        p for p in products
        if deployment_target in json.loads(p.deployment_targets or '["ec2"]')
    ]


# ============================================================
# COMPATIBILITY CHECKER
# ============================================================


def _version_gte(actual: str, minimum: str) -> bool:
    """Compare version strings (e.g. '24.04' >= '22.04')."""
    try:
        a_parts = [int(x) for x in actual.split(".")]
        m_parts = [int(x) for x in minimum.split(".")]
        return a_parts >= m_parts
    except (ValueError, AttributeError):
        return actual >= minimum


async def find_host_conflicts(db: AsyncSession, host_product_names: list[tuple[str, set[str]]]) -> list[dict]:
    """Shared conflict-checking core.

    host_product_names: [(role, {product_name, ...}), ...] — one entry per
    host, with the set of product names selected for *that* host.

    Checked per host, not across the whole template/selection set: two
    products declaring conflicts_with each other (e.g. Adminer and Apache
    both bind their own web server to port 80) are only a real problem if
    they're provisioned onto the same machine — confirmed via a live build
    where Adminer + Apache on the same host made nginx fail to start with
    "Address already in use". Checking across the whole template (the
    previous behaviour) would have produced a false-positive conflict for
    e.g. Adminer on host A and Apache on unrelated host B.

    Returns a list of {"role", "product", "conflicts_with", "reason"}
    violation dicts — empty if none.
    """
    all_names = {name for _, names in host_product_names for name in names}
    if not all_names:
        return []

    result = await db.execute(
        select(BMProductVersion).options(selectinload(BMProductVersion.product))
        .join(BMProduct).where(BMProduct.name.in_(all_names))
    )
    conflicts_by_name: dict[str, list[dict]] = {}
    for pv in result.scalars().all():
        c = json.loads(pv.conflicts_with) if pv.conflicts_with else []
        if c:
            conflicts_by_name.setdefault(pv.product.name, []).extend(c)

    violations = []
    seen = set()
    for role, names in host_product_names:
        for name in names:
            for c in conflicts_by_name.get(name, []):
                other = c.get("product")
                if other in names:
                    key = (role, frozenset({name, other}))
                    if key in seen:
                        continue
                    seen.add(key)
                    violations.append({
                        "role": role, "product": name,
                        "conflicts_with": other, "reason": c.get("reason", ""),
                    })
    return violations


async def check_template_spec_conflicts(db: AsyncSession, spec: dict) -> list[str]:
    """Conflict check for an already-built template spec (spec["hosts"][i]
    has "role" and "products": [{"product": name, ...}]) — used at
    template-save time so a conflicting combination can't be persisted via
    any save path (POST /catalogue/build-template, POST /templates, PUT
    /templates/{id}, POST /templates/import), not just caught by the
    Template Builder UI's advisory check-compatibility call, which a
    hand-crafted API request bypasses entirely. Returns human-readable
    error strings, empty if no conflicts."""
    host_product_names = [
        (h.get("role", ""), {p.get("product") for p in h.get("products", []) if p.get("product")})
        for h in spec.get("hosts", [])
    ]
    violations = await find_host_conflicts(db, host_product_names)
    return [
        f"Host '{v['role']}': {v['product']} conflicts with {v['conflicts_with']}"
        + (f" — {v['reason']}" if v["reason"] else "")
        for v in violations
    ]


async def check_compatibility(
    db: AsyncSession,
    base_os: str,
    base_os_version: str,
    hosts: list[dict],
) -> dict:
    """
    Validate product selections against OS and inter-product rules.
    hosts: [{"role": "host-01", "selections": [{"product_id": "...", "version_id": "..."}]}]
    Returns: {"valid": bool, "errors": [...], "warnings": [...], "auto_dependencies": [...]}

    Conflicts are hard errors (valid=False), not warnings — unlike OS-
    support/EOL issues, a declared conflicts_with pairing means the build
    will concretely fail (a service failing to bind its port), not just a
    soft compatibility caveat.
    """
    errors = []
    warnings = []
    auto_deps = []

    # Load all selected product versions across every host
    all_selections = [sel for h in hosts for sel in h.get("selections", [])]
    version_ids = [s["version_id"] for s in all_selections]
    result = await db.execute(
        select(BMProductVersion).options(selectinload(BMProductVersion.product))
        .where(BMProductVersion.id.in_(version_ids))
    )
    versions_by_id = {pv.id: pv for pv in result.scalars().all()}
    selected_versions = list(versions_by_id.values())
    selected_product_names = {pv.product.name for pv in selected_versions}

    for pv in selected_versions:
        product_label = f"{pv.product.display_name} {pv.version}"

        # 1. OS compatibility
        supported = json.loads(pv.supported_os) if pv.supported_os else []
        os_ok = False
        for entry in supported:
            if entry.get("os") == base_os:
                min_v = entry.get("min", "0")
                max_v = entry.get("max")
                if _version_gte(base_os_version, min_v):
                    if max_v is None or not _version_gte(base_os_version, str(float(max_v) + 0.01)):
                        os_ok = True
                break
        if supported and not os_ok:
            errors.append({
                "product": product_label,
                "level": "error",
                "message": f"Not supported on {base_os} {base_os_version}",
            })

        # 3. Dependencies
        requires = json.loads(pv.requires) if pv.requires else []
        for req in requires:
            req_name = req.get("product")
            if req_name and req_name not in selected_product_names:
                # Find the dependency in catalogue
                dep_result = await db.execute(
                    select(BMProductVersion).options(selectinload(BMProductVersion.product))
                    .join(BMProduct)
                    .where(BMProduct.name == req_name, BMProductVersion.is_latest == True)
                )
                dep_pv = dep_result.scalar_one_or_none()
                auto_deps.append({
                    "product": req_name,
                    "display_name": dep_pv.product.display_name if dep_pv else req_name,
                    "version": dep_pv.version if dep_pv else "latest",
                    "version_id": dep_pv.id if dep_pv else None,
                    "reason": req.get("reason", f"Required by {product_label}"),
                    "auto_add": True,
                })

        # 4. EOL warning
        if pv.eol_date:
            try:
                eol = date.fromisoformat(pv.eol_date)
                if eol <= date.today():
                    warnings.append({
                        "product": product_label,
                        "level": "warning",
                        "message": f"End of life: {pv.eol_date}",
                    })
                elif (eol - date.today()).days < 180:
                    warnings.append({
                        "product": product_label,
                        "level": "warning",
                        "message": f"Approaching EOL: {pv.eol_date}",
                    })
            except ValueError:
                pass

    # Also check product-level dependencies (from BMProduct.dependencies)
    for pv in selected_versions:
        product_deps = json.loads(pv.product.dependencies) if pv.product.dependencies else []
        for dep_name in product_deps:
            if dep_name not in selected_product_names:
                # Check if already in auto_deps
                if not any(d["product"] == dep_name for d in auto_deps):
                    dep_result = await db.execute(
                        select(BMProductVersion).options(selectinload(BMProductVersion.product))
                        .join(BMProduct)
                        .where(BMProduct.name == dep_name, BMProductVersion.is_latest == True)
                    )
                    dep_pv = dep_result.scalar_one_or_none()
                    auto_deps.append({
                        "product": dep_name,
                        "display_name": dep_pv.product.display_name if dep_pv else dep_name,
                        "version": dep_pv.version if dep_pv else "latest",
                        "version_id": dep_pv.id if dep_pv else None,
                        "reason": f"Required by {pv.product.display_name}",
                        "auto_add": True,
                    })

    # 2. Conflicts — checked per host (see find_host_conflicts docstring for why)
    host_product_names = [
        (h.get("role", ""), {versions_by_id[s["version_id"]].product.name
                              for s in h.get("selections", []) if s["version_id"] in versions_by_id})
        for h in hosts
    ]
    for v in await find_host_conflicts(db, host_product_names):
        errors.append({
            "product": v["product"],
            "level": "error",
            "message": f"On host '{v['role']}': conflicts with {v['conflicts_with']}" + (f" — {v['reason']}" if v["reason"] else ""),
        })

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "auto_dependencies": auto_deps,
    }


# ============================================================
# TEMPLATE BUILDER SERVICE
# ============================================================

async def build_template_spec(
    db: AsyncSession,
    base_os: str,
    base_os_version: str,
    hosts: list[dict],
    network: dict | None = None,
    certificates: dict | None = None,
    ansible_timeout_minutes: int = 30,
    aws: dict | None = None,
) -> dict:
    """
    Convert builder UI selections into a template spec.
    hosts: [{"role": "web-01", "products": [{"product_id": "...", "version_id": "...", "vars": {}}]}]
    """
    spec_hosts = []

    for h in hosts:
        products_out = []
        certs = set()

        for sel in h.get("products", []):
            # Look up product version
            result = await db.execute(
                select(BMProductVersion).options(selectinload(BMProductVersion.product))
                .where(BMProductVersion.id == sel["version_id"])
            )
            pv = result.scalar_one_or_none()
            if not pv:
                continue

            products_out.append({
                "product": pv.product.name,
                "version": pv.version,
                "vars": sel.get("vars", {}),
            })

            # Determine cert requirements
            cert_reqs = json.loads(pv.product.cert_requirements) if pv.product.cert_requirements else {}
            if cert_reqs.get("server_tls"):
                certs.add("server_tls")
            if cert_reqs.get("client_mtls"):
                certs.add("client_mtls")

        host_entry = {
            "role": h["role"],
            "hostname_pattern": "{{env_name}}-" + h["role"],
            "products": products_out,
            "certs": list(certs) if certs else ["server_tls"],
        }
        if h.get("inventory_host_id"):
            host_entry["inventory_host_id"] = h["inventory_host_id"]
        if h.get("ip"):
            host_entry["ip"] = h["ip"]

        if h.get("instance_type"):
            host_entry["instance_type"] = h["instance_type"]
        if h.get("root_volume_gb"):
            host_entry["root_volume_gb"] = h["root_volume_gb"]
        if h.get("az_index") is not None:
            host_entry["az_index"] = h["az_index"]

        spec_hosts.append(host_entry)

    spec: dict = {
        "base_os": base_os,
        "base_os_version": base_os_version,
        "hosts": spec_hosts,
        "certificates": certificates or {
            "key_algorithm": "RSA",
            "key_size": 2048,
            "validity_days": 365,
            "san_include_localhost": True,
        },
        "playbook_sequence": ["base-provision.yml", "products.yml", "health-check.yml"],
        "ansible_timeout_minutes": ansible_timeout_minutes,
    }
    if aws:
        spec["aws"] = aws
    elif network:
        # Only set a "network" block when the caller actually chose one
        # (e.g. {"pool_id": "..."} from the Template Builder's Inventory
        # pool dropdown). No block at all is a deliberate, meaningful
        # state — see environment_service.allocate_ips()'s own docstring —
        # it means every host role falls back to Docker auto-provisioning
        # instead of expecting a real, already-reachable machine. This
        # used to unconditionally default to a hardcoded, disconnected
        # 192.168.50.0/24 block regardless of what (if anything) the
        # caller passed, silently forcing every non-AWS template built
        # through this function into "expects a real host" mode.
        spec["network"] = network
    return spec
