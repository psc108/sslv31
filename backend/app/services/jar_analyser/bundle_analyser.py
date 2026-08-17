"""Bundle analyser — extracts rich detail from non-Java installer JARs.

Handles:
- NGINX_INSTALLER    : upstream blocks, server blocks, HA config, SSL directives
- MONITORING_INSTALLER: Grafana dashboards/datasources, Prometheus scrape targets
- FRONTEND_INSTALLER : package.json, version.json, Node.js entry points, API URL mappings
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml


# ---------------------------------------------------------------------------
# Nginx
# ---------------------------------------------------------------------------

@dataclass
class NginxUpstream:
    name: str
    servers: list[str]
    keepalive: int | None = None
    is_ha: bool = False

@dataclass
class NginxServerBlock:
    listen_ports: list[int]
    server_names: list[str]
    ssl: bool = False
    locations: list[dict] = field(default_factory=list)

@dataclass
class NginxAnalysis:
    upstreams: list[NginxUpstream] = field(default_factory=list)
    server_blocks: list[NginxServerBlock] = field(default_factory=list)
    ha_upstreams: list[NginxUpstream] = field(default_factory=list)
    raw_files: list[dict] = field(default_factory=list)   # {filename, content}
    service_dependencies: list[str] = field(default_factory=list)  # part names referenced


class NginxAnalyser:
    @staticmethod
    def from_jar(zf: zipfile.ZipFile) -> NginxAnalysis:
        result = NginxAnalysis()
        conf_files = [n for n in zf.namelist() if n.endswith(('.conf', '.conf.ha'))]
        for name in conf_files:
            content = zf.read(name).decode('utf-8', 'replace')
            result.raw_files.append({'filename': PurePosixPath(name).name, 'path': name, 'content': content})
            is_ha = name.endswith('.ha')
            upstreams = NginxAnalyser._parse_upstreams(content, is_ha)
            if is_ha:
                result.ha_upstreams.extend(upstreams)
            else:
                result.upstreams.extend(upstreams)
                result.server_blocks.extend(NginxAnalyser._parse_server_blocks(content))

        # Extract unique service names from upstream names (e.g. catalog-upstream -> catalog)
        seen: set[str] = set()
        for u in result.upstreams + result.ha_upstreams:
            svc = u.name.replace('-upstream', '')
            if svc not in seen:
                seen.add(svc)
                result.service_dependencies.append(svc)

        return result

    @staticmethod
    def _parse_upstreams(content: str, is_ha: bool) -> list[NginxUpstream]:
        upstreams = []
        for m in re.finditer(r'upstream\s+(\S+)\s*\{([^}]+)\}', content, re.S):
            name = m.group(1)
            body = m.group(2)
            servers = re.findall(r'server\s+(\S+);', body)
            keepalive_m = re.search(r'keepalive\s+(\d+)', body)
            upstreams.append(NginxUpstream(
                name=name,
                servers=servers,
                keepalive=int(keepalive_m.group(1)) if keepalive_m else None,
                is_ha=is_ha,
            ))
        return upstreams

    @staticmethod
    def _parse_server_blocks(content: str) -> list[NginxServerBlock]:
        blocks = []
        for m in re.finditer(r'server\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}', content, re.S):
            body = m.group(1)
            ports = [int(p) for p in re.findall(r'listen\s+(\d+)', body)]
            names = re.findall(r'server_name\s+([^;]+);', body)
            ssl = bool(re.search(r'ssl\s+on|listen\s+\d+\s+ssl', body))
            locations = [{'path': lm.group(1)} for lm in re.finditer(r'location\s+(\S+)\s*\{', body)]
            if ports or names:
                blocks.append(NginxServerBlock(
                    listen_ports=ports,
                    server_names=[s.strip() for n in names for s in n.split()],
                    ssl=ssl,
                    locations=locations,
                ))
        return blocks


# ---------------------------------------------------------------------------
# Monitoring (Grafana + Prometheus)
# ---------------------------------------------------------------------------

@dataclass
class GrafanaDashboard:
    filename: str
    title: str | None
    panel_count: int
    panel_titles: list[str]

@dataclass
class GrafanaDatasource:
    name: str | None
    type: str | None
    url: str | None

@dataclass
class PrometheusJob:
    job_name: str
    metrics_path: str | None
    targets: list[str]
    scheme: str | None = None
    has_auth: bool = False
    has_tls: bool = False

@dataclass
class MonitoringAnalysis:
    grafana_dashboards: list[GrafanaDashboard] = field(default_factory=list)
    grafana_datasources: list[GrafanaDatasource] = field(default_factory=list)
    grafana_ini: dict = field(default_factory=dict)
    prometheus_jobs: list[PrometheusJob] = field(default_factory=list)
    raw_files: list[dict] = field(default_factory=list)


class MonitoringAnalyser:
    @staticmethod
    def from_jar(zf: zipfile.ZipFile) -> MonitoringAnalysis:
        result = MonitoringAnalysis()
        for name in zf.namelist():
            if name.endswith('/'):
                continue
            content = zf.read(name).decode('utf-8', 'replace')
            fname = PurePosixPath(name).name
            result.raw_files.append({'filename': fname, 'path': name, 'content': content})

            if fname == 'grafana.ini':
                result.grafana_ini = MonitoringAnalyser._parse_ini(content)
            elif 'datasource' in name.lower() and name.endswith(('.yml', '.yaml')):
                result.grafana_datasources.extend(MonitoringAnalyser._parse_datasources(content))
            elif name.endswith('.json') and 'dashboard' in name.lower():
                result.grafana_dashboards.append(MonitoringAnalyser._parse_dashboard(fname, content))
            elif fname == 'prometheus.yml' or fname == 'prometheus.yaml':
                result.prometheus_jobs.extend(MonitoringAnalyser._parse_prometheus(content))

        return result

    @staticmethod
    def _parse_ini(content: str) -> dict:
        sections: dict = {}
        current = 'default'
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if line.startswith('[') and line.endswith(']'):
                current = line[1:-1]
                sections[current] = {}
            elif '=' in line:
                k, _, v = line.partition('=')
                sections.setdefault(current, {})[k.strip()] = v.strip()
        return sections

    @staticmethod
    def _parse_datasources(content: str) -> list[GrafanaDatasource]:
        try:
            doc = yaml.safe_load(content)
            sources = []
            for ds in (doc or {}).get('datasources', []):
                sources.append(GrafanaDatasource(
                    name=ds.get('name'),
                    type=ds.get('type'),
                    url=ds.get('url'),
                ))
            return sources
        except Exception:
            return []

    @staticmethod
    def _parse_dashboard(filename: str, content: str) -> GrafanaDashboard:
        try:
            doc = json.loads(content)
            title = doc.get('title')
            panels = doc.get('panels', [])
            panel_titles = [p.get('title', '') for p in panels if isinstance(p, dict)]
            return GrafanaDashboard(filename=filename, title=title, panel_count=len(panels), panel_titles=panel_titles)
        except Exception:
            return GrafanaDashboard(filename=filename, title=None, panel_count=0, panel_titles=[])

    @staticmethod
    def _parse_prometheus(content: str) -> list[PrometheusJob]:
        try:
            doc = yaml.safe_load(content)
            jobs = []
            for job in (doc or {}).get('scrape_configs', []):
                targets = []
                for sc in job.get('static_configs', []):
                    targets.extend(sc.get('targets', []))
                jobs.append(PrometheusJob(
                    job_name=job.get('job_name', ''),
                    metrics_path=job.get('metrics_path'),
                    targets=targets,
                    scheme=job.get('scheme'),
                    has_auth='basic_auth' in job,
                    has_tls='tls_config' in job,
                ))
            return jobs
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Frontend / Node.js
# ---------------------------------------------------------------------------

@dataclass
class FrontendAnalysis:
    package_name: str | None = None
    package_version: str | None = None
    description: str | None = None
    node_scripts: dict = field(default_factory=dict)
    dependencies: dict = field(default_factory=dict)       # name -> version
    dev_dependencies: dict = field(default_factory=dict)
    framework: str | None = None                           # react, vue, angular, etc.
    server_entry_points: list[str] = field(default_factory=list)  # .js server files
    api_urls: list[dict] = field(default_factory=list)     # {key, value} from config YAML
    app_version: str | None = None                         # from version.json
    app_yml: dict = field(default_factory=dict)            # content/app.yml parsed
    env_vars: list[dict] = field(default_factory=list)     # {key, value} from sysconfig
    npm_deps: list[dict] = field(default_factory=list)     # flat list for dep table
    raw_files: list[dict] = field(default_factory=list)


class FrontendAnalyser:
    @staticmethod
    def from_jar(zf: zipfile.ZipFile) -> FrontendAnalysis:
        result = FrontendAnalysis()
        names = zf.namelist()

        # package.json (skip node_modules)
        pkg_candidates = [n for n in names if n.endswith('package.json') and 'node_modules' not in n]
        if pkg_candidates:
            try:
                raw = zf.read(pkg_candidates[0]).decode('utf-8', 'replace')
                doc = json.loads(raw)
                result.package_name = doc.get('name')
                result.package_version = doc.get('version')
                result.description = doc.get('description')
                result.node_scripts = doc.get('scripts', {})
                result.dependencies = doc.get('dependencies', {})
                result.dev_dependencies = doc.get('devDependencies', {})
                result.framework = FrontendAnalyser._detect_framework(result.dependencies)
                result.raw_files.append({'filename': 'package.json', 'path': pkg_candidates[0], 'content': raw})
                # Build flat npm_deps list for the dependency table
                for pkg, ver in result.dependencies.items():
                    result.npm_deps.append({'name': pkg, 'version': str(ver), 'dev': False})
                for pkg, ver in result.dev_dependencies.items():
                    result.npm_deps.append({'name': pkg, 'version': str(ver), 'dev': True})
            except Exception:
                pass

        # version.json
        ver_candidates = [n for n in names if n.endswith('version.json') and 'node_modules' not in n]
        if ver_candidates:
            try:
                doc = json.loads(zf.read(ver_candidates[0]).decode('utf-8', 'replace'))
                result.app_version = doc.get('version') or doc.get('appVersion')
            except Exception:
                pass

        # Server entry points (dist-server/*.js, excluding maps)
        result.server_entry_points = [
            n for n in names
            if 'dist-server' in n and n.endswith('.js') and not n.endswith('.map')
            and 'node_modules' not in n and not n.endswith('/')
        ]

        # config/*.yml — recursive YAML walk for url/uri keys
        config_files = [n for n in names if n.startswith('config/') and n.endswith(('.yml', '.yaml', '.properties'))]
        for cfg_name in config_files:
            content = zf.read(cfg_name).decode('utf-8', 'replace')
            result.raw_files.append({'filename': PurePosixPath(cfg_name).name, 'path': cfg_name, 'content': content})
            try:
                doc = yaml.safe_load(content)
                result.api_urls.extend(FrontendAnalyser._walk_urls(doc, ''))
            except Exception:
                pass

        # content/app.yml — SSL config, config-service URI, port
        if 'content/app.yml' in names:
            content = zf.read('content/app.yml').decode('utf-8', 'replace')
            result.raw_files.append({'filename': 'app.yml', 'path': 'content/app.yml', 'content': content})
            try:
                result.app_yml = yaml.safe_load(content) or {}
            except Exception:
                pass

        # bundle/etc/sysconfig/* — env vars / secrets list
        sysconfig = [n for n in names if '/sysconfig/' in n and not n.endswith('/')]
        for sc in sysconfig:
            content = zf.read(sc).decode('utf-8', 'replace')
            for line in content.splitlines():
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, _, v = line.partition('=')
                    result.env_vars.append({'key': k.strip(), 'value': v.strip()})

        return result

    @staticmethod
    def _detect_framework(deps: dict) -> str | None:
        checks = [('react', 'React'), ('vue', 'Vue'), ('@angular/core', 'Angular'),
                  ('svelte', 'Svelte'), ('next', 'Next.js'), ('nuxt', 'Nuxt')]
        for key, name in checks:
            if key in deps:
                return name
        return None

    @staticmethod
    def _walk_urls(node: any, prefix: str) -> list[dict]:
        """Recursively walk a parsed YAML doc, yielding {key, value} for url/uri leaves."""
        results = []
        if isinstance(node, dict):
            for k, v in node.items():
                path = f'{prefix}.{k}' if prefix else k
                if isinstance(v, (dict, list)):
                    results.extend(FrontendAnalyser._walk_urls(v, path))
                elif isinstance(v, str) and k.lower() in ('url', 'uri') and v.strip():
                    results.append({'key': path, 'value': v.strip()})
        elif isinstance(node, list):
            for item in node:
                results.extend(FrontendAnalyser._walk_urls(item, prefix))
        return results
