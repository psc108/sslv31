"""Inter-service dependency graph builder.

Aggregates three already-extracted data sources into a structured topology:
  1. Consumed events  — cross-service event consumers (source_service field)
  2. Nginx upstreams  — services proxied by each load-balancer
  3. Frontend API URLs — which backend services each UI calls

Output: { nodes: [{id, type, port}], edges: [{from, to, via, label}] }
  via: "event" | "nginx" | "api_url"
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Node type classification
# ---------------------------------------------------------------------------

_UI_NAMES = {"portal-ui", "management-ui", "frontend-lb", "frontend"}
_LB_NAMES = {"frontend-lb", "backend-lb"}
_INFRA_NAMES = {"config", "config-svc", "blobstore", "blobstore-svc", "blob-service"}


def _node_type(name: str) -> str:
    if name in _LB_NAMES:
        return "load_balancer"
    if name in _UI_NAMES:
        return "frontend"
    if "ui" in name or "portal" in name:
        return "frontend"
    if name in _INFRA_NAMES or "config" in name or "blob" in name:
        return "infrastructure"
    return "service"


def _normalise(name: str) -> str:
    """Strip common suffixes so 'catalog-svc' and 'catalog' resolve to the same node."""
    return re.sub(r"-svc$|-upstream$|-service$", "", name.lower().strip())


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_dependency_graph(sub_reports: list[dict]) -> dict[str, Any]:
    """
    sub_reports: list of dicts with keys:
      service_name, declared_port, installer_metadata, event_files, config_files
    Returns { nodes, edges } suitable for JSON serialisation.
    """
    nodes: dict[str, dict] = {}   # id -> node dict
    edges: list[dict] = []
    seen_edges: set[tuple] = set()

    def _add_node(name: str, port: int | None = None) -> str:
        nid = _normalise(name)
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": name, "type": _node_type(nid), "port": port}
        elif port and not nodes[nid]["port"]:
            nodes[nid]["port"] = port
        return nid

    def _add_edge(frm: str, to: str, via: str, label: str = "") -> None:
        key = (frm, to, via)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": frm, "to": to, "via": via, "label": label})

    # ── Pass 1: register all known services as nodes ──────────────────────
    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename", "unknown")
        _add_node(svc, sr.get("declared_port"))

    # ── Pass 2: consumed events → edges ──────────────────────────────────
    for sr in sub_reports:
        consumer = _normalise(sr.get("service_name") or sr.get("filename", ""))
        for ef in sr.get("event_files", []):
            for c in ef.get("consumed", []):
                src = c.get("source_service")
                if not src:
                    continue
                publisher = _normalise(src)
                _add_node(publisher)
                _add_node(consumer)
                entity = c.get("entity") or ""
                action = c.get("action") or ""
                lbl = f"{entity}{action}" if entity else ""
                _add_edge(publisher, consumer, "event", lbl)

    # ── Pass 3: nginx upstreams → edges ──────────────────────────────────
    for sr in sub_reports:
        lb = _normalise(sr.get("service_name") or sr.get("filename", ""))
        meta = sr.get("installer_metadata") or {}
        nginx = meta.get("nginx") or {}
        for upstream in nginx.get("upstreams", []):
            uname = upstream.get("name", "")
            target = _normalise(uname)
            if target and target != lb:
                _add_node(target)
                _add_edge(lb, target, "nginx", uname)

    # ── Pass 4: frontend API URL config → edges ───────────────────────────
    _API_KEY_RE = re.compile(r"^api\.([a-z0-9_-]+)\.url$", re.IGNORECASE)
    for sr in sub_reports:
        caller = _normalise(sr.get("service_name") or sr.get("filename", ""))
        for cf in sr.get("config_files", []):
            for k in cf.get("keys", []):
                key = k.get("key", "")
                val = k.get("value", "") or ""
                m = _API_KEY_RE.match(key)
                if not m:
                    continue
                target_raw = m.group(1)
                target = _normalise(target_raw)
                # Try to extract port from URL value
                port_match = re.search(r":(\d{4,5})/", val)
                port = int(port_match.group(1)) if port_match else None
                _add_node(target, port)
                _add_node(caller)
                _add_edge(caller, target, "api_url", key)

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Mermaid diagram generator (for storefront guide)
# ---------------------------------------------------------------------------

def graph_to_mermaid(graph: dict[str, Any]) -> str:
    lines = ["graph LR"]
    # Node declarations with shape by type
    for node in graph["nodes"]:
        nid = node["id"].replace("-", "_")
        label = node["label"]
        port = f":{node['port']}" if node.get("port") else ""
        t = node["type"]
        if t == "load_balancer":
            lines.append(f'  {nid}["{label}{port}"]:::lb')
        elif t == "frontend":
            lines.append(f'  {nid}("{label}"):::ui')
        elif t == "infrastructure":
            lines.append(f'  {nid}[("{label}")]:::infra')
        else:
            lines.append(f'  {nid}["{label}{port}"]')

    # Edges grouped by via
    _STYLE = {"event": "-->|event|", "nginx": "-.->|proxy|", "api_url": "-->|API|"}
    for edge in graph["edges"]:
        frm = edge["from"].replace("-", "_")
        to = edge["to"].replace("-", "_")
        arrow = _STYLE.get(edge["via"], "-->")
        lines.append(f"  {frm} {arrow} {to}")

    lines += [
        "  classDef lb fill:#fbbf24,stroke:#d97706,color:#000",
        "  classDef ui fill:#818cf8,stroke:#4f46e5,color:#fff",
        "  classDef infra fill:#6b7280,stroke:#374151,color:#fff",
    ]
    return "\n".join(lines)
