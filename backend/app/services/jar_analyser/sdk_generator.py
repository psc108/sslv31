"""JavaScript / TypeScript SDK generator — Stage 4.

Generates a self-contained, dependency-free JS or TS client from the
analysed endpoint + schema data.  Output is a single file string; nothing
is stored in the database.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _camel(name: str) -> str:
    """Convert a snake_case or kebab-case name to camelCase."""
    parts = re.split(r"[-_\s]+", name)
    return parts[0].lower() + "".join(p.title() for p in parts[1:])


def _pascal(name: str) -> str:
    parts = re.split(r"[-_\s]+", name)
    return "".join(p.title() for p in parts)


def _method_name(ep: dict) -> str:
    """Derive a camelCase method name from an endpoint."""
    method = ep["http_method"].lower()
    path = ep["full_path"]
    # Strip path params and split on /
    segments = [s for s in path.strip("/").split("/")
                if s and not s.startswith("{")]
    if not segments:
        return method
    # Use last 2 meaningful segments
    meaningful = segments[-2:] if len(segments) >= 2 else segments
    name = _camel("_".join(meaningful))
    # Prefix with HTTP verb if not already implied
    prefixes = {"get": "get", "post": "create", "put": "update",
                "patch": "patch", "delete": "delete"}
    verb = prefixes.get(method, method)
    if not name.lower().startswith(verb):
        name = verb + name[0].upper() + name[1:]
    return name


def _path_to_template(path: str) -> str:
    """Convert /foo/{id}/bar to /foo/${id}/bar for template literals."""
    return re.sub(r"\{([^}]+)\}", r"${\1}", path)


def _openapi_to_ts(openapi_type: str, fmt: str | None, simple_type: str) -> str:
    if openapi_type == "integer":
        return "number"
    if openapi_type == "number":
        return "number"
    if openapi_type == "boolean":
        return "boolean"
    if openapi_type == "array":
        return "unknown[]"
    if openapi_type == "object":
        return "Record<string, unknown>"
    if openapi_type == "null":
        return "void"
    return "string"


# ---------------------------------------------------------------------------
# Per-service SDK generator
# ---------------------------------------------------------------------------

class JsSdkGenerator:

    @staticmethod
    def generate(
        service_name: str,
        port: int,
        version: str,
        filename: str,
        endpoints: list[dict],
        schemas: list[dict] | None = None,
        workflows: list[dict] | None = None,
        typescript: bool = False,
    ) -> str:
        schemas = schemas or []
        workflows = workflows or []
        ext = "ts" if typescript else "js"
        class_name = _pascal(service_name) + "Client"
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        lines: list[str] = []

        # ---- Header comment ----
        lines += [
            f"// {'=' * 60}",
            f"// {service_name}-sdk.{ext}",
            f"// Auto-generated from JAR bytecode analysis",
            f"// Service: {service_name}  Version: {version}  Port: {port}",
            f"// Generated: {generated_at}",
            f"// DO NOT EDIT — regenerate from JAR Analyser",
            f"// {'=' * 60}",
            "",
        ]

        # ---- TypeScript interfaces ----
        if typescript and schemas:
            schema_map = {s["simple_name"]: s for s in schemas}
            for schema in schemas:
                if schema.get("is_enum"):
                    values = schema.get("enum_values") or []
                    serialised = [v.get("serialised_as", v.get("name", "")) for v in values]
                    if serialised:
                        union = " | ".join(f'"{v}"' for v in serialised)
                        lines.append(f"export type {schema['simple_name']} = {union}")
                else:
                    fields = schema.get("fields") or []
                    visible = [f for f in fields if not f.get("json_ignored")]
                    if not visible:
                        continue
                    lines.append(f"export interface {schema['simple_name']} {{")
                    for f in visible:
                        opt = "" if f.get("required") else "?"
                        ts_type = _openapi_to_ts(
                            f.get("openapi_type", "string"),
                            f.get("openapi_format"),
                            f.get("simple_type", ""),
                        )
                        # Use enum type name if available
                        simple = f.get("simple_type", "")
                        if simple in schema_map and schema_map[simple].get("is_enum"):
                            ts_type = simple
                        elif f.get("is_collection"):
                            elem = f.get("collection_element_type") or "unknown"
                            elem_ts = elem if elem in schema_map else "unknown"
                            ts_type = f"{elem_ts}[]"
                        elif f.get("openapi_type") == "object" and simple in schema_map:
                            ts_type = simple
                        nullable = " | null" if f.get("nullable") else ""
                        lines.append(f"  {f['json_name']}{opt}: {ts_type}{nullable}")
                    lines.append("}")
            lines.append("")

        # ---- Class declaration ----
        if typescript:
            lines += [
                f"export class {class_name} {{",
                f"  private baseUrl: string",
                f"  private token?: string",
                f"  private apiKey?: string",
                "",
                f"  constructor({{ baseUrl = 'http://localhost:{port}', token, apiKey }}: {{",
                f"    baseUrl?: string; token?: string; apiKey?: string",
                f"  }} = {{}}) {{",
                f"    this.baseUrl = baseUrl.replace(/\\/$/, '')",
                f"    this.token = token",
                f"    this.apiKey = apiKey",
                f"  }}",
            ]
        else:
            lines += [
                f"class {class_name} {{",
                f"  constructor({{ baseUrl = 'http://localhost:{port}', token, apiKey }} = {{}}) {{",
                f"    this.baseUrl = baseUrl.replace(/\\/$/, '')",
                f"    this.token = token",
                f"    this.apiKey = apiKey",
                f"  }}",
            ]

        lines += [
            "",
            "  _headers(extra = {}) {",
            "    return {",
            "      'Content-Type': 'application/json',",
            "      ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),",
            "      ...(this.apiKey ? { 'X-API-Key': this.apiKey } : {}),",
            "      ...extra,",
            "    }",
            "  }",
            "",
        ]

        if typescript:
            lines += [
                "  async _request<T = unknown>(method: string, path: string, { body, params }: { body?: unknown; params?: Record<string, unknown> } = {}): Promise<T> {",
            ]
        else:
            lines += [
                "  async _request(method, path, { body, params } = {}) {",
            ]

        lines += [
            "    const url = new URL(this.baseUrl + path)",
            "    if (params) {",
            "      Object.entries(params).forEach(([k, v]) => {",
            "        if (v !== undefined && v !== null) url.searchParams.set(k, String(v))",
            "      })",
            "    }",
            "    const res = await fetch(url.toString(), {",
            "      method,",
            "      headers: this._headers(),",
            "      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),",
            "    })",
            "    if (!res.ok) {",
            "      const err = await res.json().catch(() => ({ message: res.statusText }))",
            "      throw Object.assign(new Error(err.message ?? res.statusText), { status: res.status, body: err })",
            "    }",
            "    return res.status === 204 ? null : res.json()",
            "  }",
            "",
        ]

        # ---- Group endpoints by controller ----
        by_controller: dict[str, list[dict]] = {}
        for ep in endpoints:
            ctrl = ep.get("controller_simple", "Unknown")
            by_controller.setdefault(ctrl, []).append(ep)

        schema_map = {s["simple_name"]: s for s in schemas}

        for ctrl, eps in by_controller.items():
            lines.append(f"  // ---- {ctrl} ----")
            lines.append("")
            for ep in eps:
                method_nm = _method_name(ep)
                http = ep["http_method"]
                path = ep["full_path"]
                params = ep.get("parameters") or []
                body = ep.get("request_body")
                ret = ep.get("return_type")

                path_params = [p for p in params if p.get("location") == "path"]
                query_params = [p for p in params if p.get("location") == "query"]
                has_body = body is not None

                # Build JSDoc / comment
                lines.append(f"  /** {http} {path} */")

                # Build signature
                sig_parts: list[str] = []
                for p in path_params:
                    if typescript:
                        sig_parts.append(f"{p['name']}: {_openapi_to_ts(p.get('simple_type','string').lower(), None, '')}")
                    else:
                        sig_parts.append(p["name"])

                if has_body:
                    if typescript:
                        body_type = body.get("simple_type") or "unknown"
                        if body_type in schema_map:
                            sig_parts.append(f"body: {body_type}")
                        else:
                            sig_parts.append("body: Record<string, unknown>")
                    else:
                        sig_parts.append("body")

                if query_params:
                    if typescript:
                        qp_fields = ", ".join(
                            f"{p['name']}?: {_openapi_to_ts(p.get('simple_type','string').lower(), None, '')}"
                            for p in query_params
                        )
                        sig_parts.append(f"{{ {qp_fields} }}: {{ {qp_fields} }} = {{}}")
                    else:
                        qp_names = ", ".join(p["name"] for p in query_params)
                        sig_parts.append(f"{{ {qp_names} }} = {{}}")

                # Return type annotation for TS
                ret_annotation = ""
                if typescript:
                    if ret and ret.get("simple_type") and ret["simple_type"] != "void":
                        rt = ret["simple_type"]
                        if rt in schema_map:
                            ret_annotation = f": Promise<{rt}>"
                        else:
                            ret_annotation = ": Promise<unknown>"
                    else:
                        ret_annotation = ": Promise<unknown>"

                sig = ", ".join(sig_parts)
                lines.append(f"  {method_nm}({sig}){ret_annotation} {{")

                # Build path expression
                has_path_vars = bool(path_params)
                if has_path_vars:
                    path_expr = f"`{_path_to_template(path)}`"
                else:
                    path_expr = f"'{path}'"

                # Build call
                call_args = [f"'{http}'", path_expr]
                extras: list[str] = []
                if has_body:
                    extras.append("body")
                if query_params:
                    qp_obj = "{ " + ", ".join(p["name"] for p in query_params) + " }"
                    extras.append(f"params: {qp_obj}")
                if extras:
                    call_args.append("{ " + ", ".join(extras) + " }")

                lines.append(f"    return this._request({', '.join(call_args)})")
                lines.append("  }")
                lines.append("")

        lines.append("}")
        lines.append("")

        # ---- Exports ----
        lines += [
            f"export default {class_name}",
            f"export {{ {class_name} }}",
        ]

        return "\n".join(lines)

    @staticmethod
    def generate_combined(
        services: list[dict],  # [{name, port, version, filename, class_name, endpoints, schemas, workflows}]
        typescript: bool = False,
    ) -> str:
        """Generate a combined SDK importing all per-service clients."""
        ext = "ts" if typescript else "js"
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines: list[str] = [
            f"// {'=' * 60}",
            f"// platform-sdk.{ext}",
            f"// Auto-generated combined SDK — all services",
            f"// Generated: {generated_at}",
            f"// DO NOT EDIT — regenerate from JAR Analyser",
            f"// {'=' * 60}",
            "",
        ]

        # Inline each service SDK then wrap in PlatformClient
        class_names: list[tuple[str, str]] = []  # (service_name, class_name)
        for svc in services:
            svc_sdk = JsSdkGenerator.generate(
                service_name=svc["name"],
                port=svc["port"],
                version=svc["version"],
                filename=svc["filename"],
                endpoints=svc["endpoints"],
                schemas=svc.get("schemas"),
                workflows=svc.get("workflows"),
                typescript=typescript,
            )
            lines.append(f"// {'─' * 58}")
            lines.append(f"// Service: {svc['name']}")
            lines.append(f"// {'─' * 58}")
            lines.append("")
            lines.append(svc_sdk)
            lines.append("")
            class_names.append((svc["name"], _pascal(svc["name"]) + "Client"))

        # PlatformClient wrapper
        if typescript:
            lines += [
                "export class PlatformClient {",
            ]
            for svc_name, cls in class_names:
                prop = _camel(svc_name)
                lines.append(f"  {prop}: {cls}")
            lines += [
                "",
                "  constructor(config: { baseUrl?: string; token?: string; apiKey?: string } = {}) {",
            ]
        else:
            lines += [
                "class PlatformClient {",
                "  constructor(config = {}) {",
            ]

        for svc_name, cls in class_names:
            prop = _camel(svc_name)
            # Build per-service baseUrl from port if available
            svc_data = next((s for s in services if s["name"] == svc_name), None)
            port = svc_data["port"] if svc_data else 8080
            lines.append(f"    this.{prop} = new {cls}(config)")

        lines += [
            "  }",
            "}",
            "",
            "export default PlatformClient",
            "export { PlatformClient }",
        ]

        return "\n".join(lines)
