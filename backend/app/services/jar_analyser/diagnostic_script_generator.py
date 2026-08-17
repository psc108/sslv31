"""Generate a report-specific diagnostic collection script.

The script is a self-contained bash file that:
  - Detects the OS (RHEL 8/9, Ubuntu, Amazon Linux 2023)
  - Collects config files at their known install paths
  - Collects systemd/journald logs for each service
  - Collects SSL keystore/truststore files (metadata only — no private keys)
  - Runs connectivity checks (port, DB ping, RabbitMQ)
  - Captures JVM/OS environment info
  - Packages everything into a timestamped tar.gz for upload
"""
from __future__ import annotations

import json
from typing import Any


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_ssl_paths(config_files: list[dict]) -> list[str]:
    paths: list[str] = []
    ssl_keys = ("keystore", "truststore", "ssl.key-store", "ssl.trust-store",
                "javax.net.ssl.keyStore", "javax.net.ssl.trustStore")
    for cfg in config_files:
        for k in cfg.get("keys", []):
            key = (k.get("key") or "").lower()
            val = k.get("value") or ""
            if any(s in key for s in ssl_keys) and val and not val.startswith("${"):
                if "/" in val or val.endswith((".jks", ".p12", ".pem", ".crt", ".cer")):
                    paths.append(val)
    return list(dict.fromkeys(paths))  # deduplicate, preserve order


def _extract_log_paths(config_files: list[dict], service_name: str, install_path: str | None) -> list[str]:
    paths: list[str] = []
    log_keys = ("logging.file", "logging.path", "log.file", "log.dir", "log4j", "logback")
    for cfg in config_files:
        for k in cfg.get("keys", []):
            key = (k.get("key") or "").lower()
            val = k.get("value") or ""
            if any(s in key for s in log_keys) and val and not val.startswith("${"):
                paths.append(val)
    # Fallback conventional paths
    base = install_path or f"/opt/{service_name}"
    paths += [
        f"{base}/logs",
        f"/var/log/{service_name}",
        f"/var/log/app/{service_name}",
    ]
    return list(dict.fromkeys(paths))


def _extract_config_paths(config_files: list[dict], service_name: str, install_path: str | None) -> list[str]:
    """Return the on-disk paths where config files are likely to live."""
    paths: list[str] = []
    base = install_path or f"/opt/{service_name}"
    for cfg in config_files:
        fname = cfg.get("filename", "")
        if fname:
            paths.append(f"{base}/config/{fname}")
            paths.append(f"{base}/{fname}")
    # Common Spring Boot config locations
    paths += [
        f"{base}/config/application.properties",
        f"{base}/config/application.yml",
        f"{base}/application.properties",
        f"{base}/application.yml",
    ]
    return list(dict.fromkeys(paths))


def _extract_db_info(config_files: list[dict]) -> dict[str, str]:
    info: dict[str, str] = {}
    for cfg in config_files:
        for k in cfg.get("keys", []):
            key = (k.get("key") or "").lower()
            val = k.get("value") or ""
            if val.startswith("${"):
                continue
            if "datasource.url" in key and "url" not in info:
                info["url"] = val
            if "datasource.username" in key and "user" not in info:
                info["user"] = val
            if "datasource.driver" in key and "driver" not in info:
                info["driver"] = val
    return info


def _extract_rmq_info(config_files: list[dict]) -> dict[str, str]:
    info: dict[str, str] = {}
    for cfg in config_files:
        for k in cfg.get("keys", []):
            key = (k.get("key") or "").lower()
            val = k.get("value") or ""
            if val.startswith("${"):
                continue
            if "rabbitmq.host" in key and "host" not in info:
                info["host"] = val
            if "rabbitmq.port" in key and "port" not in info:
                info["port"] = val
            if "rabbitmq.virtual-host" in key and "vhost" not in info:
                info["vhost"] = val
    return info


# ── Main generator ────────────────────────────────────────────────────────────

