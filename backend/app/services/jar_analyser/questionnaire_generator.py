"""Generate a structured diagnostic questionnaire from a JAR report.

Each section maps to a collection area the script covers.  Every item
contains:
  - id          : stable identifier used when submitting responses
  - label       : readable name
  - context     : why this matters (shown to the person filling it in)
  - command     : the exact shell command to run (or None for free-text)
  - input_type  : "command_output" | "file_content" | "yes_no" | "text"
  - required    : bool
"""
from __future__ import annotations

from typing import Any


def generate_questionnaire(report: dict, sub_dicts: list[dict]) -> list[dict]:
    """Return a list of sections, each containing a list of items."""

    version = (
        report.get("manifest", {}).get("Implementation-Version")
        or report.get("summary", {}).get("implementation_version")
        or "unknown"
    )
    title = report.get("manifest", {}).get("Implementation-Title") or "platform"

    # Filter out non-service JARs
    services = [
        s for s in sub_dicts
        if s.get("jar_type") not in ("nginx_installer", "monitoring_installer", "frontend_installer")
    ]

    sections: list[dict] = []

    # ── 1. System environment ────────────────────────────────────────────────
    sections.append({
        "id": "system",
        "title": "System Environment",
        "description": "Basic OS and JVM information to establish the deployment context.",
        "items": [
            {
                "id": "system.os_release",
                "label": "OS release",
                "context": "Identifies the Linux distribution and version.",
                "command": "cat /etc/os-release",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "system.uname",
                "label": "Kernel / architecture",
                "context": "Confirms 64-bit kernel and architecture.",
                "command": "uname -a",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "system.java_version",
                "label": "Java version",
                "context": f"{title} v{version} requires a specific JVM. This confirms what is installed.",
                "command": "java -version 2>&1",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "system.java_home",
                "label": "JAVA_HOME",
                "context": "Confirms which JDK the services will use at runtime.",
                "command": 'echo "JAVA_HOME=${JAVA_HOME:-not set}"',
                "input_type": "command_output",
                "required": False,
            },
            {
                "id": "system.disk",
                "label": "Disk usage",
                "context": "Low disk space causes startup failures and log truncation.",
                "command": "df -h",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "system.memory",
                "label": "Memory",
                "context": "Insufficient heap causes OutOfMemoryError on startup.",
                "command": "free -m",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "system.listening_ports",
                "label": "Listening ports",
                "context": "Confirms which services are actually bound and listening.",
                "command": "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "system.failed_units",
                "label": "Failed systemd units",
                "context": "Quickly surfaces any services that have crashed.",
                "command": "systemctl list-units --state=failed",
                "input_type": "command_output",
                "required": False,
            },
        ],
    })

    # ── 2. Per-service sections ──────────────────────────────────────────────
    for sub in services:
        svc = sub.get("service_name") or sub.get("filename", "service")
        port = sub.get("declared_port")
        install_path = sub.get("install_path") or f"/opt/{svc}"
        cfgs = sub.get("config_files", [])

        # Derive SSL paths
        ssl_keys = ("keystore", "truststore", "ssl.key-store", "ssl.trust-store",
                    "javax.net.ssl.keyStore", "javax.net.ssl.trustStore")
        ssl_paths: list[str] = []
        db_url: str | None = None
        rmq_host: str | None = None
        rmq_port: str = "5672"

        for cfg in cfgs:
            for k in cfg.get("keys", []):
                key = (k.get("key") or "").lower()
                val = k.get("value") or ""
                if val.startswith("${"):
                    continue
                if any(s in key for s in ssl_keys) and val and ("/" in val or val.endswith((".jks", ".p12", ".pem", ".crt"))):
                    ssl_paths.append(val)
                if "datasource.url" in key and not db_url:
                    db_url = val
                if "rabbitmq.host" in key and not rmq_host:
                    rmq_host = val
                if "rabbitmq.port" in key and val.isdigit():
                    rmq_port = val

        ssl_paths = list(dict.fromkeys(ssl_paths))[:4]

        items: list[dict] = []

        # Service status
        items.append({
            "id": f"{svc}.status",
            "label": f"{svc} — service status",
            "context": f"Confirms whether {svc} is running and shows recent state transitions.",
            "command": f"systemctl status {svc} --no-pager -l",
            "input_type": "command_output",
            "required": True,
        })

        # Journal / logs
        items.append({
            "id": f"{svc}.journal",
            "label": f"{svc} — recent logs (last 200 lines)",
            "context": "The most recent log output is the primary source of startup errors and SSL handshake failures.",
            "command": f"journalctl -u {svc} -n 200 --no-pager 2>/dev/null || tail -n 200 {install_path}/logs/*.log 2>/dev/null",
            "input_type": "command_output",
            "required": True,
        })

        # Config file
        items.append({
            "id": f"{svc}.config",
            "label": f"{svc} — application config",
            "context": "The live config file reveals unresolved placeholders, wrong DB URLs, and SSL paths.",
            "command": f"cat {install_path}/config/application.properties 2>/dev/null || cat {install_path}/config/application.yml 2>/dev/null || cat {install_path}/application.properties 2>/dev/null",
            "input_type": "command_output",
            "required": True,
        })

        # Port check
        if port:
            items.append({
                "id": f"{svc}.port",
                "label": f"{svc} — port {port} reachability",
                "context": f"Confirms the service is accepting connections on its declared port {port}.",
                "command": f"(echo >/dev/tcp/localhost/{port}) 2>/dev/null && echo OPEN || echo CLOSED",
                "input_type": "command_output",
                "required": True,
            })

        # SSL cert metadata
        for ssl_path in ssl_paths:
            if ssl_path.endswith((".jks", ".p12", ".pfx")):
                cmd = f"keytool -list -keystore {ssl_path} -storepass changeit -noprompt 2>/dev/null || keytool -list -keystore {ssl_path} -storepass '' -noprompt 2>/dev/null"
                label = f"{svc} — keystore contents ({ssl_path})"
                ctx = f"Lists aliases and expiry dates in the keystore at {ssl_path}. Expired or missing entries cause SSL handshake failures."
            else:
                cmd = f"openssl x509 -in {ssl_path} -noout -text 2>/dev/null | grep -E 'Subject:|Issuer:|Not Before:|Not After:|DNS:'"
                label = f"{svc} — certificate info ({ssl_path})"
                ctx = f"Shows subject, issuer, and expiry for the certificate at {ssl_path}."
            items.append({
                "id": f"{svc}.cert.{ssl_path.replace('/', '_').lstrip('_')}",
                "label": label,
                "context": ctx,
                "command": cmd,
                "input_type": "command_output",
                "required": False,
            })

        # DB connectivity
        if db_url:
            items.append({
                "id": f"{svc}.db_port",
                "label": f"{svc} — database connectivity",
                "context": f"Checks whether the database at {db_url} is reachable from this host.",
                "command": f"# DB URL: {db_url}\n# Extract host/port and test:\nDB_HOST=$(echo '{db_url}' | sed 's|.*://||;s|[:/].*||')\nDB_PORT=$(echo '{db_url}' | grep -oE ':[0-9]{{4,5}}/' | tr -d ':/' || echo 3306)\n(echo >/dev/tcp/$DB_HOST/$DB_PORT) 2>/dev/null && echo OPEN || echo CLOSED",
                "input_type": "command_output",
                "required": True,
            })

        sections.append({
            "id": f"service.{svc}",
            "title": f"Service: {svc}",
            "description": f"Logs, config, and connectivity for {svc}" + (f" (port {port})" if port else "") + ".",
            "items": items,
        })

    # ── 3. RabbitMQ (if any service uses it) ────────────────────────────────
    rmq_hosts = set()
    for sub in services:
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                key = (k.get("key") or "").lower()
                val = k.get("value") or ""
                if "rabbitmq.host" in key and val and not val.startswith("${"):
                    rmq_hosts.add(val)

    if rmq_hosts:
        rmq_h = next(iter(rmq_hosts))
        sections.append({
            "id": "rabbitmq",
            "title": "RabbitMQ",
            "description": "Connectivity and broker health for the RabbitMQ instance used by this platform.",
            "items": [
                {
                    "id": "rabbitmq.port",
                    "label": "AMQP port reachability",
                    "context": f"Checks whether RabbitMQ AMQP port is open on {rmq_h}.",
                    "command": f"(echo >/dev/tcp/{rmq_h}/5672) 2>/dev/null && echo OPEN || echo CLOSED",
                    "input_type": "command_output",
                    "required": True,
                },
                {
                    "id": "rabbitmq.management_api",
                    "label": "RabbitMQ management API overview",
                    "context": "Returns broker version, node name, and message stats. Requires the management plugin to be enabled.",
                    "command": f"curl -s http://{rmq_h}:15672/api/overview 2>/dev/null || echo 'management API not accessible'",
                    "input_type": "command_output",
                    "required": False,
                },
            ],
        })

    # ── 4. JVM cacerts ───────────────────────────────────────────────────────
    sections.append({
        "id": "jvm_cacerts",
        "title": "JVM Trust Store (cacerts)",
        "description": "The JVM cacerts file must contain the CA that signed your service certificates. Missing entries cause PKIX path building failures.",
        "items": [
            {
                "id": "jvm_cacerts.list",
                "label": "JVM cacerts — alias list",
                "context": "Lists all trusted CAs in the JVM default trust store. Look for your internal CA alias.",
                "command": 'JAVA_HOME_DIR=$(java -XshowSettings:all -version 2>&1 | grep "java.home" | awk \'{print $3}\' | head -1)\nCACERTS="${JAVA_HOME_DIR}/lib/security/cacerts"\n[ -f "$CACERTS" ] || CACERTS="${JAVA_HOME_DIR}/../lib/security/cacerts"\nkeytool -list -keystore "$CACERTS" -storepass changeit -noprompt 2>/dev/null | head -60',
                "input_type": "command_output",
                "required": False,
            },
        ],
    })

    # ── 5. Nginx (always include — it's the front door) ─────────────────────
    sections.append({
        "id": "nginx",
        "title": "Nginx",
        "description": "Nginx is the TLS termination point. Config errors and certificate issues here affect all services.",
        "items": [
            {
                "id": "nginx.status",
                "label": "Nginx service status",
                "context": "Confirms nginx is running and shows recent state.",
                "command": "systemctl status nginx --no-pager -l 2>/dev/null || nginx -t 2>&1",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "nginx.config_test",
                "label": "Nginx config test",
                "context": "nginx -t validates the config syntax and reports certificate file errors.",
                "command": "nginx -t 2>&1",
                "input_type": "command_output",
                "required": True,
            },
            {
                "id": "nginx.journal",
                "label": "Nginx recent error log",
                "context": "SSL handshake errors, upstream connection failures, and 502s appear here.",
                "command": "journalctl -u nginx -n 100 --no-pager 2>/dev/null || tail -n 100 /var/log/nginx/error.log 2>/dev/null",
                "input_type": "command_output",
                "required": False,
            },
        ],
    })

    return sections


def questionnaire_to_markdown(sections: list[dict], report_id: str, title: str, version: str) -> str:
    """Render the questionnaire as a copy-paste-friendly Markdown checklist."""
    lines = [
        f"# Diagnostic Information Request",
        f"**Report:** {report_id}  **Platform:** {title} v{version}",
        "",
        "Run each command on the target server and paste the output into the corresponding field in the JAR Analyser → Diagnostics → Manual Collection page.",
        "If a command is not available, leave the field blank.",
        "",
    ]
    for sec in sections:
        lines.append(f"## {sec['title']}")
        lines.append(f"_{sec['description']}_")
        lines.append("")
        for item in sec["items"]:
            req = " *(required)*" if item.get("required") else ""
            lines.append(f"### {item['label']}{req}")
            lines.append(f"{item['context']}")
            lines.append("")
            if item.get("command"):
                lines.append("```bash")
                lines.append(item["command"])
                lines.append("```")
            lines.append("")
    return "\n".join(lines)
