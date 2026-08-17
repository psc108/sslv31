"""Postman Collection v2.1 generator — Stage 7."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone


def _example_value(field: dict) -> object:
    t = field.get("openapi_type", "string")
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    fmt = field.get("openapi_format", "")
    if fmt == "uuid":
        return "00000000-0000-0000-0000-000000000000"
    if fmt in ("date",):
        return "2024-01-01"
    if fmt in ("date-time",):
        return "2024-01-01T00:00:00Z"
    return f"<{field.get('json_name', 'value')}>"


def _build_example_body(simple_type: str, schemas: dict[str, dict]) -> dict:
    schema = schemas.get(simple_type)
    if not schema:
        return {}
    fields = [f for f in (schema.get("fields") or []) if not f.get("json_ignored")]
    return {f["json_name"]: _example_value(f) for f in fields}


def _path_to_postman(path: str) -> tuple[list[str], list[dict]]:
    """Split path into segments list and extract path variable objects."""
    segments = [s for s in path.strip("/").split("/") if s]
    variables = []
    postman_segments = []
    for seg in segments:
        m = re.match(r"^\{(.+)\}$", seg)
        if m:
            name = m.group(1)
            postman_segments.append(f":{name}")
            variables.append({"key": name, "value": f"{{{{{name}}}}}", "description": ""})
        else:
            postman_segments.append(seg)
    return postman_segments, variables


class PostmanGenerator:

    @staticmethod
    def generate(
        service_name: str,
        port: int,
        version: str,
        endpoints: list[dict],
        schemas: list[dict] | None = None,
    ) -> dict:
        schema_map = {s["simple_name"]: s for s in (schemas or [])}
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Collect all path variables across all endpoints for the environment
        all_path_vars: set[str] = set()

        # Group by controller
        by_controller: dict[str, list[dict]] = {}
        for ep in endpoints:
            ctrl = ep.get("controller_simple") or "Default"
            by_controller.setdefault(ctrl, []).append(ep)

        folders = []
        for ctrl, eps in by_controller.items():
            items = []
            for ep in eps:
                path = ep.get("full_path", "/")
                method = ep.get("http_method", "GET")
                params = ep.get("parameters") or []
                body_info = ep.get("request_body")

                path_params = [p for p in params if p.get("location") == "path"]
                query_params = [p for p in params if p.get("location") == "query"]

                segments, path_vars = _path_to_postman(path)
                for pv in path_vars:
                    all_path_vars.add(pv["key"])

                # URL object
                raw_url = "{{baseUrl}}/" + "/".join(segments)
                if query_params:
                    qs = "&".join(f"{p['name']}={{{{{p['name']}}}}}" for p in query_params)
                    raw_url += "?" + qs

                url_obj: dict = {
                    "raw": raw_url,
                    "host": ["{{baseUrl}}"],
                    "path": segments,
                }
                if query_params:
                    url_obj["query"] = [
                        {"key": p["name"], "value": f"{{{{{p['name']}}}}}", "disabled": False}
                        for p in query_params
                    ]
                if path_vars:
                    url_obj["variable"] = path_vars

                # Headers
                headers = [{"key": "Authorization", "value": "Bearer {{token}}"}]

                # Request body
                request: dict = {
                    "method": method,
                    "header": headers,
                    "url": url_obj,
                }
                if body_info:
                    simple = body_info.get("simple_type") or body_info.get("java_type") or ""
                    example = _build_example_body(simple, schema_map)
                    request["body"] = {
                        "mode": "raw",
                        "raw": json.dumps(example, indent=2),
                        "options": {"raw": {"language": "json"}},
                    }
                    headers.append({"key": "Content-Type", "value": "application/json"})

                item: dict = {
                    "name": f"{method} {path}",
                    "request": request,
                    "response": [],
                    "event": [
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": ["pm.test(\"Status is 2xx\", () => pm.response.to.be.success)"],
                            },
                        }
                    ],
                }
                items.append(item)

            folders.append({"name": ctrl, "item": items})

        # Environment variables
        variables = [
            {"key": "baseUrl", "value": f"http://localhost:{port}", "type": "default"},
            {"key": "token", "value": "", "type": "secret"},
        ]
        for var in sorted(all_path_vars):
            variables.append({"key": var, "value": "", "type": "default"})

        return {
            "info": {
                "_postman_id": str(uuid.uuid4()),
                "name": f"{service_name} — v{version}",
                "description": f"Auto-generated from JAR bytecode analysis. Generated: {generated_at}",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": folders,
            "variable": variables,
        }
