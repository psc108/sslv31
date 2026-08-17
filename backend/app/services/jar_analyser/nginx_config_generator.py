"""Nginx configuration generator.

Produces ready-to-use nginx configs in three deployment flavours from the
raw nginx config content already extracted into the DB:

  on_prem_standard  — single-host upstreams, TLS termination at nginx
  on_prem_ha        — dual-host upstreams (host1/host2), same TLS setup
  aws               — HTTP-only upstreams (ALB terminates TLS externally)
  docker            — service-name upstreams (Docker DNS), no inter-service TLS

Data sources used:
  - jar_config_files.content  for frontend-lb / backend-lb (raw nginx conf)
  - sub_reports.declared_port for each service
  - sub_reports.installer_metadata_json for upstream lists
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Placeholder resolution
# ---------------------------------------------------------------------------

# Maps the parts.<key> name used in nginx to the service_name in sub_reports.
# The nginx config uses camelCase for some (serviceInstances) and kebab for others.
_PARTS_KEY_MAP: dict[str, str] = {
    "management-ui":   "management-ui",
    "portal-ui":       "portal-ui",
    "catalog":         "catalog",
    "blob-store":      "blob-store",
    "customers":       "customers",
    "event":           "event",
    "fulfillment":     "fulfillment",
    "request":         "request",
    "serviceInstances": "service-instances",
    "pricing":         "pricing",
    "reporting":       "reporting",
    "ticketing":       "ticketing",
    "config":          "config",
    "diagnostic":      "diagnostic",
    "export":          "export",
    "api-doc":         "api-doc",
    "idm":             "idm",
}

# Fixed ports for monitoring services not in sub_reports
_FIXED_PORTS: dict[str, int] = {
    "grafana":    3000,
    "prometheus": 9090,
}


def _build_port_map(sub_reports: list[dict]) -> dict[str, int]:
    """service_name -> declared_port from sub_reports."""
    m: dict[str, int] = {}
    for sr in sub_reports:
        name = sr.get("service_name") or ""
        port = sr.get("declared_port")
        if name and port:
            m[name] = int(port)
    m.update(_FIXED_PORTS)
    return m


def _resolve_port(parts_key: str, port_map: dict[str, int]) -> int:
    svc = _PARTS_KEY_MAP.get(parts_key, parts_key)
    return port_map.get(svc, 8080)


# ---------------------------------------------------------------------------
# Nginx config builders
# ---------------------------------------------------------------------------

_SSL_COMMON = """\
    ssl_session_cache    shared:SSL:1m;
    ssl_session_timeout  10m;
    ssl_certificate      /opt/ecs/security/server_chain.crt;
    ssl_certificate_key  /opt/ecs/security/server.key;
    ssl_password_file    /etc/nginx/password;
    ssl_verify_client    off;
    ssl_prefer_server_ciphers on;
    ssl_protocols        TLSv1.2 TLSv1.3;
    ssl_ciphers          'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:DHE-RSA-AES256-SHA384:HIGH:!aNULL:!eNULL:!EXPORT:!3DES:!RC4:!MD5';"""

_PROXY_COMMON = """\
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   Connection        "";
    proxy_http_version 1.1;
    client_max_body_size    50m;
    client_body_buffer_size 128k;
    proxy_connect_timeout   1200;
    proxy_send_timeout      1200;
    proxy_read_timeout      1200;
    send_timeout            1200;
    proxy_buffers           32 4k;"""

# Rewrites absolute redirects from IDM back to relative paths.
# Only needed when nginx terminates TLS (on-prem); for HTTP-internal
# deployments (AWS/Docker) use proxy_redirect off.
_PROXY_REDIRECT_TLS = "    proxy_redirect     ~^https?://[^/]+(/api/idm.+)$ $1;"
_PROXY_REDIRECT_HTTP = "    proxy_redirect     off;"


def _upstream_block_standard(name: str, host_var: str, port: int, proto: str = "https") -> str:
    return (
        f"upstream {name} {{\n"
        f"    server {host_var}:{port};\n"
        f"    keepalive 5;\n"
        f"}}"
    )


def _upstream_block_ha(name: str, host1_var: str, host2_var: str, port: int) -> str:
    return (
        f"upstream {name} {{\n"
        f"    server {host1_var}:{port};\n"
        f"    server {host2_var}:{port};\n"
        f"    keepalive 5;\n"
        f"}}"
    )


def _upstream_block_docker(name: str, docker_host: str, port: int) -> str:
    return (
        f"upstream {name} {{\n"
        f"    server {docker_host}:{port};\n"
        f"    keepalive 5;\n"
        f"}}"
    )


# ---------------------------------------------------------------------------
# Location extraction from raw nginx config
# ---------------------------------------------------------------------------

_LOCATION_RE = re.compile(
    r"location\s+(\S+)\s*\{[^}]*proxy_pass\s+(https?://\S+);[^}]*\}",
    re.DOTALL,
)
_RETURN_RE = re.compile(
    r"location\s+(\S+)\s*\{[^}]*return\s+(\d+)[^}]*\}",
    re.DOTALL,
)
_REWRITE_RE = re.compile(
    r"location\s+(\S+)\s*\{[^}]*rewrite\s+([^\n]+)\n[^}]*\}",
    re.DOTALL,
)


def _extract_locations(raw: str) -> list[dict]:
    """Extract location blocks from raw nginx config."""
    locations: list[dict] = []
    seen: set[str] = set()

    for m in _LOCATION_RE.finditer(raw):
        path = m.group(1)
        proxy_pass = m.group(2).rstrip("/")
        if path not in seen:
            seen.add(path)
            locations.append({"path": path, "proxy_pass": proxy_pass, "type": "proxy"})

    # health check / redirect locations
    for m in _RETURN_RE.finditer(raw):
        path = m.group(1)
        code = m.group(2)
        if path not in seen:
            seen.add(path)
            locations.append({"path": path, "return_code": code, "type": "return"})

    return locations


# ---------------------------------------------------------------------------
# Upstream catalogue from installer metadata
# ---------------------------------------------------------------------------

def _get_upstreams(nginx_meta: dict, ha: bool = False) -> list[dict]:
    key = "ha_upstreams" if ha else "upstreams"
    return nginx_meta.get(key) or nginx_meta.get("upstreams") or []


def _upstream_name_to_parts_key(upstream_name: str) -> str:
    """'catalog-upstream' -> 'catalog', 'service-instances-upstream' -> 'serviceInstances'."""
    base = re.sub(r"-upstream$", "", upstream_name)
    # reverse the camelCase mapping
    for parts_key, svc in _PARTS_KEY_MAP.items():
        if svc == base:
            return parts_key
    return base


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def build_nginx_configs(sub_reports: list[dict]) -> dict[str, Any]:
    """
    Returns:
      {
        "on_prem_standard": { "frontend": str, "backend": str },
        "on_prem_ha":       { "frontend": str, "backend": str },
        "aws":              { "frontend": str, "backend": str },
        "docker":           { "frontend": str, "backend": str },
        "services":         [ {name, port} ],
        "notes":            { on_prem_standard: str, ... }
      }
    """
    port_map = _build_port_map(sub_reports)

    # Find the two LB sub-reports and their raw configs
    lb_configs: dict[str, dict] = {}  # "frontend" | "backend" -> {nginx_meta, raw_standard, raw_ha}
    for sr in sub_reports:
        svc = sr.get("service_name", "")
        if svc not in ("frontend-lb", "backend-lb"):
            continue
        key = "frontend" if svc == "frontend-lb" else "backend"
        meta = sr.get("installer_metadata") or {}
        nginx_meta = meta.get("nginx") or {}

        raw_std = raw_ha = ""
        for cf in sr.get("config_files", []):
            fname = cf.get("filename", "")
            content = cf.get("content") or ""
            if fname.endswith(".conf.ha"):
                raw_ha = content
            elif fname.endswith(".conf"):
                raw_std = content

        lb_configs[key] = {
            "nginx_meta": nginx_meta,
            "raw_standard": raw_std,
            "raw_ha": raw_ha,
        }

    result: dict[str, Any] = {
        "on_prem_standard": {},
        "on_prem_ha": {},
        "aws": {},
        "docker": {},
        "services": [
            {"name": sr.get("service_name"), "port": sr.get("declared_port")}
            for sr in sub_reports
            if sr.get("declared_port") and sr.get("service_name")
               and sr.get("service_name") not in ("frontend-lb", "backend-lb")
        ],
        "notes": {
            "on_prem_standard": (
                "Single-host deployment. Replace <HOST> placeholders with actual hostnames/IPs. "
                "TLS terminated at nginx using /opt/ecs/security/server_chain.crt."
            ),
            "on_prem_ha": (
                "High-availability deployment. Replace <HOST1> and <HOST2> with the two node "
                "hostnames/IPs for each service. nginx round-robins between them."
            ),
            "aws": (
                "AWS deployment with an Application Load Balancer (ALB) handling TLS termination. "
                "nginx listens on HTTP port 80 and forwards to services on their declared ports. "
                "Set X-Forwarded-Proto header on the ALB. Replace <HOST> with private DNS names "
                "or use AWS service discovery / ECS task IPs."
            ),
            "docker": (
                "Docker Compose / Kubernetes deployment. Service names are used directly as "
                "hostnames (Docker DNS). No TLS between containers — plain HTTP internally. "
                "Expose only port 80 externally and terminate TLS at a reverse proxy or ingress."
            ),
        },
    }

    for lb_key, lb_data in lb_configs.items():
        nginx_meta = lb_data["nginx_meta"]
        raw_std = lb_data["raw_standard"]
        raw_ha = lb_data["raw_ha"]
        locations = _extract_locations(raw_std or raw_ha)

        upstreams_std = _get_upstreams(nginx_meta, ha=False)
        upstreams_ha = _get_upstreams(nginx_meta, ha=True)

        result["on_prem_standard"][lb_key] = _render_on_prem(
            lb_key, upstreams_std, locations, port_map, ha=False
        )
        result["on_prem_ha"][lb_key] = _render_on_prem(
            lb_key, upstreams_ha, locations, port_map, ha=True
        )
        result["aws"][lb_key] = _render_aws(
            lb_key, upstreams_std, locations, port_map
        )
        result["docker"][lb_key] = _render_docker(
            lb_key, upstreams_std, locations, port_map
        )

    return result


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_on_prem(
    lb_key: str,
    upstreams: list[dict],
    locations: list[dict],
    port_map: dict[str, int],
    ha: bool,
) -> str:
    lines = [
        f"# {lb_key.upper()} LOAD BALANCER — On-Premises {'HA' if ha else 'Standard'}",
        f"# Generated from JAR analysis. Replace <HOST{'1/HOST2' if ha else ''}> placeholders.",
        "",
    ]

    for u in upstreams:
        uname = u["name"]
        parts_key = _upstream_name_to_parts_key(uname)
        port = _resolve_port(parts_key, port_map)
        if ha:
            lines.append(_upstream_block_ha(uname, f"<{parts_key.upper()}_HOST1>", f"<{parts_key.upper()}_HOST2>", port))
        else:
            lines.append(_upstream_block_standard(uname, f"<{parts_key.upper()}_HOST>", port))
        lines.append("")

    lines += [
        "server {",
        "    listen       443 default_server ssl;",
        "    server_name  _;",
        "",
        _SSL_COMMON,
        "",
        _PROXY_COMMON,
        _PROXY_REDIRECT_TLS,
        "    proxy_ssl_session_reuse on;",
        "",
    ]
    lines += _render_locations(locations, proto="https")
    lines.append("}")
    return "\n".join(lines)


def _render_aws(
    lb_key: str,
    upstreams: list[dict],
    locations: list[dict],
    port_map: dict[str, int],
) -> str:
    lines = [
        f"# {lb_key.upper()} LOAD BALANCER — AWS (ALB terminates TLS)",
        "# nginx listens on HTTP :80. ALB handles HTTPS and forwards here.",
        "# Replace <HOST> with private DNS names or ECS task IPs.",
        "",
    ]

    for u in upstreams:
        uname = u["name"]
        parts_key = _upstream_name_to_parts_key(uname)
        port = _resolve_port(parts_key, port_map)
        lines.append(_upstream_block_standard(uname, f"<{parts_key.upper()}_HOST>", port, proto="http"))
        lines.append("")

    lines += [
        "server {",
        "    listen       80 default_server;",
        "    server_name  _;",
        "",
        "    # Trust X-Forwarded-Proto from ALB",
        "    set $forwarded_proto $http_x_forwarded_proto;",
        "",
        _PROXY_COMMON,
        "    proxy_set_header   X-Forwarded-Proto $forwarded_proto;",
        _PROXY_REDIRECT_HTTP,
        "",
    ]
    # AWS: proxy_pass uses http:// (no inter-service TLS)
    aws_locations = [
        {**loc, "proxy_pass": re.sub(r"^https://", "http://", loc.get("proxy_pass", ""))}
        if loc.get("type") == "proxy" else loc
        for loc in locations
    ]
    lines += _render_locations(aws_locations, proto="http")
    lines.append("}")
    return "\n".join(lines)


def _render_docker(
    lb_key: str,
    upstreams: list[dict],
    locations: list[dict],
    port_map: dict[str, int],
) -> str:
    lines = [
        f"# {lb_key.upper()} LOAD BALANCER — Docker Compose / Kubernetes",
        "# Service names resolve via Docker DNS. No TLS between containers.",
        "# Expose port 80 only; terminate TLS at an ingress controller or ALB.",
        "",
    ]

    for u in upstreams:
        uname = u["name"]
        parts_key = _upstream_name_to_parts_key(uname)
        # Docker service name = the svc name (kebab-case)
        docker_host = _PARTS_KEY_MAP.get(parts_key, parts_key)
        port = _resolve_port(parts_key, port_map)
        lines.append(_upstream_block_docker(uname, docker_host, port))
        lines.append("")

    lines += [
        "server {",
        "    listen       80 default_server;",
        "    server_name  _;",
        "",
        _PROXY_COMMON,
        _PROXY_REDIRECT_HTTP,
        "",
    ]
    docker_locations = [
        {**loc, "proxy_pass": re.sub(r"^https://", "http://", loc.get("proxy_pass", ""))}
        if loc.get("type") == "proxy" else loc
        for loc in locations
    ]
    lines += _render_locations(docker_locations, proto="http")
    lines.append("}")
    return "\n".join(lines)


def _render_locations(locations: list[dict], proto: str) -> list[str]:
    lines: list[str] = []
    for loc in locations:
        path = loc["path"]
        if loc.get("type") == "proxy":
            pp = loc.get("proxy_pass", "")
            lines.append(f"    location {path} {{")
            lines.append(f"        proxy_pass  {pp}/;")
            lines.append("    }")
            lines.append("")
        elif loc.get("type") == "return":
            code = loc.get("return_code", "404")
            if code == "200":
                lines.append(f"    location {path} {{")
                lines.append(f'        access_log off;')
                lines.append(f'        return 200 "healthy\\n";')
                lines.append("    }")
            else:
                lines.append(f"    location {path} {{")
                lines.append(f"        return {code};")
                lines.append("    }")
            lines.append("")
    return lines