def generate_diagnostic_script(report: dict, sub_dicts: list[dict]) -> str:
    """Return a bash script string tailored to this report."""

    version = report.get("manifest", {}).get("Implementation-Version") or \
              report.get("summary", {}).get("implementation_version") or "unknown"
    title = report.get("manifest", {}).get("Implementation-Title") or "platform"
    report_id = report.get("report_id", "unknown")

    # Build per-service collection specs
    services: list[dict[str, Any]] = []
    all_ports: list[int] = []
    rmq_info: dict[str, str] = {}

    for sub in sub_dicts:
        if sub.get("jar_type") in ("nginx_installer", "monitoring_installer", "frontend_installer"):
            continue
        svc = sub.get("service_name") or sub.get("filename", "svc")
        install_path = sub.get("install_path")
        port = sub.get("declared_port")
        cfgs = sub.get("config_files", [])

        if port:
            all_ports.append(port)

        ssl_paths = _extract_ssl_paths(cfgs)
        log_paths = _extract_log_paths(cfgs, svc, install_path)
        cfg_paths = _extract_config_paths(cfgs, svc, install_path)
        db_info = _extract_db_info(cfgs)
        rmq = _extract_rmq_info(cfgs)
        if rmq and not rmq_info:
            rmq_info = rmq

        services.append({
            "name": svc,
            "port": port,
            "install_path": install_path or f"/opt/{svc}",
            "ssl_paths": ssl_paths,
            "log_paths": log_paths,
            "cfg_paths": cfg_paths,
            "db_info": db_info,
            "systemd_unit": f"{svc}.service",
        })

    # Render the script
    lines: list[str] = []
    a = lines.append

    a("#!/usr/bin/env bash")
    a("# ============================================================")
    a(f"# Diagnostic Collection Script")
    a(f"# Report  : {report_id}")
    a(f"# Platform: {title} v{version}")
    a(f"# Generated by SSL Certificate Manager — JAR Analyser")
    a("# ============================================================")
    a("# Usage: sudo bash <script>.sh")
    a("# Output: /tmp/diag_<hostname>_<timestamp>.tar.gz")
    a("# Upload the tar.gz via the JAR Analyser → Diagnostics page.")
    a("# ============================================================")
    a("set -uo pipefail")
    a("")
    a("# ── Metadata ────────────────────────────────────────────────")
    a(f'REPORT_ID="{report_id}"')
    a(f'PLATFORM_VERSION="{version}"')
    a('HOSTNAME_SAFE=$(hostname -s 2>/dev/null || echo "unknown")')
    a('TIMESTAMP=$(date +%Y%m%d_%H%M%S)')
    a('OUTDIR=$(mktemp -d /tmp/diag_XXXXXX)')
    a('TARBALL="/tmp/diag_${HOSTNAME_SAFE}_${TIMESTAMP}.tar.gz"')
    a('LOG="${OUTDIR}/collection.log"')
    a("")
    a("# ── OS detection ────────────────────────────────────────────")
    a('OS_ID="unknown"')
    a('if [ -f /etc/os-release ]; then')
    a('  . /etc/os-release')
    a('  OS_ID="${ID:-unknown}"')
    a('fi')
    a('echo "OS: ${OS_ID}" | tee -a "$LOG"')
    a("")
    a("# ── Capability detection ────────────────────────────────────")
    a('HAS_OPENSSL=0; command -v openssl &>/dev/null && HAS_OPENSSL=1')
    a('HAS_KEYTOOL=0; command -v keytool &>/dev/null && HAS_KEYTOOL=1')
    a('HAS_JAVA=0;    command -v java    &>/dev/null && HAS_JAVA=1')
    a('HAS_NC=0;      command -v nc      &>/dev/null && HAS_NC=1')
    a('HAS_CURL=0;    command -v curl    &>/dev/null && HAS_CURL=1')
    a('HAS_SS=0;      command -v ss      &>/dev/null && HAS_SS=1')
    a('HAS_NETSTAT=0; command -v netstat &>/dev/null && HAS_NETSTAT=1')
    a('HAS_JOURNALCTL=0; command -v journalctl &>/dev/null && HAS_JOURNALCTL=1')
    a('HAS_GREP_P=0;  echo "" | grep -P "" &>/dev/null 2>&1 && HAS_GREP_P=1')
    a('echo "Capabilities: openssl=$HAS_OPENSSL keytool=$HAS_KEYTOOL java=$HAS_JAVA nc=$HAS_NC curl=$HAS_CURL ss=$HAS_SS journalctl=$HAS_JOURNALCTL" | tee -a "$LOG"')
    a("")
    a("# ── Helper functions ────────────────────────────────────────")
    a('collect_file() {')
    a('  local src="$1" dst="$2"')
    a('  if [ -f "$src" ]; then')
    a('    mkdir -p "$(dirname "$dst")"')
    a('    cp "$src" "$dst" 2>/dev/null && echo "  [OK] $src" >> "$LOG" || echo "  [SKIP] $src (copy failed)" >> "$LOG"')
    a('  else')
    a('    echo "  [MISS] $src" >> "$LOG"')
    a('  fi')
    a('}')
    a('')
    a('collect_dir() {')
    a('  local src="$1" dst="$2" maxlines="${3:-2000}"')
    a('  if [ -d "$src" ]; then')
    a('    mkdir -p "$dst"')
    a('    find "$src" -maxdepth 2 -name "*.log" -o -name "*.out" -o -name "*.err" 2>/dev/null | while read -r f; do')
    a('      tail -n "$maxlines" "$f" > "${dst}/$(basename "$f").tail" 2>/dev/null || true')
    a('    done')
    a('    echo "  [OK] dir $src" >> "$LOG"')
    a('  else')
    a('    echo "  [MISS] dir $src" >> "$LOG"')
    a('  fi')
    a('}')
    a('')
    a('cert_info() {')
    a('  local f="$1" dst="$2"')
    a('  if [ -f "$f" ]; then')
    a('    mkdir -p "$(dirname "$dst")"')
    a('    case "$f" in')
    a('      *.pem|*.crt|*.cer)')
    a('        if [ "$HAS_OPENSSL" = "1" ]; then')
    a('          openssl x509 -in "$f" -noout -text 2>/dev/null > "$dst" || echo "[openssl failed]" > "$dst"')
    a('        else')
    a('          echo "[SKIP] openssl not available — cannot decode PEM/CRT" > "$dst"')
    a('        fi ;;')
    a('      *.jks|*.p12|*.pfx)')
    a('        if [ "$HAS_KEYTOOL" = "1" ]; then')
    a('          keytool -list -keystore "$f" -storepass changeit -noprompt 2>/dev/null > "$dst" || \\')
    a('          keytool -list -keystore "$f" -storepass "" -noprompt 2>/dev/null >> "$dst" || \\')
    a('          echo "[keytool failed — wrong password?]" >> "$dst"')
    a('        else')
    a('          echo "[SKIP] keytool not available — cannot inspect JKS/P12" > "$dst"')
    a('        fi ;;')
    a('    esac')
    a('    echo "  [CERT] $f" >> "$LOG"')
    a('  fi')
    a('}')
    a('')
    a('port_check() {')
    a('  local host="${1:-localhost}" port="$2" svc="$3" dst="$4"')
    a('  mkdir -p "$(dirname "$dst")"')
    a('  if [ "$HAS_NC" = "1" ]; then')
    a('    nc -z -w3 "$host" "$port" 2>&1 && echo "OPEN" > "$dst" || echo "CLOSED" > "$dst"')
    a('  else')
    a('    (echo >/dev/tcp/"$host"/"$port") 2>/dev/null && echo "OPEN" > "$dst" || echo "CLOSED" > "$dst"')
    a('  fi')
    a('  echo "  [PORT] $svc $host:$port $(cat "$dst" 2>/dev/null)" >> "$LOG"')
    a('}')
    a('')
    a('# ── System info ─────────────────────────────────────────────')
    a('SYSDIR="${OUTDIR}/system"')
    a('mkdir -p "$SYSDIR"')
    a('echo "=== uname ===" > "${SYSDIR}/os_info.txt"')
    a('uname -a >> "${SYSDIR}/os_info.txt" 2>/dev/null || true')
    a('echo "=== /etc/os-release ===" >> "${SYSDIR}/os_info.txt"')
    a('cat /etc/os-release >> "${SYSDIR}/os_info.txt" 2>/dev/null || true')
    a('echo "=== hostname ===" >> "${SYSDIR}/os_info.txt"')
    a('hostname -f >> "${SYSDIR}/os_info.txt" 2>/dev/null || true')
    a('echo "=== date ===" >> "${SYSDIR}/os_info.txt"')
    a('date -u >> "${SYSDIR}/os_info.txt" 2>/dev/null || true')
    a('echo "=== uptime ===" >> "${SYSDIR}/os_info.txt"')
    a('uptime >> "${SYSDIR}/os_info.txt" 2>/dev/null || true')
    a('echo "=== df ===" >> "${SYSDIR}/os_info.txt"')
    a('df -h >> "${SYSDIR}/os_info.txt" 2>/dev/null || true')
    a('echo "=== free ===" >> "${SYSDIR}/os_info.txt"')
    a('free -m >> "${SYSDIR}/os_info.txt" 2>/dev/null || true')
    a('echo "=== java version ===" >> "${SYSDIR}/os_info.txt"')
    a('java -version >> "${SYSDIR}/os_info.txt" 2>&1 || true')
    a('echo "=== JAVA_HOME ===" >> "${SYSDIR}/os_info.txt"')
    a('echo "${JAVA_HOME:-not set}" >> "${SYSDIR}/os_info.txt"')
    a('echo "=== listening ports ===" >> "${SYSDIR}/os_info.txt"')
    a('if [ "$HAS_SS" = "1" ]; then')
    a('  ss -tlnp 2>/dev/null >> "${SYSDIR}/os_info.txt" || true')
    a('elif [ "$HAS_NETSTAT" = "1" ]; then')
    a('  netstat -tlnp 2>/dev/null >> "${SYSDIR}/os_info.txt" || true')
    a('else')
    a('  echo "[SKIP] ss/netstat not available" >> "${SYSDIR}/os_info.txt"')
    a('fi')
    a('echo "=== systemd failed units ===" >> "${SYSDIR}/os_info.txt"')
    a('systemctl list-units --state=failed 2>/dev/null >> "${SYSDIR}/os_info.txt" || true')
    a('')
    a('# JVM cacerts info')
    a('if [ "$HAS_JAVA" = "1" ]; then')
    a('  JAVA_SEC=$(java -XshowSettings:all -version 2>&1 | grep "java.home" | awk \'{print $3}\' | head -1)')
    a('  if [ -n "$JAVA_SEC" ]; then')
    a('    CACERTS="${JAVA_SEC}/lib/security/cacerts"')
    a('    [ -f "$CACERTS" ] || CACERTS="${JAVA_SEC}/../lib/security/cacerts"')
    a('    cert_info "$CACERTS" "${SYSDIR}/jvm_cacerts.txt"')
    a('  fi')
    a('else')
    a('  echo "[SKIP] java not available — JVM cacerts not collected" >> "${SYSDIR}/os_info.txt"')
    a('fi')
    a('')

    # Per-service collection
    for svc_spec in services:
        svc = svc_spec["name"]
        safe = svc.replace("-", "_").replace(".", "_")
        svcdir = f'"${{OUTDIR}}/services/{svc}"'
        a(f'# ── Service: {svc} ──────────────────────────────────────')
        a(f'echo "Collecting {svc}..." | tee -a "$LOG"')
        a(f'mkdir -p {svcdir}')
        a('')

        # Config files
        a(f'# Config files')
        for p in svc_spec["cfg_paths"][:8]:
            a(f'collect_file "{p}" {svcdir}/config/$(basename "{p}")')
        a('')

        # Log files
        a(f'# Log files (last 2000 lines per file)')
        for p in svc_spec["log_paths"][:4]:
            a(f'collect_dir "{p}" {svcdir}/logs')
        a('')

        # Systemd journal
        a(f'# Systemd journal (last 500 lines)')
        a(f'if [ "$HAS_JOURNALCTL" = "1" ]; then')
        a(f'  journalctl -u "{svc_spec["systemd_unit"]}" -n 500 --no-pager 2>/dev/null > {svcdir}/journal.log || true')
        a(f'  journalctl -u "{svc}" -n 500 --no-pager 2>/dev/null >> {svcdir}/journal.log 2>/dev/null || true')
        a(f'else')
        a(f'  echo "[SKIP] journalctl not available" > {svcdir}/journal.log')
        a(f'fi')
        a('')

        # SSL cert metadata
        if svc_spec["ssl_paths"]:
            a(f'# SSL certificate metadata (no private keys)')
            for p in svc_spec["ssl_paths"][:4]:
                safe_name = p.replace("/", "_").lstrip("_")
                a(f'cert_info "{p}" {svcdir}/certs/{safe_name}.txt')
            a('')

        # Port check
        if svc_spec["port"]:
            a(f'# Port connectivity check')
            a(f'port_check "localhost" "{svc_spec["port"]}" "{svc}" {svcdir}/port_{svc_spec["port"]}.txt')
            a('')

        # DB connectivity
        if svc_spec["db_info"].get("url"):
            db_url = svc_spec["db_info"]["url"]
            a(f'# Database connectivity check')
            a(f'# DB URL: {db_url}')
            a(f'DB_URL="{db_url}"')
            a(f'if [ "$HAS_GREP_P" = "1" ]; then')
            a(f'  DB_HOST=$(echo "$DB_URL" | grep -oP "(?<=://)[^:/]+" 2>/dev/null || echo "localhost")')
            a(f'  DB_PORT=$(echo "$DB_URL" | grep -oP "(?<=:)\\d{{4,5}}(?=/)" 2>/dev/null || echo "3306")')
            a(f'else')
            a(f'  DB_HOST=$(echo "$DB_URL" | sed "s|.*://||;s|[:/].*||")')
            a(f'  DB_PORT="3306"')
            a(f'fi')
            a(f'port_check "$DB_HOST" "$DB_PORT" "db-{svc}" {svcdir}/port_db.txt')
            a('')

    # RabbitMQ check
    if rmq_info:
        rmq_host = rmq_info.get("host", "localhost")
        rmq_port = rmq_info.get("port", "5672")
        a('# ── RabbitMQ connectivity ───────────────────────────────')
        a(f'echo "Checking RabbitMQ..." | tee -a "$LOG"')
        a(f'RMQDIR="${{OUTDIR}}/rabbitmq"')
        a(f'mkdir -p "$RMQDIR"')
        a(f'port_check "{rmq_host}" "{rmq_port}" "rabbitmq" "${{RMQDIR}}/port.txt"')
        a('# RabbitMQ management API (if accessible)')
        a('if [ "$HAS_CURL" = "1" ]; then')
        a(f'  curl -s -o "${{RMQDIR}}/overview.json" "http://{rmq_host}:15672/api/overview" 2>/dev/null || true')
        a(f'  curl -s -o "${{RMQDIR}}/nodes.json" "http://{rmq_host}:15672/api/nodes" 2>/dev/null || true')
        a('else')
        a(f'  echo "[SKIP] curl not available — RabbitMQ management API not queried" > "${{RMQDIR}}/overview.json"')
        a('fi')
        a('')

    # All port checks summary
    if all_ports:
        a('# ── Port inventory check ────────────────────────────────')
        a('PORTDIR="${OUTDIR}/ports"')
        a('mkdir -p "$PORTDIR"')
        for port in sorted(set(all_ports)):
            a(f'port_check "localhost" "{port}" "port-{port}" "${{PORTDIR}}/port_{port}.txt"')
        a('')

    # Nginx config
    a('# ── Nginx config (if present) ───────────────────────────')
    a('NGINXDIR="${OUTDIR}/nginx"')
    a('mkdir -p "$NGINXDIR"')
    a('collect_dir "/etc/nginx" "$NGINXDIR/etc_nginx"')
    a('collect_dir "/opt/nginx/conf" "$NGINXDIR/opt_nginx"')
    a('journalctl -u nginx -n 200 --no-pager 2>/dev/null > "$NGINXDIR/journal.log" || true')
    a('')

    # Capabilities summary + manifest
    a('# ── Capabilities summary ────────────────────────────────')
    a('cat > "${OUTDIR}/capabilities.json" <<EOF')
    a('{')
    a('  "openssl":    $HAS_OPENSSL,')
    a('  "keytool":    $HAS_KEYTOOL,')
    a('  "java":       $HAS_JAVA,')
    a('  "nc":         $HAS_NC,')
    a('  "curl":       $HAS_CURL,')
    a('  "ss":         $HAS_SS,')
    a('  "netstat":    $HAS_NETSTAT,')
    a('  "journalctl": $HAS_JOURNALCTL,')
    a('  "grep_pcre":  $HAS_GREP_P')
    a('}')
    a('EOF')
    a('')
    a('# ── Report metadata ─────────────────────────────────────')
    a('cat > "${OUTDIR}/manifest.json" <<EOF')
    a('{')
    a(f'  "report_id": "{report_id}",')
    a(f'  "platform_version": "{version}",')
    a(f'  "platform_title": "{title}",')
    a('  "collected_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",')
    a('  "hostname": "$(hostname -f 2>/dev/null || hostname)",')
    a('  "os_id": "${OS_ID}",')
    a(f'  "services": {json.dumps([s["name"] for s in services])}')
    a('}')
    a('EOF')
    a('')

    # Package
    a('# ── Package ─────────────────────────────────────────────')
    a('echo "Packaging..." | tee -a "$LOG"')
    a('tar -czf "$TARBALL" -C "$(dirname "$OUTDIR")" "$(basename "$OUTDIR")" 2>/dev/null')
    a('rm -rf "$OUTDIR"')
    a('echo ""')
    a('echo "============================================================"')
    a('echo "Diagnostic bundle: $TARBALL"')
    a('echo "Upload this file via: JAR Analyser → Diagnostics → Upload"')
    a('echo "============================================================"')

    return "\n".join(lines) + "\n"
