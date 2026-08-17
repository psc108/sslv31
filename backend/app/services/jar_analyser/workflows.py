"""Workflow detection and parsing for JAR Analyser Stage 3.

Two sources:
  1. Auto-detection — heuristic patterns over discovered endpoints + frontend API URLs
  2. Manual YAML — uploaded workflows.yml defining named ordered sequences
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    name: str
    method: str
    path: str
    description: str | None = None
    input_from: dict = field(default_factory=dict)   # var_name -> source expression
    output: str | None = None                         # variable this step produces
    query_params: dict = field(default_factory=dict)
    body_fields: list[str] = field(default_factory=list)
    poll_until: str | None = None
    endpoint_ref: str | None = None                   # matched signature_key


@dataclass
class Workflow:
    name: str
    description: str | None
    category: str                                     # ordering | management | monitoring | admin
    steps: list[WorkflowStep]
    source: str                                       # auto_detected | manual


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class WorkflowDetector:

    # -----------------------------------------------------------------------
    # Auto-detection
    # -----------------------------------------------------------------------

    @staticmethod
    def detect(endpoints: list[dict], api_urls: list[dict] | None = None) -> list[Workflow]:
        """
        Heuristic workflow detection from endpoint list and optional frontend API URL config.

        Strategy:
        1. Group endpoints by path prefix (first two segments) to find domain clusters.
        2. Within each cluster, look for the canonical CRUD+status+resources pattern.
        3. Each cluster that has at least a POST (create) + GET (list or get-by-id) becomes
           a candidate workflow.
        """
        workflows: list[Workflow] = []

        # Index endpoints by path for quick lookup
        by_path: dict[str, list[dict]] = {}
        for ep in endpoints:
            by_path.setdefault(ep["full_path"], []).append(ep)

        # Group by root resource (first non-empty path segment)
        clusters: dict[str, list[dict]] = {}
        for ep in endpoints:
            root = _path_root(ep["full_path"])
            if root:
                clusters.setdefault(root, []).append(ep)

        for root, eps in clusters.items():
            wf = WorkflowDetector._build_crud_workflow(root, eps)
            if wf:
                workflows.append(wf)

        # Deduplicate by name
        seen: set[str] = set()
        unique: list[Workflow] = []
        for wf in workflows:
            if wf.name not in seen:
                seen.add(wf.name)
                unique.append(wf)

        return unique

    @staticmethod
    def _build_crud_workflow(root: str, eps: list[dict]) -> Workflow | None:
        """
        Given a set of endpoints sharing a root resource path, build a workflow
        if there is enough structure to be useful (at least a list + create or
        a create + status/result pattern).
        """
        # Classify endpoints
        list_ep = _find_ep(eps, "GET", lambda p: not _has_id_segment(p))
        create_ep = _find_ep(eps, "POST", lambda p: not _has_id_segment(p))
        get_ep = _find_ep(eps, "GET", _has_id_segment)
        update_ep = _find_ep(eps, "PUT", _has_id_segment) or _find_ep(eps, "PATCH", _has_id_segment)
        delete_ep = _find_ep(eps, "DELETE", _has_id_segment)
        status_ep = _find_ep(eps, "GET", lambda p: p.rstrip("/").endswith("/status"))
        result_ep = _find_ep(eps, "GET", lambda p: any(
            p.rstrip("/").endswith(s) for s in ("/resources", "/result", "/details", "/output")
        ))

        # Need at minimum a list or create endpoint
        if not list_ep and not create_ep:
            return None

        resource = root.strip("/").replace("-", " ").replace("_", " ").title()
        steps: list[WorkflowStep] = []
        id_var = _id_var_name(root)

        if list_ep:
            steps.append(WorkflowStep(
                name=f"List {resource}",
                method="GET",
                path=list_ep["full_path"],
                description=f"Browse available {resource.lower()}",
                endpoint_ref=list_ep.get("signature_key"),
            ))

        if create_ep:
            body_fields = _body_fields_from_ep(create_ep)
            steps.append(WorkflowStep(
                name=f"Create {resource}",
                method="POST",
                path=create_ep["full_path"],
                description=f"Submit a new {resource.lower()} record",
                body_fields=body_fields,
                output=id_var,
                endpoint_ref=create_ep.get("signature_key"),
            ))

        if status_ep:
            steps.append(WorkflowStep(
                name=f"Poll {resource} status",
                method="GET",
                path=status_ep["full_path"],
                description=f"Poll until {resource.lower()} reaches terminal state",
                input_from={id_var: f"previous.{id_var}"},
                poll_until="response.status == 'COMPLETED'",
                endpoint_ref=status_ep.get("signature_key"),
            ))

        if result_ep:
            steps.append(WorkflowStep(
                name=f"Get {resource} result",
                method="GET",
                path=result_ep["full_path"],
                description=f"Retrieve the provisioned {resource.lower()} details",
                input_from={id_var: f"previous.{id_var}"},
                endpoint_ref=result_ep.get("signature_key"),
            ))

        if get_ep and not status_ep and not result_ep:
            steps.append(WorkflowStep(
                name=f"Get {resource}",
                method="GET",
                path=get_ep["full_path"],
                description=f"Retrieve a specific {resource.lower()} by ID",
                input_from={id_var: f"previous.{id_var}"},
                endpoint_ref=get_ep.get("signature_key"),
            ))

        if update_ep:
            steps.append(WorkflowStep(
                name=f"Update {resource}",
                method=update_ep["http_method"],
                path=update_ep["full_path"],
                description=f"Update an existing {resource.lower()}",
                input_from={id_var: f"previous.{id_var}"},
                body_fields=_body_fields_from_ep(update_ep),
                endpoint_ref=update_ep.get("signature_key"),
            ))

        if delete_ep:
            steps.append(WorkflowStep(
                name=f"Delete {resource}",
                method="DELETE",
                path=delete_ep["full_path"],
                description=f"Remove the {resource.lower()}",
                input_from={id_var: f"previous.{id_var}"},
                endpoint_ref=delete_ep.get("signature_key"),
            ))

        if len(steps) < 2:
            return None

        category = _guess_category(root)
        return Workflow(
            name=f"Manage {resource}",
            description=f"Auto-detected workflow for {resource.lower()} operations",
            category=category,
            steps=steps,
            source="auto_detected",
        )

    # -----------------------------------------------------------------------
    # Manual YAML
    # -----------------------------------------------------------------------

    @staticmethod
    def from_yaml(content: str, endpoints: list[dict]) -> list[Workflow]:
        """Parse a workflows.yml file and resolve endpoint references."""
        try:
            doc = yaml.safe_load(content)
        except Exception as e:
            raise ValueError(f"Invalid YAML: {e}") from e

        if not isinstance(doc, dict) or "workflows" not in doc:
            raise ValueError("YAML must have a top-level 'workflows' key")

        # Build signature index for matching
        sig_index: dict[str, str] = {}  # "METHOD:/path" -> signature_key
        for ep in endpoints:
            key = f"{ep['http_method']}:{ep['full_path']}"
            sig_index[key] = ep.get("signature_key", key)

        workflows: list[Workflow] = []
        for raw in doc["workflows"]:
            if not isinstance(raw, dict):
                continue
            steps: list[WorkflowStep] = []
            for rs in raw.get("steps", []):
                method = str(rs.get("method", "GET")).upper()
                path = str(rs.get("path", ""))
                sig_key = f"{method}:{path}"
                steps.append(WorkflowStep(
                    name=str(rs.get("name", path)),
                    method=method,
                    path=path,
                    description=rs.get("description"),
                    input_from=rs.get("input_from") or {},
                    output=rs.get("output"),
                    query_params=rs.get("query_params") or {},
                    body_fields=rs.get("body_fields") or [],
                    poll_until=rs.get("poll_until"),
                    endpoint_ref=sig_index.get(sig_key),
                ))
            if not steps:
                continue
            workflows.append(Workflow(
                name=str(raw.get("name", "Unnamed Workflow")),
                description=raw.get("description"),
                category=str(raw.get("category", "management")),
                steps=steps,
                source="manual",
            ))

        return workflows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _path_root(path: str) -> str:
    """Return the first meaningful non-empty, non-variable, non-version path segment."""
    _SKIP_SEGMENTS = {"api", "v1", "v2", "v3", "rest", "service", "services"}
    for seg in path.strip("/").split("/"):
        if seg and not seg.startswith("{") and seg.lower() not in _SKIP_SEGMENTS:
            return seg
    return ""


def _has_id_segment(path: str) -> bool:
    return bool(re.search(r"/\{[^}]+\}", path))


def _find_ep(
    eps: list[dict],
    method: str,
    path_pred,
) -> dict | None:
    for ep in eps:
        if ep["http_method"] == method and path_pred(ep["full_path"]):
            return ep
    return None


def _body_fields_from_ep(ep: dict) -> list[str]:
    body = ep.get("request_body")
    if not body:
        return []
    # Return the simple type name as a hint; field-level detail comes from Stage 1 schemas
    simple = body.get("simple_type") or body.get("java_type") or ""
    return [simple] if simple else []


def _id_var_name(root: str) -> str:
    """Derive a camelCase ID variable name from the resource root path segment."""
    singular = root.rstrip("s").replace("-", "_")
    parts = singular.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:]) + "Id"


def _guess_category(root: str) -> str:
    root_lower = root.lower()
    if any(x in root_lower for x in ("order", "provision", "deploy", "request", "purchase")):
        return "ordering"
    if any(x in root_lower for x in ("monitor", "metric", "alert", "health", "status")):
        return "monitoring"
    if any(x in root_lower for x in ("admin", "user", "role", "permission", "config", "setting")):
        return "admin"
    return "management"
